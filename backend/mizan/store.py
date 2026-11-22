"""Storage layer.

Two implementations with the same interface:
* MemoryStore  - everything in RAM (unit tests, evaluation runs, quick demo).
* PgStore      - PostgreSQL + pgvector (deployed system). Relational tables for
                 documents, financials, watchlist, alerts and query logs; a vector
                 column on chunks for dense search.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Iterable, Optional

import numpy as np

from .models import Alert, Answer, Chunk, Document, FinancialHighlights


class Store(ABC):
    # documents ---------------------------------------------------------------
    @abstractmethod
    def add_document(self, doc: Document, chunks: list[Chunk], pages: dict[int, str]) -> None: ...
    @abstractmethod
    def get_document(self, doc_id: str) -> Optional[Document]: ...
    @abstractmethod
    def list_documents(self, symbol: str | None = None) -> list[Document]: ...
    @abstractmethod
    def get_page(self, doc_id: str, page: int) -> Optional[str]: ...
    # chunks + vectors ----------------------------------------------------------
    @abstractmethod
    def chunks(self, doc_ids: Iterable[str] | None = None) -> list[Chunk]: ...
    @abstractmethod
    def set_embeddings(self, chunk_ids: list[str], vectors: np.ndarray) -> None: ...
    @abstractmethod
    def missing_embeddings(self) -> list[Chunk]: ...
    @abstractmethod
    def dense_search(self, qvec: np.ndarray, k: int, doc_ids: Iterable[str] | None = None) -> list[tuple[Chunk, float]]: ...
    # structured data -------------------------------------------------------------
    @abstractmethod
    def save_financials(self, doc_id: str, fh: FinancialHighlights) -> None: ...
    @abstractmethod
    def get_financials(self, doc_id: str) -> Optional[FinancialHighlights]: ...
    # watchlist / alerts / logs -----------------------------------------------------
    @abstractmethod
    def watch(self, symbol: str, chat_id: str = "", email: str = "") -> None: ...
    @abstractmethod
    def watchlist(self) -> list[dict]: ...
    @abstractmethod
    def add_alert(self, alert: Alert) -> None: ...
    @abstractmethod
    def alerts(self, limit: int = 50) -> list[Alert]: ...
    @abstractmethod
    def log_answer(self, ans: Answer) -> None: ...
    @abstractmethod
    def answer_log(self, limit: int = 500) -> list[Answer]: ...


class MemoryStore(Store):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.docs: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._pages: dict[tuple[str, int], str] = {}
        self._vecs: dict[str, np.ndarray] = {}
        self._fin: dict[str, FinancialHighlights] = {}
        self._watch: dict[str, dict] = {}
        self._alerts: list[Alert] = []
        self._log: list[Answer] = []

    def __getstate__(self):          # allow pickling (evaluation cache)
        d = self.__dict__.copy()
        d.pop("_lock", None)
        return d

    def __setstate__(self, d):
        self.__dict__.update(d)
        self._lock = threading.Lock()

    def add_document(self, doc, chunks, pages):
        with self._lock:
            self.docs[doc.doc_id] = doc
            for c in chunks:
                self._chunks[c.chunk_id] = c
            for p, t in pages.items():
                self._pages[(doc.doc_id, p)] = t

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def list_documents(self, symbol=None):
        docs = list(self.docs.values())
        return [d for d in docs if not symbol or d.symbol.upper() == symbol.upper()]

    def get_page(self, doc_id, page):
        return self._pages.get((doc_id, page))

    def chunks(self, doc_ids=None):
        if doc_ids is None:
            return list(self._chunks.values())
        ids = set(doc_ids)
        return [c for c in self._chunks.values() if c.doc_id in ids]

    def set_embeddings(self, chunk_ids, vectors):
        with self._lock:
            for cid, v in zip(chunk_ids, vectors):
                self._vecs[cid] = np.asarray(v, dtype=np.float32)

    def missing_embeddings(self):
        return [c for cid, c in self._chunks.items() if cid not in self._vecs]

    def dense_search(self, qvec, k, doc_ids=None):
        cands = self.chunks(doc_ids)
        cands = [c for c in cands if c.chunk_id in self._vecs]
        if not cands:
            return []
        mat = np.stack([self._vecs[c.chunk_id] for c in cands])
        sims = mat @ np.asarray(qvec, dtype=np.float32)   # vectors are L2-normalised
        top = np.argsort(-sims)[:k]
        return [(cands[i], float(sims[i])) for i in top]

    def save_financials(self, doc_id, fh):
        self._fin[doc_id] = fh

    def get_financials(self, doc_id):
        return self._fin.get(doc_id)

    def watch(self, symbol, chat_id="", email=""):
        self._watch[symbol.upper()] = {"symbol": symbol.upper(), "chat_id": chat_id, "email": email}

    def watchlist(self):
        return list(self._watch.values())

    def add_alert(self, alert):
        self._alerts.append(alert)

    def alerts(self, limit=50):
        return list(reversed(self._alerts))[:limit]

    def log_answer(self, ans):
        self._log.append(ans)

    def answer_log(self, limit=500):
        return self._log[-limit:]


class PgStore(Store):
    """PostgreSQL + pgvector. Tables are created on first use."""

    def __init__(self, url: str, dim: int = 384) -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        self.conn = psycopg.connect(url, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.dim = dim
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(f"""
        CREATE TABLE IF NOT EXISTS documents (doc_id TEXT PRIMARY KEY, data JSONB NOT NULL);
        CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, page INT, text TEXT, PRIMARY KEY (doc_id, page));
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT, company TEXT, page INT, kind TEXT,
            text TEXT, embedding vector({self.dim}));
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
        CREATE INDEX IF NOT EXISTS chunks_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
        CREATE TABLE IF NOT EXISTS financials (doc_id TEXT PRIMARY KEY, data JSONB);
        CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, chat_id TEXT, email TEXT);
        CREATE TABLE IF NOT EXISTS alerts (id SERIAL PRIMARY KEY, data JSONB, created_at TIMESTAMPTZ DEFAULT now());
        CREATE TABLE IF NOT EXISTS answer_log (id SERIAL PRIMARY KEY, data JSONB, created_at TIMESTAMPTZ DEFAULT now());
        """)

    @staticmethod
    def _chunk(row) -> Chunk:
        return Chunk(chunk_id=row[0], doc_id=row[1], company=row[2], page=row[3], kind=row[4], text=row[5])

    def add_document(self, doc, chunks, pages):
        with self.conn.transaction():
            self.conn.execute("INSERT INTO documents VALUES (%s,%s) ON CONFLICT (doc_id) DO UPDATE SET data=EXCLUDED.data",
                              (doc.doc_id, doc.model_dump_json()))
            self.conn.execute("DELETE FROM chunks WHERE doc_id=%s", (doc.doc_id,))
            self.conn.execute("DELETE FROM pages WHERE doc_id=%s", (doc.doc_id,))
            with self.conn.cursor() as cur:
                cur.executemany("INSERT INTO pages VALUES (%s,%s,%s)",
                                [(doc.doc_id, p, t) for p, t in pages.items()])
                cur.executemany("INSERT INTO chunks (chunk_id,doc_id,company,page,kind,text) VALUES (%s,%s,%s,%s,%s,%s)",
                                [(c.chunk_id, c.doc_id, c.company, c.page, c.kind, c.text) for c in chunks])

    def get_document(self, doc_id):
        r = self.conn.execute("SELECT data FROM documents WHERE doc_id=%s", (doc_id,)).fetchone()
        return Document.model_validate(r[0]) if r else None

    def list_documents(self, symbol=None):
        rows = self.conn.execute("SELECT data FROM documents").fetchall()
        docs = [Document.model_validate(r[0]) for r in rows]
        return [d for d in docs if not symbol or d.symbol.upper() == symbol.upper()]

    def get_page(self, doc_id, page):
        r = self.conn.execute("SELECT text FROM pages WHERE doc_id=%s AND page=%s", (doc_id, page)).fetchone()
        return r[0] if r else None

    def chunks(self, doc_ids=None):
        q = "SELECT chunk_id,doc_id,company,page,kind,text FROM chunks"
        if doc_ids is None:
            rows = self.conn.execute(q).fetchall()
        else:
            rows = self.conn.execute(q + " WHERE doc_id = ANY(%s)", (list(doc_ids),)).fetchall()
        return [self._chunk(r) for r in rows]

    def set_embeddings(self, chunk_ids, vectors):
        with self.conn.cursor() as cur:
            cur.executemany("UPDATE chunks SET embedding=%s WHERE chunk_id=%s",
                            [(np.asarray(v, dtype=np.float32), cid) for cid, v in zip(chunk_ids, vectors)])

    def missing_embeddings(self):
        rows = self.conn.execute("SELECT chunk_id,doc_id,company,page,kind,text FROM chunks WHERE embedding IS NULL").fetchall()
        return [self._chunk(r) for r in rows]

    def dense_search(self, qvec, k, doc_ids=None):
        q = ("SELECT chunk_id,doc_id,company,page,kind,text, 1 - (embedding <=> %s) AS sim FROM chunks "
             "WHERE embedding IS NOT NULL {flt} ORDER BY embedding <=> %s LIMIT %s")
        v = np.asarray(qvec, dtype=np.float32)
        if doc_ids is None:
            rows = self.conn.execute(q.format(flt=""), (v, v, k)).fetchall()
        else:
            rows = self.conn.execute(q.format(flt="AND doc_id = ANY(%s)"), (v, list(doc_ids), v, k)).fetchall()
        return [(self._chunk(r), float(r[6])) for r in rows]

    def save_financials(self, doc_id, fh):
        self.conn.execute("INSERT INTO financials VALUES (%s,%s) ON CONFLICT (doc_id) DO UPDATE SET data=EXCLUDED.data",
                          (doc_id, fh.model_dump_json()))

    def get_financials(self, doc_id):
        r = self.conn.execute("SELECT data FROM financials WHERE doc_id=%s", (doc_id,)).fetchone()
        return FinancialHighlights.model_validate(r[0]) if r else None

    def watch(self, symbol, chat_id="", email=""):
        self.conn.execute("INSERT INTO watchlist VALUES (%s,%s,%s) ON CONFLICT (symbol) DO UPDATE "
                          "SET chat_id=EXCLUDED.chat_id, email=EXCLUDED.email", (symbol.upper(), chat_id, email))

    def watchlist(self):
        rows = self.conn.execute("SELECT symbol, chat_id, email FROM watchlist").fetchall()
        return [{"symbol": r[0], "chat_id": r[1], "email": r[2]} for r in rows]

    def add_alert(self, alert):
        self.conn.execute("INSERT INTO alerts (data) VALUES (%s)", (alert.model_dump_json(),))

    def alerts(self, limit=50):
        rows = self.conn.execute("SELECT data FROM alerts ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
        return [Alert.model_validate(r[0]) for r in rows]

    def log_answer(self, ans):
        self.conn.execute("INSERT INTO answer_log (data) VALUES (%s)", (ans.model_dump_json(),))

    def answer_log(self, limit=500):
        rows = self.conn.execute("SELECT data FROM answer_log ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
        return [Answer.model_validate(r[0]) for r in rows]


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        from .config import get_settings
        url = get_settings().database_url
        _store = MemoryStore() if url == "memory" else PgStore(url)
    return _store


def set_store(store: Store) -> None:
    global _store
    _store = store
