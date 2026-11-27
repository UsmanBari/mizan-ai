"""Storage layer.

Two implementations with the same interface:
* MemoryStore  - everything in RAM (unit tests, evaluation runs, quick demo), with
                 optional disk persistence to data/store.pkl.
* PgStore      - PostgreSQL + pgvector (deployed system). Relational tables for
                 documents, financials, facts, watchlist, alerts and query logs; a vector
                 column on chunks for dense search.
"""
from __future__ import annotations

import csv
import logging
import pickle
import re
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .models import Alert, Answer, Chunk, Document, FIELDS, FinancialFact, FinancialHighlights
from .ratios import SCALE

log = logging.getLogger(__name__)

_MONTHS_BY_DOC_TYPE = {
    "annual": 12,
    "nine-months": 9,
    "half-yearly": 6,
    "quarterly": 3,
}


def _prior_year_date(period_end: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", period_end.strip())
    if not m:
        return f"prior_{period_end}"
    y, mo, d = int(m.group(1)) - 1, int(m.group(2)), int(m.group(3))
    if mo == 2 and d == 29:
        d = 28
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _scaled(value: float, unit: str, field: str) -> float:
    if field == "eps_basic":
        return float(value)
    return float(value) * SCALE.get((unit or "").lower(), 1.0)


def _facts_differ(a: FinancialFact, b: FinancialFact) -> bool:
    va = _scaled(a.value, a.unit, a.field)
    vb = _scaled(b.value, b.unit, b.field)
    denom = max(abs(va), abs(vb), 1e-9)
    if va == 0 and vb == 0:
        return False
    return abs(va - vb) > 0.005 * denom


def _group_conflicts(facts: list[FinancialFact]) -> list[dict]:
    buckets: dict[tuple, list[FinancialFact]] = {}
    for f in facts:
        key = (f.symbol.upper(), f.field, f.period_end, f.basis)
        buckets.setdefault(key, []).append(f)
    out = []
    for (sym, field, period_end, basis), grp in buckets.items():
        if len(grp) < 2:
            continue
        base = grp[0]
        if any(_facts_differ(base, other) for other in grp[1:]):
            out.append({
                "company": base.company,
                "symbol": sym,
                "field": field,
                "period_end": period_end,
                "basis": basis,
                "values": [
                    {
                        "value": g.value,
                        "unit": g.unit,
                        "doc_id": g.doc_id,
                        "page": g.page,
                        "source": g.source,
                    }
                    for g in grp
                ],
            })
    return out


def _facts_from_highlights(doc_id: str, fh: FinancialHighlights, doc: Optional[Document]) -> list[FinancialFact]:
    symbol = (doc.symbol if doc and doc.symbol else doc_id.split("_")[0]).upper()
    company = fh.company or (doc.company if doc else symbol)
    doc_type = doc.doc_type if doc else "annual"
    months = _MONTHS_BY_DOC_TYPE.get(doc_type, 12)
    period_end = fh.period_end or (doc.period if doc else "")
    if not period_end:
        return []
    basis = "consolidated" if fh.consolidated else "unconsolidated"
    out = []
    for f in FIELDS:
        fv = getattr(fh, f)
        if fv.value is None:
            continue
        out.append(FinancialFact(
            company=company,
            symbol=symbol,
            field=f,
            period_end=period_end,
            period_type=doc_type,
            months=months,
            basis=basis,
            value=float(fv.value),
            unit="Rupees per share" if f == "eps_basic" else fh.unit,
            doc_id=doc_id,
            page=fv.page,
            source="extraction",
        ))
    return out


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
    # chunks + vectors --------------------------------------------------------
    @abstractmethod
    def chunks(self, doc_ids: Iterable[str] | None = None) -> list[Chunk]: ...
    @abstractmethod
    def set_embeddings(self, chunk_ids: list[str], vectors: np.ndarray) -> None: ...
    @abstractmethod
    def missing_embeddings(self) -> list[Chunk]: ...
    @abstractmethod
    def dense_search(self, qvec: np.ndarray, k: int, doc_ids: Iterable[str] | None = None) -> list[tuple[Chunk, float]]: ...
    # structured data ---------------------------------------------------------
    @abstractmethod
    def save_financials(self, doc_id: str, fh: FinancialHighlights) -> None: ...
    @abstractmethod
    def get_financials(self, doc_id: str) -> Optional[FinancialHighlights]: ...
    # verified financial facts ------------------------------------------------
    @abstractmethod
    def add_facts(self, facts: list[FinancialFact]) -> list[dict]: ...
    @abstractmethod
    def get_facts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
        period_type: str | None = None,
        doc_id: str | None = None,
    ) -> list[FinancialFact]: ...
    @abstractmethod
    def fact_conflicts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
    ) -> list[dict]: ...
    # watchlist / alerts / logs -----------------------------------------------
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
    def __init__(self, persist_path: str | Path | None = None, autoload_labels: bool = False) -> None:
        self._lock = threading.Lock()
        self.docs: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._pages: dict[tuple[str, int], str] = {}
        self._vecs: dict[str, np.ndarray] = {}
        self._fin: dict[str, FinancialHighlights] = {}
        self._facts: list[FinancialFact] = []
        self._watch: dict[str, dict] = {}
        self._alerts: list[Alert] = []
        self._log: list[Answer] = []
        self._persist_path: Optional[Path] = Path(persist_path) if persist_path else None
        if self._persist_path and self._persist_path.exists():
            self._load_disk()
        if autoload_labels:
            load_psx_labels(self)

    def __getstate__(self):          # allow pickling (evaluation cache)
        d = self.__dict__.copy()
        d.pop("_lock", None)
        return d

    def __setstate__(self, d):
        self.__dict__.update(d)
        self._lock = threading.Lock()
        if not hasattr(self, "_facts"):
            self._facts = []
        if not hasattr(self, "_persist_path"):
            self._persist_path = None

    def _save_disk(self) -> None:
        if self._persist_path is None:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._persist_path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(self, f)
        tmp.replace(self._persist_path)

    def _load_disk(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            with open(self._persist_path, "rb") as f:
                loaded = pickle.load(f)
            if isinstance(loaded, MemoryStore):
                self.docs = getattr(loaded, "docs", {})
                self._chunks = getattr(loaded, "_chunks", {})
                self._pages = getattr(loaded, "_pages", {})
                self._vecs = getattr(loaded, "_vecs", {})
                self._fin = getattr(loaded, "_fin", {})
                self._facts = getattr(loaded, "_facts", [])
                self._watch = getattr(loaded, "_watch", {})
                self._alerts = getattr(loaded, "_alerts", [])
                self._log = getattr(loaded, "_log", [])
        except Exception as e:
            log.warning("Failed to load %s: %s", self._persist_path, e)

    def add_document(self, doc, chunks, pages):
        with self._lock:
            self.docs[doc.doc_id] = doc
            for c in chunks:
                self._chunks[c.chunk_id] = c
            for p, t in pages.items():
                self._pages[(doc.doc_id, p)] = t
            self._save_disk()

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
            self._save_disk()

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
        doc = self.get_document(doc_id)
        facts = _facts_from_highlights(doc_id, fh, doc)
        with self._lock:
            self._fin[doc_id] = fh
            self._ingest_facts_unlocked(facts)
            self._save_disk()

    def get_financials(self, doc_id):
        return self._fin.get(doc_id)

    def _ingest_facts_unlocked(self, facts: list[FinancialFact]) -> list[dict]:
        for f in facts:
            f_sym = f.symbol.upper()
            # Match bucket: same symbol/company, field, period_end, basis
            bucket = [
                existing for existing in self._facts
                if existing.symbol.upper() == f_sym
                and existing.field == f.field
                and existing.period_end == f.period_end
                and existing.basis == f.basis
            ]
            # Deduplicate exact same (doc_id, source) entry when value agrees within 0.5%
            same_origin = [
                e for e in bucket
                if e.doc_id == f.doc_id and e.source == f.source and not _facts_differ(e, f)
            ]
            if same_origin:
                continue
            has_conflict = any(_facts_differ(e, f) for e in bucket)
            if has_conflict:
                for e in bucket:
                    e.conflict = True
                f = f.model_copy(update={"conflict": True})
            self._facts.append(f)
        return _group_conflicts(self._facts)

    def add_facts(self, facts: list[FinancialFact]) -> list[dict]:
        with self._lock:
            conflicts = self._ingest_facts_unlocked(facts)
            self._save_disk()
            return conflicts

    def get_facts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
        period_type: str | None = None,
        doc_id: str | None = None,
    ) -> list[FinancialFact]:
        out = self._facts
        if symbol:
            su = symbol.upper()
            out = [f for f in out if f.symbol.upper() == su or f.company.lower() == symbol.lower()]
        if field:
            out = [f for f in out if f.field == field]
        if period_end:
            out = [f for f in out if f.period_end == period_end]
        if basis:
            out = [f for f in out if f.basis == basis]
        if period_type:
            out = [f for f in out if f.period_type == period_type]
        if doc_id:
            out = [f for f in out if f.doc_id == doc_id]
        return list(out)

    def fact_conflicts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
    ) -> list[dict]:
        sub = self.get_facts(symbol=symbol, field=field, period_end=period_end, basis=basis)
        return _group_conflicts(sub)

    def watch(self, symbol, chat_id="", email=""):
        with self._lock:
            self._watch[symbol.upper()] = {"symbol": symbol.upper(), "chat_id": chat_id, "email": email}
            self._save_disk()

    def watchlist(self):
        return list(self._watch.values())

    def add_alert(self, alert):
        with self._lock:
            self._alerts.append(alert)
            self._save_disk()

    def alerts(self, limit=50):
        return list(reversed(self._alerts))[:limit]

    def log_answer(self, ans):
        self._log.append(ans)

    def answer_log(self, limit=500):
        return self._log[-limit:]


