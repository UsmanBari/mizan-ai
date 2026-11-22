"""Builds the shared components once (store, retriever, LLM, engine, extractor)."""
from __future__ import annotations

from functools import lru_cache

from .config import get_settings
from .store import get_store


@lru_cache
def get_llm():
    from .llm import LLM
    s = get_settings()
    return LLM() if s.llm_api_key or "localhost" in s.llm_base_url else None


_retriever = None


def get_retriever(kind: str | None = None):
    """BM25 works with zero setup; hybrid+rerank needs sentence-transformers."""
    global _retriever
    from .retrieval.retrievers import build_retriever
    s = get_settings()
    if _retriever is None or kind:
        try:
            _retriever = build_retriever(get_store(), kind or ("hybridx+rerank" if s.use_reranker else "hybridx"))
        except ImportError:  # sentence-transformers not installed -> lexical only
            _retriever = build_retriever(get_store(), "bm25x")
    return _retriever


def reset_retriever():
    global _retriever
    _retriever = None


def get_engine():
    from .agent.engine import QAEngine
    llm = get_llm()
    if llm is None:
        raise RuntimeError("No LLM configured: set MIZAN_LLM_API_KEY (or point MIZAN_LLM_BASE_URL to Ollama)")
    return QAEngine(get_store(), get_retriever(), llm)


def get_extractor():
    from .extraction.extractor import LLMExtractor, RuleExtractor
    llm = get_llm()
    return LLMExtractor(llm) if llm else RuleExtractor()
