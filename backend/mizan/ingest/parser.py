"""PDF parsing and table-aware chunking (deterministic, no AI).

* Text is rebuilt from word coordinates (layout_text): words on the same visual
  line are joined, and big horizontal gaps become " | ". This keeps every table
  row ("Net profit | 5,363 | 4,869") on one line - this is what makes numeric
  questions retrievable - and is ~100x faster than a table detector.
* Optionally, PyMuPDF's table finder adds markdown tables as extra chunks
  (slow; used as an ablation).
* Scanned pages (no text layer) are flagged; OCR (Tesseract via PyMuPDF) is used
  only if it is installed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..models import Chunk

log = logging.getLogger(__name__)


@dataclass
class ParsedPage:
    page: int                     # 1-based
    text: str
    tables: list[str] = field(default_factory=list)   # markdown tables
    scanned: bool = False


def _table_to_markdown(rows: list[list]) -> str:
    clean = [[re.sub(r"\s+", " ", str(c or "")).strip() for c in r] for r in rows]
    clean = [r for r in clean if any(r)]
    if len(clean) < 2:
        return ""
    width = max(len(r) for r in clean)
    clean = [r + [""] * (width - len(r)) for r in clean]
    lines = ["| " + " | ".join(clean[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in clean[1:]]
    return "\n".join(lines)


def layout_text(pg, ytol: float = 3.0, gap: float = 12.0) -> str:
    """Rebuild page text row by row from word boxes."""
    words = pg.get_text("words")  # (x0, y0, x1, y1, word, block, line, wordno)
    rows: list[list] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        ym = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - ym) <= ytol:
            rows[-1][1].append(w)
        else:
            rows.append([ym, [w]])
    out = []
    for _, ws in rows:
        ws.sort(key=lambda w: w[0])
        line = ws[0][4]
        for a, b in zip(ws, ws[1:]):
            line += (" | " if b[0] - a[2] > gap else " ") + b[4]
        out.append(line)
    return "\n".join(out)


def ocr_available() -> bool:
    """True if the Tesseract program is installed (PyMuPDF calls it for OCR)."""
    import shutil
    return shutil.which("tesseract") is not None


def parse_pdf(path: str | Path, find_tables: bool = False, ocr: bool | None = None) -> list[ParsedPage]:
    # ocr=None means "automatic": OCR scanned pages whenever Tesseract is installed
    if ocr is None:
        ocr = ocr_available()
    pages: list[ParsedPage] = []
    with pymupdf.open(str(path)) as doc:
        for i, pg in enumerate(doc, start=1):
            text = layout_text(pg)
            scanned = len(text.strip()) < 30 and len(pg.get_images()) > 0
            if scanned and ocr:
                try:
                    tp = pg.get_textpage_ocr(full=True, dpi=200)
                    text = pg.get_text("text", textpage=tp)
                except Exception as e:  # tesseract not installed
                    log.warning("OCR failed on %s p%d: %s", path, i, e)
            tables: list[str] = []
            if find_tables and not scanned:
                try:
                    for t in pg.find_tables().tables:
                        md = _table_to_markdown(t.extract())
                        if md:
                            tables.append(md)
                except Exception as e:
                    log.debug("table finder failed on p%d: %s", i, e)
            pages.append(ParsedPage(page=i, text=text, tables=tables, scanned=scanned))
    return pages


def _normalise(text: str) -> str:
    # PDFs often put every table cell on its own line; join short numeric lines so
    # "Net profit\n5,363\n4,869" becomes "Net profit 5,363 4,869".
    text = text.replace(" ", " ")
    lines = [l.strip() for l in text.splitlines()]
    out: list[str] = []
    for l in lines:
        if not l:
            continue
        if out and (re.fullmatch(r"[\(\)\-–$%.,|\d\s]+", l) or len(out[-1]) < 3):
            out[-1] = f"{out[-1]} {l}"
        else:
            out.append(l)
    return "\n".join(out)


def _split(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        # try to cut at a line break
        cut = text.rfind("\n", start + size // 2, end)
        if cut == -1 or end == len(text):
            cut = end
        parts.append(text[start:cut])
        if cut >= len(text):
            break
        start = max(cut - overlap, start + 1)
    return parts


def chunk_pages(pages: list[ParsedPage], doc_id: str, company: str, size: int = 1500,
                overlap: int = 200, with_tables: bool = True) -> list[Chunk]:
    """Each chunk is prefixed with a small header (company, page) so both BM25 and
    embeddings can use it. Tables become their own chunks (table-aware)."""
    chunks: list[Chunk] = []
    for p in pages:
        header = f"[{company} | {doc_id} | page {p.page}]\n"
        body = _normalise(p.text)
        for i, part in enumerate(_split(body, size, overlap)):
            if part.strip():
                chunks.append(Chunk(chunk_id=f"{doc_id}:p{p.page}:c{i}", doc_id=doc_id,
                                    company=company, page=p.page, kind="text",
                                    text=header + part))
        if with_tables:
            for j, md in enumerate(p.tables):
                for k, part in enumerate(_split(md, size * 2, 0)):
                    chunks.append(Chunk(chunk_id=f"{doc_id}:p{p.page}:t{j}.{k}", doc_id=doc_id,
                                        company=company, page=p.page, kind="table",
                                        text=header + part))
    return chunks