class PgStore(Store):
    """PostgreSQL + pgvector. Tables are created on first use."""

    def __init__(self, url: str, dim: int = 384, autoload_labels: bool = True) -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        self.conn = psycopg.connect(url, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.dim = dim
        self._init_schema()
        if autoload_labels:
            load_psx_labels(self)

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
        CREATE TABLE IF NOT EXISTS facts (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            field TEXT NOT NULL,
            period_end TEXT NOT NULL,
            basis TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            source TEXT NOT NULL,
            data JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS facts_lookup ON facts(symbol, field, period_end, basis);
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
        self.add_facts(_facts_from_highlights(doc_id, fh, self.get_document(doc_id)))

    def get_financials(self, doc_id):
        r = self.conn.execute("SELECT data FROM financials WHERE doc_id=%s", (doc_id,)).fetchone()
        return FinancialHighlights.model_validate(r[0]) if r else None

    def add_facts(self, facts: list[FinancialFact]) -> list[dict]:
        for f in facts:
            sym = f.symbol.upper()
            rows = self.conn.execute(
                "SELECT id, data FROM facts WHERE symbol=%s AND field=%s AND period_end=%s AND basis=%s",
                (sym, f.field, f.period_end, f.basis),
            ).fetchall()
            bucket = [(rid, FinancialFact.model_validate(data)) for rid, data in rows]
            if any(e.doc_id == f.doc_id and e.source == f.source and not _facts_differ(e, f) for _, e in bucket):
                continue
            has_conflict = any(_facts_differ(e, f) for _, e in bucket)
            if has_conflict:
                for rid, e in bucket:
                    if not e.conflict:
                        e = e.model_copy(update={"conflict": True})
                        self.conn.execute("UPDATE facts SET data=%s WHERE id=%s", (e.model_dump_json(), rid))
                f = f.model_copy(update={"conflict": True})
            self.conn.execute(
                "INSERT INTO facts (symbol,field,period_end,basis,doc_id,source,data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (sym, f.field, f.period_end, f.basis, f.doc_id, f.source, f.model_dump_json()),
            )
        return self.fact_conflicts()

    def get_facts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
        period_type: str | None = None,
        doc_id: str | None = None,
    ) -> list[FinancialFact]:
        clauses, params = [], []
        if symbol:
            clauses.append("symbol=%s")
            params.append(symbol.upper())
        if field:
            clauses.append("field=%s")
            params.append(field)
        if period_end:
            clauses.append("period_end=%s")
            params.append(period_end)
        if basis:
            clauses.append("basis=%s")
            params.append(basis)
        if doc_id:
            clauses.append("doc_id=%s")
            params.append(doc_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(f"SELECT data FROM facts {where} ORDER BY id", tuple(params)).fetchall()
        out = [FinancialFact.model_validate(r[0]) for r in rows]
        if period_type:
            out = [f for f in out if f.period_type == period_type]
        return out

    def fact_conflicts(
        self,
        symbol: str | None = None,
        field: str | None = None,
        period_end: str | None = None,
        basis: str | None = None,
    ) -> list[dict]:
        return _group_conflicts(self.get_facts(symbol=symbol, field=field, period_end=period_end, basis=basis))

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


def default_psx_labels_path() -> Optional[Path]:
    repo = Path(__file__).resolve().parents[2]
    for cand in (repo / "eval/data/psx_labels.csv", Path("eval/data/psx_labels.csv"), Path("/app/eval/data/psx_labels.csv")):
        if cand.exists():
            return cand
    return None


def load_psx_labels(store: Store, csv_path: str | Path | None = None, verified_only: bool = True) -> int:
    """Load verified PSX gold labels from psx_labels.csv into the store's facts table."""
    path = Path(csv_path) if csv_path else default_psx_labels_path()
    if path is None or not path.exists():
        return 0
    facts: list[FinancialFact] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["doc_id"].startswith("EXAMPLE"):
                continue
            labeller = (r.get("labeller") or "").strip()
            if verified_only and labeller.lower() in ("", "claude-draft"):
                continue
            basis: str = "consolidated" if r["consolidated"].strip().lower() == "true" else "unconsolidated"
            unit = "Rupees per share" if r["field"] == "eps_basic" else r["unit"]
            page = int(r["page"]) if r.get("page") else None
            cur = float(str(r["value_current"]).replace(",", ""))
            facts.append(FinancialFact(
                company=r["company"],
                symbol=r["symbol"].upper(),
                field=r["field"],
                period_end=r["period_end"],
                period_type="annual",
                months=12,
                basis=basis,
                value=cur,
                unit=unit,
                doc_id=r["doc_id"],
                page=page,
                source="label",
                labeller=labeller,
            ))
            if r.get("value_prior"):
                prior = float(str(r["value_prior"]).replace(",", ""))
                facts.append(FinancialFact(
                    company=r["company"],
                    symbol=r["symbol"].upper(),
                    field=r["field"],
                    period_end=_prior_year_date(r["period_end"]),
                    period_type="annual",
                    months=12,
                    basis=basis,
                    value=prior,
                    unit=unit,
                    doc_id=r["doc_id"],
                    page=page,
                    source="label",
                    labeller=labeller,
                ))
    if facts:
        store.add_facts(facts)
    return len(facts)


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        from .config import get_settings
        s = get_settings()
        _store = (
            MemoryStore(persist_path=Path(s.data_dir) / "store.pkl", autoload_labels=True)
            if s.database_url == "memory"
            else PgStore(s.database_url, autoload_labels=True)
        )
    return _store


def set_store(store: Store) -> None:
    global _store
    _store = store
