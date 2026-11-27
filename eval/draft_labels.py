"""Draft gold labels for NEW reports with the LLM extractor, for a human to check.

For every report in data/psx_reports.csv that has no rows in data/psx_labels.csv
yet, this reads the PDF, runs the LLM extractor (one API call per report), and
appends 6 rows (revenue, PBT, net profit, EPS, total assets, total equity) with
labeller = "claude-draft". The prior-year value is read in code from the
previous-period column of the same row (mizan.extraction.columns).

Drafts are NOT gold. Check every row against the PDF with verify_labels.py and
only then change labeller to your name.

  python eval/draft_labels.py --burhan ATRL_FY2026 KOHC_FY2026 --usman APL_FY2026 BERG_FY2026
  python eval/draft_labels.py --only ATRL_FY2026        # just one report
  python eval/draft_labels.py --dry-run                 # print, write nothing
"""
from __future__ import annotations

import argparse
import csv

from common import DATA

from mizan.extraction.columns import correct_to_current, prior_for_value, read_page_rows
from mizan.extraction.extractor import LLMExtractor
from mizan.ingest.metadata import period_from_statements, period_from_title
from mizan.ingest.parser import parse_pdf
from mizan.llm import LLM

FIELDS6 = ["revenue", "profit_before_tax", "net_profit", "eps_basic", "total_assets", "total_equity"]
COLS = ["doc_id", "symbol", "company", "period_end", "unit", "consolidated", "field", "value_current",
        "value_prior", "page", "labeller", "notes"]


def fmt(v):
    if v is None:
        return ""
    return f"{v:.2f}" if abs(v) < 1000 and not float(v).is_integer() else f"{v:.0f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", help="doc_ids to draft (default: every report without labels)")
    ap.add_argument("--burhan", nargs="*", default=[], help="doc_ids Burhan will verify")
    ap.add_argument("--usman", nargs="*", default=[], help="doc_ids Usman will verify")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    labels_path = DATA / "psx_labels.csv"
    done = {r["doc_id"] for r in csv.DictReader(open(labels_path))}
    reports = list(csv.DictReader(open(DATA / "psx_reports.csv")))
    ex = LLMExtractor(LLM(), fallback=False)
    new_rows = []
    for rep in reports:
        doc_id = f"{rep['symbol']}_{rep['period']}"
        if (a.only and doc_id not in a.only) or (not a.only and doc_id in done):
            continue
        path = DATA / "psx_pdfs" / f"{doc_id}.pdf"
        if not path.exists():
            print(f"{doc_id}: PDF missing - run fetch_psx_reports.py first"); continue
        print(f"{doc_id}: reading ...", flush=True)
        pages = {p.page: p.text for p in parse_pdf(path, ocr=False)}
        res = ex.extract(pages, rep["company"])
        fh = res.highlights
        if fh is None:
            print(f"  LLM gave no valid output ({res.error}) - label this report by hand"); continue
        # period end: statement headers first (checked in code), else what the LLM read
        stmt = period_from_statements(pages, res.pages_used)
        title = period_from_title(f"{rep['doc_type']} {rep['period']}")
        period_end = stmt.period_end or fh.period_end
        who = "burhan" if doc_id in a.burhan else "usman" if doc_id in a.usman else ""
        rows_cache = {}
        for f in FIELDS6:
            fv = getattr(fh, f)
            prior, note, value = None, "", fv.value
            if fv.value is not None and fv.page:
                if fv.page not in rows_cache:
                    rows_cache[fv.page] = read_page_rows(path, fv.page)
                # code decides: the value comes from the CURRENT-year column of the row the LLM pointed at
                value, what = correct_to_current(rows_cache[fv.page], fv.value)
                if what == "was_prior_column":
                    note = f"LLM read the prior-year column ({fmt(fv.value)}); code took the current year"
                prior = prior_for_value(rows_cache[fv.page], value)
                if prior is None:
                    note = (note + "; " if note else "") + "prior not found in code - fill by hand"
            else:
                note = "LLM found nothing - fill by hand"
            label = (fv.label or "").replace(",", " ")
            notes = " | ".join(x for x in [label, note, f"type: {rep['doc_type']}",
                                           f"verify: {who}" if who else ""] if x)
            new_rows.append({"doc_id": doc_id, "symbol": rep["symbol"], "company": rep["company"],
                             "period_end": period_end, "unit": fh.unit,
                             "consolidated": str(bool(fh.consolidated)).lower(), "field": f,
                             "value_current": fmt(value), "value_prior": fmt(prior),
                             "page": fv.page or "", "labeller": "claude-draft", "notes": notes})
        if stmt.period_type and title.period_type and stmt.period_type != title.period_type:
            print(f"  WARNING: csv says {title.period_type} but the statements say {stmt.period_type}")
        print(f"  drafted 6 rows (period end {period_end}, {fh.unit}, consolidated={fh.consolidated})")
    for r in new_rows:
        print(",".join(str(r[c]) for c in COLS))
    if new_rows and not a.dry_run:
        with open(labels_path, "a", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=COLS)
            for r in new_rows:
                w.writerow(r)
        print(f"\nappended {len(new_rows)} draft rows to {labels_path.name}. Now check each one with "
              f"verify_labels.py and set labeller to your name.")


if __name__ == "__main__":
    main()
