"""Command line helpers.

  python -m mizan.cli psx HBL --limit 2            # download + ingest PSX reports
  python -m mizan.cli pdf report.pdf --company "Habib Bank" --symbol HBL --period FY2025
  python -m mizan.cli ask "What was HBL's profit after tax in 2025?" --mode agent
"""
from __future__ import annotations

import argparse
import json

from .ingest.pipeline import ingest_pdf, ingest_psx_symbol
from .store import get_store


def main() -> None:
    ap = argparse.ArgumentParser(prog="mizan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("psx"); p.add_argument("symbol"); p.add_argument("--limit", type=int, default=2)
    p = sub.add_parser("pdf"); p.add_argument("path"); p.add_argument("--company", required=True)
    p.add_argument("--symbol", default=""); p.add_argument("--period", default="")
    p.add_argument("--doc-type", default="annual")
    p = sub.add_parser("ask"); p.add_argument("question"); p.add_argument("--mode", default="agent")
    a = ap.parse_args()

    store = get_store()
    if a.cmd == "psx":
        for d in ingest_psx_symbol(store, a.symbol, limit=a.limit):
            print("ingested", d.doc_id, d.n_pages, "pages")
    elif a.cmd == "pdf":
        doc_id = f"{(a.symbol or a.company).upper().replace(' ', '')}_{a.period or 'X'}"
        d = ingest_pdf(store, a.path, doc_id, a.company, a.symbol, a.doc_type, a.period)
        print("ingested", d.doc_id, d.n_pages, "pages")
    elif a.cmd == "ask":
        from .services import get_engine
        print(json.dumps(get_engine().answer(a.question, a.mode).model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
