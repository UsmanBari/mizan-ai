"""Turn results/extraction_errors.json into a markdown failure log, grouped by cause.

  python eval/failure_report.py                     # prints markdown
  python eval/failure_report.py >> eval/results/failures/extraction_failures.md

Every line comes from the last run_extraction.py run. Read the PDF page for each
failure before writing the explanation under its group.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from common import DATA, RESULTS

WHAT = {
    "took_prior_period_column": "Prior-year column taken instead of the current year",
    "unit_scale": "Unit off by 1000x (Rs '000 vs Rs million)",
    "page_not_located": "Wrong statement page found",
    "missing_field_page_not_located": "Field missing - the right page was not found",
    "missing_field": "Field missing on the right page (label not matched / unlabelled total)",
    "wrong_line_item_or_consolidation": "Wrong line item, or consolidated vs unconsolidated mixed",
    "invalid_or_no_output": "No valid output (JSON / API failure)",
}


def main() -> None:
    errs = json.load(open(RESULTS / "extraction_errors.json"))
    summary = json.load(open(RESULTS / "summary.json")).get("extraction", {})
    gold = json.load(open(DATA / "psx_extraction_gold.json"))
    print(f"\n# Extraction experiment, all verified reports (run on {date.today().isoformat()})\n")
    print(f"{len(gold)} reports, {sum(len(v) - 1 for v in gold.values())} verified examples.\n")
    print("| Extractor | Field accuracy | Dev (9 old reports) | Held-out (new reports) | Prior-year column taken |"
          " Unit acc. | Page located |")
    print("|---|---|---|---|---|---|---|")
    for name, m in summary.items():
        print(f"| {name} | {m['field_accuracy']:.3f} | {m.get('field_accuracy_dev', '')} | "
              f"{m.get('field_accuracy_heldout', '')} (n={m.get('n_examples_heldout', '')}) | "
              f"{m.get('prior_column_rate', '')} | {m['unit_accuracy']:.3f} | {m['statement_page_located']:.3f} |")
    by = defaultdict(list)
    for e in errs:
        by[(e["extractor"], e["cause"])].append(e)
    print(f"\n{len(errs)} failures in total.\n")
    for (ex, cause), items in sorted(by.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        print(f"\n## {ex}: {WHAT.get(cause, cause)} ({len(items)})\n")
        print("| Report | Field | Gold | Predicted | Gold page | Pages used |")
        print("|---|---|---|---|---|---|")
        for e in items:
            pred = "none" if e["pred"] is None else f"{e['pred']:,.2f}"
            print(f"| {e['doc_id']} | {e['field']} | {e['gold']:,.2f} | {pred} | {e['gold_page']} | "
                  f"{', '.join(map(str, e['pages_used']))} |")
        print("\nWhy: _(open the gold page and write one line)_\n")


if __name__ == "__main__":
    main()
