"""Ingestion pipeline: PDF -> pages -> metadata + chunks -> store (-> embeddings -> extraction).

Added for the proposal feedback:
  * reporting period (annual / half-yearly / quarterly, period end, months
    covered) from the title, checked against the statement headers;
  * every statement page tagged consolidated / unconsolidated;
  * de-duplication: the same filing (PSX id or identical PDF bytes) is never
    ingested twice.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings
from ..models import Document
from ..store import Store
from .dedupe import Ledger, sha256_file
from .metadata import document_metadata
from .parser import chunk_pages, ocr_available, parse_pdf

log = logging.getLogger(__name__)

_LEDGER: Ledger | None = None


def get_ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger(Path(get_settings().data_dir) / "ingested.json")
    return _LEDGER


def find_duplicate(store: Store, sha: str = "", remote_id: str = "") -> Document | None:
    """An already-ingested document with the same PDF bytes or the same PSX id."""
    for d in store.list_documents():
        if (sha and d.sha256 == sha) or (remote_id and d.remote_id == remote_id):
            return d
    return None


def ingest_pdf(store: Store, path: str | Path, doc_id: str, company: str, symbol: str = "",
               doc_type: str = "annual", period: str = "", source_url: str = "",
               find_tables: bool = False, ocr: bool | None = None, title: str = "",
               remote_id: str = "", ledger: Ledger | None = None) -> Document:
    """Ingest one PDF. If the same file is already in the store, the existing
    document is returned and nothing is added (de-duplication by sha256)."""
    s = get_settings()
    sha = sha256_file(path)
    dup = find_duplicate(store, sha, remote_id)
    if dup is not None:
        log.info("skipping %s: same filing as %s already ingested", doc_id, dup.doc_id)
        return dup
    pages = parse_pdf(path, find_tables=find_tables, ocr=ocr)
    chunks = chunk_pages(pages, doc_id, company, s.chunk_chars, s.chunk_overlap, with_tables=find_tables)
    page_text = {p.page: p.text + ("\n\n" + "\n\n".join(p.tables) if p.tables else "") for p in pages}
    # the title is the PSX announcement title when we have it; else use what the caller said
    md = document_metadata({p.page: p.text for p in pages}, title or f"{doc_type} {period}")
    if md.warnings:
        log.warning("%s: %s", doc_id, "; ".join(md.warnings))
    doc = Document(doc_id=doc_id, company=company, symbol=symbol,
                   doc_type=md.period.period_type or doc_type, period=period,
                   source_url=source_url, path=str(path), n_pages=len(pages),
                   period_type=md.period.period_type or doc_type, period_end=md.period.period_end,
                   months_covered=md.period.months_covered, period_warnings=md.warnings,
                   statement_pages={p: {"statement": t.statement, "basis": t.basis}
                                    for p, t in md.statement_pages.items()},
                   sha256=sha, remote_id=remote_id)
    store.add_document(doc, chunks, page_text)
    if ledger is not None:      # the PSX fetch path keeps a ledger that survives restarts
        ledger.record(doc_id, sha, remote_id)
    n_scanned = sum(p.scanned for p in pages)
    log.info("ingested %s: %d pages (%d scanned), %d chunks, %s ending %s", doc_id, len(pages),
             n_scanned, len(chunks), doc.period_type, doc.period_end)
    if n_scanned and not (ocr if ocr is not None else ocr_available()):
        log.warning("%s has %d scanned pages but Tesseract is not installed, so they have no text "
                    "(install it: sudo apt install tesseract-ocr)", doc_id, n_scanned)
    return doc


def ingest_psx_symbol(store: Store, symbol: str, company: str = "", limit: int = 4,
                      ledger: Ledger | None = None, only_unseen: bool = False) -> list[Document]:
    """Download the latest `limit` financial reports of a PSX company and ingest
    them. A filing already in the store (same PSX id, or same PDF bytes under a
    different id) is skipped. With only_unseen=True (the alert watcher), filings
    the ledger has seen before - e.g. before a restart wiped the in-memory
    store - are re-ingested but not returned, so each filing alerts once."""
    from . import psx
    s = get_settings()
    led = ledger or get_ledger()
    docs = []
    for link in psx.fetch_company_reports(symbol)[:limit]:
        doc_id = psx.doc_id_for(link)
        rid = link.remote_id
        if store.get_document(doc_id) or find_duplicate(store, remote_id=rid):
            continue
        known = led.seen_remote(rid)
        if known and store.get_document(known):
            continue                               # same filing under a second PSX id: no download
        seen_before = led.seen_remote(rid)
        path = psx.download(link, Path(s.data_dir) / "pdfs" / symbol.upper())
        sha = sha256_file(path)
        dup = find_duplicate(store, sha=sha)
        if dup is not None:
            led.record(dup.doc_id, sha, rid)       # same PDF posted under a second id
            continue
        seen_before = seen_before or led.seen_sha(sha)
        doc = ingest_pdf(store, path, doc_id, company or symbol.upper(), symbol.upper(),
                         link.doc_type, link.period, link.url, title=link.title, remote_id=rid, ledger=led)
        if not (only_unseen and seen_before):
            docs.append(doc)
    return docs
