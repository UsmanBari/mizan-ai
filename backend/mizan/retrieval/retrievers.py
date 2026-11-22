"""Retrieval: BM25, dense, hybrid (RRF) and cross-encoder reranking.

These are the alternatives compared in the retrieval experiment:
    bm25 | dense | hybrid | hybrid+rerank
All share one interface: retrieve(query, k, doc_ids) -> list[Hit].
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from ..models import Chunk, Hit
from ..store import Store

_STOP = set("""a an and are as at be by for from has have in is it its of on or that the
to was were will with what which how much many did does do give using based
shown company""".split())


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; keeps numbers and years ("2018", "1,577" -> "1577")."""
    text = text.lower().replace(",", "")
    toks = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text)
    return [t for t in toks if t not in _STOP]


class Retriever(Protocol):
    name: str
    def retrieve(self, query: str, k: int = 6, doc_ids: Iterable[str] | None = None) -> list[Hit]: ...


class BM25Retriever:
    name = "bm25"

    def __init__(self, store: Store) -> None:
        self.store = store
        self._cache: dict[tuple, tuple[BM25Okapi, list[Chunk]]] = {}

    def _index(self, doc_ids):
        key = tuple(sorted(doc_ids)) if doc_ids is not None else ("*", len(self.store.chunks()))
        if key not in self._cache:
            chunks = self.store.chunks(doc_ids)
            if not chunks:
                return None, []
            self._cache[key] = (BM25Okapi([tokenize(c.text) for c in chunks]), chunks)
        return self._cache[key]

    def invalidate(self) -> None:
        self._cache.clear()

    def retrieve(self, query, k=6, doc_ids=None):
        bm25, chunks = self._index(doc_ids)
        if bm25 is None:
            return []
        scores = bm25.get_scores(tokenize(query))
        top = np.argsort(-scores)[:k]
        return [Hit(chunk=chunks[i], score=float(scores[i]), source=self.name) for i in top]


class Embedder:
    """sentence-transformers wrapper; vectors are L2-normalised so dot = cosine."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        # BGE models expect this instruction on the query side only
        self.query_prefix = "Represent this sentence for searching relevant passages: " \
            if "bge" in model_name.lower() and "m3" not in model_name.lower() else ""

    @property
    def dim(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def embed_docs(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                 show_progress_bar=len(texts) > 500)

    def embed_query(self, text: str) -> np.ndarray:
        return self.model.encode([self.query_prefix + text], normalize_embeddings=True)[0]


@lru_cache(maxsize=2)
def get_embedder(model_name: str) -> Embedder:
    return Embedder(model_name)


def index_missing(store: Store, embedder: Embedder, batch: int = 256) -> int:
    """Embed every chunk that has no vector yet. Returns number embedded."""
    todo = store.missing_embeddings()
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        store.set_embeddings([c.chunk_id for c in part], embedder.embed_docs([c.text for c in part]))
    return len(todo)


class DenseRetriever:
    name = "dense"

    def __init__(self, store: Store, embedder: Embedder) -> None:
        self.store, self.embedder = store, embedder

    def retrieve(self, query, k=6, doc_ids=None):
        q = self.embedder.embed_query(query)
        return [Hit(chunk=c, score=s, source=self.name)
                for c, s in self.store.dense_search(q, k, doc_ids)]


def rrf_fuse(result_lists: list[list[Hit]], k: int, c: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion: score = sum 1/(c + rank). Robust to the very
    different score scales of BM25 and cosine similarity."""
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for hits in result_lists:
        for rank, h in enumerate(hits, start=1):
            cid = h.chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (c + rank)
            best.setdefault(cid, h)
    order = sorted(scores, key=scores.get, reverse=True)[:k]
    return [Hit(chunk=best[cid].chunk, score=scores[cid], source="hybrid") for cid in order]


class HybridRetriever:
    name = "hybrid"

    def __init__(self, sparse: BM25Retriever, dense: DenseRetriever, pool: int = 30) -> None:
        self.sparse, self.dense, self.pool = sparse, dense, pool

    def retrieve(self, query, k=6, doc_ids=None):
        return rrf_fuse([self.sparse.retrieve(query, self.pool, doc_ids),
                         self.dense.retrieve(query, self.pool, doc_ids)], k)


class RerankRetriever:
    """Takes a wide candidate pool from a base retriever and re-orders it with a
    cross-encoder that reads (query, passage) together."""

    def __init__(self, base: Retriever, model_name: str, pool: int = 30) -> None:
        from sentence_transformers import CrossEncoder
        self.base, self.pool = base, pool
        self.model = CrossEncoder(model_name, max_length=512)
        self.name = f"{base.name}+rerank"

    def retrieve(self, query, k=6, doc_ids=None):
        cands = self.base.retrieve(query, self.pool, doc_ids)
        if not cands:
            return []
        scores = self.model.predict([(query, h.chunk.text) for h in cands])
        order = np.argsort(-np.asarray(scores))[:k]
        return [Hit(chunk=cands[i].chunk, score=float(scores[i]), source=self.name) for i in order]


def build_retriever(store: Store, kind: str = "hybridx+rerank", embed_model: str | None = None,
                    rerank_model: str | None = None) -> Retriever:
    """Factory used by the API, the agent and the evaluation scripts.

    kind = <base>[x][+rerank]
      base    : bm25 | dense | hybrid
      x       : glossary query expansion + company/year metadata routing
      +rerank : cross-encoder reranking of the top-30 candidates
    e.g. "bm25", "bm25x", "hybrid", "hybridx+rerank" (the product default)."""
    from ..config import get_settings
    from .query import ExpandedRetriever
    s = get_settings()
    rerank = kind.endswith("+rerank")
    core = kind.removesuffix("+rerank")
    expand = core.endswith("x")
    base = core.removesuffix("x")
    if base not in ("bm25", "dense", "hybrid"):
        raise ValueError(f"unknown retriever kind: {kind}")
    r: Retriever = BM25Retriever(store)
    if base in ("dense", "hybrid"):
        emb = get_embedder(embed_model or s.embed_model)
        index_missing(store, emb)
        dense = DenseRetriever(store, emb)
        r = dense if base == "dense" else HybridRetriever(r, dense)
    if expand:
        r = ExpandedRetriever(r, store)
    if rerank:
        r = RerankRetriever(r, rerank_model or s.rerank_model)
    r.name = kind
    return r
