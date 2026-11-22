"""Build the PSX test sets from your hand labels.

Step 1  python eval/fetch_psx_reports.py      # downloads PDFs listed in data/psx_reports.csv
Step 2  open each PDF and fill data/psx_labels.csv (one row per report x field):
          fields: revenue, profit_before_tax, net_profit, eps_basic, total_assets, total_equity
          value_current / value_prior : exactly as printed (brackets -> negative)
          page                         : 1-based PDF page where you read it
        Two people: each labels half, then cross-check 10% of the other's rows.
Step 3  python eval/build_psx_testset.py

Outputs (all derived deterministically from the labels):
  data/psx_extraction_gold.json  - extraction test set  (one example = report x field)
  data/psx_qa.jsonl              - QA test set: look-up questions + growth questions
                                   (growth gold answers are computed in code)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict

from common import DATA

LABELS = {"revenue": "revenue", "profit_before_tax": "profit before tax",
          "net_profit": "profit after tax", "eps_basic": "basic earnings per share",
          "total_assets": "total assets", "total_equity": "total equity"}
UNIT_TXT = {"thousands": "Rs '000", "millions": "Rs million", "units": "Rupees", "billions": "Rs billion"}


def main() -> None:
    rows = [r for r in csv.DictReader(open(DATA / "psx_labels.csv")) if not r["doc_id"].startswith("EXAMPLE")]
    if not rows:
        raise SystemExit("data/psx_labels.csv has no labels yet - see the instructions at the top of this file")
    gold = defaultdict(dict)
    qa = []
    for r in rows:
        cur = float(r["value_current"].replace(",", ""))
        prior = float(r["value_prior"].replace(",", "")) if r.get("value_prior") else None
        page = int(r["page"])
        gold[r["doc_id"]]["_meta"] = {"symbol": r["symbol"], "company": r["company"], "unit": r["unit"],
                                      "period_end": r["period_end"], "consolidated": r["consolidated"]}
        gold[r["doc_id"]][r["field"]] = {"value": cur, "prior": prior, "page": page}
        unit = "Rupees per share" if r["field"] == "eps_basic" else UNIT_TXT.get(r["unit"], r["unit"])
        # say which statements the gold comes from, so a correct consolidated /
        # unconsolidated answer is not marked wrong
        basis = "consolidated" if r["consolidated"].strip().lower() == "true" else "unconsolidated"
        qa.append({"id": f"psx_{r['doc_id']}_{r['field']}_lookup", "type": "lookup", "doc_name": r["doc_id"],
                   "question": f"According to its {basis} financial statements, what was {r['company']}'s "
                               f"{LABELS.get(r['field'], r['field'])} for the period ended {r['period_end']}? "
                               f"Answer in {unit}.",
                   "answer": f"{cur:,.2f}", "gold_pages": [[r["doc_id"], page]], "question_type": "metrics-generated"})
        if prior is not None and prior != 0 and r["field"] in ("revenue", "net_profit", "total_assets"):
            what = LABELS[r["field"]]
            if prior > 0 and cur > 0:
                pct = (cur - prior) / prior * 100   # computed by code, never by a model
                q, gold_ans, kind = (f"By what percentage did {r['company']}'s {basis} {what} change in the period ended "
                                 f"{r['period_end']} compared with the previous period?", f"{pct:.2f}%", "growth")
            else:
                # a loss in either year makes a % change meaningless (PRL FY2025):
                # ask for the change in amount instead
                diff = cur - prior
                q, gold_ans, kind = (f"By how much did {r['company']}'s {basis} {what} change in the period ended "
                                 f"{r['period_end']} compared with the previous period? Answer in {unit}.",
                                 f"{diff:,.2f}", "change")
            qa.append({"id": f"psx_{r['doc_id']}_{r['field']}_{kind}", "type": kind, "doc_name": r["doc_id"],
                       "question": q, "answer": gold_ans, "gold_pages": [[r["doc_id"], page]],
                       "question_type": "metrics-generated"})
    (DATA / "psx_extraction_gold.json").write_text(json.dumps(gold, indent=1))
    with open(DATA / "psx_qa.jsonl", "w") as f:
        for q in qa:
            f.write(json.dumps(q) + "\n")
    n_ex = sum(len([k for k in v if k != "_meta"]) for v in gold.values())
    print(f"{len(gold)} reports -> {n_ex} extraction examples, {len(qa)} QA questions "
          f"({sum(q['type'] == 'growth' for q in qa)} growth %, {sum(q['type'] == 'change' for q in qa)} change in amount)")
    if n_ex < 50 or len(qa) < 50:
        print("WARNING: the assignment needs >= 50 labelled examples per component; label more fields/reports")


if __name__ == "__main__":
    main()
