"""Speed up the HUMAN check of the draft gold labels (it does not replace it).

For every row in data/psx_labels.csv it opens the labelled PDF page and looks for
the current and prior values as printed (1,234,567 or (1,234,567)). It prints the
line where each value was found, so you can confirm the line item, the column
(current vs prior) and consolidated vs unconsolidated at a glance.

  python eval/verify_labels.py                 # all rows
  python eval/verify_labels.py --who usman     # only rows whose notes say "verify: usman"
  python eval/verify_labels.py --symbol HUBC   # one company
  python eval/verify_labels.py --doc ATRL_H1FY2026   # one report
  python eval/verify_labels.py --drafts --who burhan  # only your unchecked rows
  python eval/verify_labels.py --show HUBC 275 # print a whole page (or --show ATRL_9MFY2026 12)

After YOU have checked a row against the PDF, change its labeller from
"claude-draft" to your name. Rows marked NOT FOUND need a closer look.
"""
from __future__ import annotations

import argparse
import csv
import re

from common import DATA

from mizan.ingest.parser import parse_pdf


def variants(v: float, field: str) -> list[str]:
    if field == "eps_basic":
        base = [f"{abs(v):.2f}", f"{abs(v):.1f}", f"{abs(v):g}"]
    else:
        base = [f"{abs(v):,.0f}"]
    return base


def find(text: str, v: float, field: str) -> str | None:
    for s in variants(v, field):
        for line in text.splitlines():
            if re.search(rf"(?<![\d,.]){re.escape(s)}(?![\d,]|\.\d)", line):
                return line.strip()
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", help="usman / burhan: only rows assigned to you")
    ap.add_argument("--symbol")
    ap.add_argument("--doc", help="one report, e.g. ATRL_H1FY2026")
    ap.add_argument("--drafts", action="store_true", help="only rows still marked claude-draft")
    ap.add_argument("--show", nargs=2, metavar=("SYMBOL", "PAGE"))
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(DATA / "psx_labels.csv")) if not r["doc_id"].startswith("EXAMPLE")]
    # one symbol can now have several reports (ATRL annual, half-year, nine months),
    # so pages are looked up by doc_id (= SYMBOL_PERIOD = the PDF file name)
    cache: dict[str, dict[int, str]] = {}

    def pages(doc_id: str) -> dict[int, str]:
        if doc_id not in cache:
            path = DATA / "psx_pdfs" / f"{doc_id}.pdf"
            cache[doc_id] = {p.page: p.text for p in parse_pdf(path, ocr=False)}
        return cache[doc_id]

    if a.show:
        key = a.show[0]
        if "_" not in key:   # a bare symbol: use its first report
            key = next((r["doc_id"] for r in rows if r["symbol"] == key.upper()), key.upper())
        print(pages(key).get(int(a.show[1]), "page not found"))
        return
    bad = 0
    for r in rows:
        if a.who and f"verify: {a.who.lower()}" not in r["notes"].lower():
            continue
        if a.symbol and r["symbol"] != a.symbol.upper():
            continue
        if a.drafts and r["labeller"].strip().lower() != "claude-draft":
            continue
        if a.doc and r["doc_id"] != a.doc:
            continue
        if not r["value_current"].strip() or not r["page"].strip():
            print(f"[EMPTY    ] {r['doc_id']:14s} {r['field']:17s} - no draft value: read it from the PDF")
            bad += 1
            continue
        text = pages(r["doc_id"]).get(int(r["page"]), "")
        cur = float(r["value_current"]); prior = float(r["value_prior"]) if r["value_prior"] else None
        lc = find(text, cur, r["field"])
        lp = find(text, prior, r["field"]) if prior is not None else "-"
        ok = lc is not None and lp is not None
        bad += not ok
        flag = "ok  " if ok else "NOT FOUND"
        print(f"[{flag}] {r['doc_id']:14s} {r['field']:17s} p{r['page']:>4s} ({r['labeller']})")
        print(f"        current {cur:,.2f}: {lc or '-- not on this page --'}")
        if prior is not None:
            print(f"        prior   {prior:,.2f}: {lp or '-- not on this page --'}")
    print(f"\n{bad} row(s) need a closer look. Check every row against the PDF anyway, then set labeller to your name.")


if __name__ == "__main__":
    main()
