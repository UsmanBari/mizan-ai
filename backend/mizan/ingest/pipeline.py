"""Ingestion pipeline: PDF -> pages -> chunks -> store (-> embeddings -> extraction)."""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings
from ..models import Document
from ..store import Store
from .parser import chunk_pages, ocr_available, parse_pdf

log = logging.getLogger(__name__)


def ingest_pdf(store: Store, path: str | Path, doc_id: str, company: str, symbol: str = "",
               doc_type: str = "annual", period: str = "", source_url: str = "",
               find_tables: bool = False, ocr: bool | None = None) -> Document:
    s = get_settings()
    pages = parse_pdf(path, find_tables=find_tables, ocr=ocr)
    chunks = chunk_pages(pages, doc_id, company, s.chunk_chars, s.chunk_overlap, with_tables=find_tables)
    page_text = {p.page: p.text + ("\n\n" + "\n\n".join(p.tables) if p.tables else "") for p in pages}
    doc = Document(doc_id=doc_id, company=company, symbol=symbol, doc_type=doc_type, period=period,
                   source_url=source_url, path=str(path), n_pages=len(pages))
    store.add_document(doc, chunks, page_text)
    n_scanned = sum(p.scanned for p in pages)
    log.info("ingested %s: %d pages (%d scanned), %d chunks", doc_id, len(pages), n_scanned, len(chunks))
    if n_scanned and not (ocr if ocr is not None else ocr_available()):
        log.warning("%s has %d scanned pages but Tesseract is not installed, so they have no text "
                    "(install it: sudo apt install tesseract-ocr)", doc_id, n_scanned)
    return doc


def ingest_psx_symbol(store: Store, symbol: str, company: str = "", limit: int = 4) -> list[Document]:
    """Download the latest `limit` financial reports of a PSX company and ingest them."""
    from . import psx
    s = get_settings()
    docs = []
    for link in psx.fetch_company_reports(symbol)[:limit]:
        doc_id = psx.doc_id_for(link)
        if store.get_document(doc_id):
            continue
        path = psx.download(link, Path(s.data_dir) / "pdfs" / symbol.upper())
        docs.append(ingest_pdf(store, path, doc_id, company or symbol.upper(), symbol.upper(),
                               link.doc_type, link.period, link.url))
    return docs
