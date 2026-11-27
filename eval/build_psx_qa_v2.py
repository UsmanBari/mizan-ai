"""Build PSX QA v2 benchmark from verified labels + ratios.py.

Usage:
  python eval/build_psx_qa_v2.py

Generates eval/data/psx_qa_v2.jsonl with >= 200 questions across 5 types:
  - lookup        (54): single field, stating reporting basis + period + unit
  - growth        (27): revenue / earnings / EPS growth % via ratios.py (or amount change when base <= 0)
  - ratio         (54): net_margin (2 yrs), ROE, ROA, debt_to_equity (2 yrs, derived liabilities)
  - cross_company (54): pairwise net_margin & ROE comparisons across verified companies
  - unanswerable  (54): missing periods (FY2022/FY2020), quarterly vs annual, unavailable basis/fields
"""
from __future__ import annotations

import csv
import itertools
import json
from collections import Counter, defaultdict

from common import DATA

from mizan.ratios import compute as compute_ratio

FIELD_LABELS = {
    "revenue": "revenue",
    "profit_before_tax": "profit before tax",
    "net_profit": "net profit (profit after tax)",
    "eps_basic": "basic earnings per share (EPS)",
    "total_assets": "total assets",
    "total_equity": "total equity",
}
UNIT_TXT = {"thousands": "Rs '000", "millions": "Rs million", "units": "Rupees", "billions": "Rs billion"}


def _prior_year(period_end: str) -> str:
    y, m, d = period_end.split("-")
    return f"{int(y) - 1:04d}-{m}-{d}"


def _unit_label(field: str, unit: str) -> str:
    return "Rupees per share" if field == "eps_basic" else UNIT_TXT.get(unit, unit)


def load_verified_rows() -> list[dict]:
    rows = []
    with open(DATA / "psx_labels.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["doc_id"].startswith("EXAMPLE"):
                continue
            if (r.get("labeller") or "").strip().lower() in ("", "claude-draft"):
                continue
            rows.append(r)
    return rows


def build_questions() -> list[dict]:
    rows = load_verified_rows()
    if not rows:
        raise SystemExit("No verified rows in eval/data/psx_labels.csv (labeller != claude-draft)")

    by_sym: dict[str, dict] = {}
    vbp_by_sym: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    raw_by_sym: dict[str, dict[str, dict]] = defaultdict(dict)

    for r in rows:
        sym = r["symbol"].upper()
        cur = float(str(r["value_current"]).replace(",", ""))
        pri = float(str(r["value_prior"]).replace(",", "")) if r.get("value_prior") else None
        page = int(r["page"])
        basis = "consolidated" if r["consolidated"].strip().lower() == "true" else "unconsolidated"
        cur_p = r["period_end"]
        pri_p = _prior_year(cur_p)
        unit = "Rupees per share" if r["field"] == "eps_basic" else r["unit"]

        by_sym[sym] = {
            "symbol": sym,
            "company": r["company"],
            "doc_id": r["doc_id"],
            "period_end": cur_p,
            "prior_end": pri_p,
            "unit": r["unit"],
            "basis": basis,
        }
        raw_by_sym[sym][r["field"]] = {
            "cur": cur, "prior": pri, "page": page, "unit_lbl": _unit_label(r["field"], r["unit"]),
            "doc_id": r["doc_id"], "period_end": cur_p, "prior_end": pri_p, "basis": basis,
        }
        vbp_by_sym[sym][cur_p][r["field"]] = {
            "value": cur, "doc_id": r["doc_id"], "page": page, "basis": basis,
            "period_type": "annual", "months": 12, "unit": unit,
        }
        if pri is not None:
            vbp_by_sym[sym][pri_p][r["field"]] = {
                "value": pri, "doc_id": r["doc_id"], "page": page, "basis": basis,
                "period_type": "annual", "months": 12, "unit": unit,
            }

    qs: list[dict] = []
    syms = sorted(by_sym.keys())

    # 1. LOOKUP (>= 50: 9 companies x 6 fields = 54) -----------------------
    for sym in syms:
        meta = by_sym[sym]
        for field, info in raw_by_sym[sym].items():
            lbl = FIELD_LABELS.get(field, field)
            basis = meta["basis"]
            p = meta["period_end"]
            qs.append({
                "id": f"psx2_{meta['doc_id']}_{field}_lookup",
                "type": "lookup",
                "template": "lookup",
                "question_type": "lookup",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "basis": basis,
                "period": p,
                "question": (
                    f"According to its {basis} annual financial statements, what was {meta['company']} "
                    f"({sym})'s {lbl} for FY2026 (year ended {p})? Answer in {info['unit_lbl']}."
                ),
                "answer": f"{info['cur']:,.2f}",
                "gold_operands": [{
                    "field": field, "period": p, "value": info["cur"],
                    "doc_id": meta["doc_id"], "page": info["page"], "basis": basis,
                }],
                "gold_formula": "lookup",
                "gold_pages": [[meta["doc_id"], info["page"]]],
                "answerable": True,
            })

    # 2. GROWTH (9 companies x 3 metrics = 27 via ratios.py) ---------------
    growth_specs = [
        ("revenue_growth", "revenue", "revenue"),
        ("earnings_growth", "net_profit", "net profit (profit after tax)"),
        ("eps_growth", "eps_basic", "basic EPS"),
    ]
    for sym in syms:
        meta = by_sym[sym]
        vbp = vbp_by_sym[sym]
        for ratio_name, field, lbl in growth_specs:
            res = compute_ratio(ratio_name, vbp)
            ops = res["operands"]
            pages = sorted({(o["doc_id"], o["page"]) for o in ops if o.get("page")})
            if res.get("refused") and "change_amount" in res:
                diff = res["change_amount"]
                unit_lbl = _unit_label(field, meta["unit"])
                q_txt = (
                    f"By how much did {meta['company']} ({sym})'s {meta['basis']} {lbl} change in FY2026 "
                    f"({meta['period_end']}) compared with FY2025 ({meta['prior_end']})? "
                    f"(Note: since the prior base is <= 0, state the change in {unit_lbl} rather than %)."
                )
                ans_txt = f"{diff:,.2f} {unit_lbl}"
                formula = res["formula"]
            elif not res.get("refused"):
                pct = res["value"]
                q_txt = (
                    f"What was {meta['company']} ({sym})'s {meta['basis']} {lbl} growth percentage "
                    f"in FY2026 ({meta['period_end']}) compared with FY2025 ({meta['prior_end']})?"
                )
                ans_txt = f"{pct:.2f}%"
                formula = ratio_name
            else:
                continue
            qs.append({
                "id": f"psx2_{meta['doc_id']}_{ratio_name}",
                "type": "growth",
                "template": "growth",
                "question_type": "growth",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "basis": meta["basis"],
                "period": meta["period_end"],
                "question": q_txt,
                "answer": ans_txt,
                "gold_operands": ops,
                "gold_formula": formula,
                "gold_pages": [list(p) for p in pages],
                "answerable": True,
            })

    # 3. RATIO (>= 50: 54 across net_margin x2, roe, roa, debt_to_equity x2) -
    ratio_plans = [
        ("net_margin", "margin", "net profit margin (%)", "2026-06-30", False),
        ("net_margin", "margin", "net profit margin (%)", "2025-06-30", True),
        ("roe", "ratio", "return on equity (ROE %, net profit / average equity)", "2026-06-30", False),
        ("roa", "ratio", "return on assets (ROA %, net profit / average total assets)", "2026-06-30", False),
        ("debt_to_equity", "ratio", "debt-to-equity ratio (using liabilities = assets - equity)", "2026-06-30", False),
        ("debt_to_equity", "ratio", "debt-to-equity ratio (using liabilities = assets - equity)", "2025-06-30", True),
    ]
    for sym in syms:
        meta = by_sym[sym]
        full_vbp = vbp_by_sym[sym]
        for ratio_name, tmpl, desc, target_p, single_prior in ratio_plans:
            sub_vbp = {meta["prior_end"]: full_vbp[meta["prior_end"]]} if single_prior else full_vbp
            res = compute_ratio(ratio_name, sub_vbp)
            if res.get("refused"):
                continue
            ops = res["operands"]
            pages = sorted({(o["doc_id"], o["page"]) for o in ops if o.get("page")})
            fy = "FY2025" if single_prior else "FY2026"
            unit_sym = "%" if res["unit"] == "%" else "x"
            qs.append({
                "id": f"psx2_{sym}_{fy}_{ratio_name}",
                "type": "ratio",
                "template": tmpl,
                "question_type": "ratio",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "basis": meta["basis"],
                "period": target_p,
                "question": (
                    f"Based on {meta['company']} ({sym})'s {meta['basis']} annual statements, "
                    f"what was its {desc} in {fy} (year ended {target_p})?"
                ),
                "answer": f"{res['value']:.2f}{unit_sym}",
                "gold_operands": ops,
                "gold_formula": ratio_name,
                "gold_pages": [list(p) for p in pages],
                "answerable": True,
            })

    # 4. CROSS_COMPANY (>= 50: 36 pairs net_margin + 18 pairs roe = 54) ----
    pairs = list(itertools.combinations(syms, 2))  # 36 pairs
    cross_specs = [("net_margin", "margin", "net profit margin", pairs)]
    cross_specs.append(("roe", "ratio", "return on equity (ROE)", pairs[:18]))
    for ratio_name, tmpl, desc, pair_list in cross_specs:
        for sym_a, sym_b in pair_list:
            ma, mb = by_sym[sym_a], by_sym[sym_b]
            ra = compute_ratio(ratio_name, vbp_by_sym[sym_a])
            rb = compute_ratio(ratio_name, vbp_by_sym[sym_b])
            if ra.get("refused") or rb.get("refused"):
                continue
            va, vb = ra["value"], rb["value"]
            win_sym, win_co, win_val, lose_val = (
                (sym_a, ma["company"], va, vb) if va >= vb else (sym_b, mb["company"], vb, va)
            )
            ops = ra["operands"] + rb["operands"]
            pages = sorted({(o["doc_id"], o["page"]) for o in ops if o.get("page")})
            qs.append({
                "id": f"psx2_cross_{sym_a}_{sym_b}_{ratio_name}",
                "type": "cross_company",
                "template": tmpl,
                "question_type": "cross_company",
                "doc_name": ma["doc_id"],
                "doc_names": [ma["doc_id"], mb["doc_id"]],
                "symbol": f"{sym_a},{sym_b}",
                "winner_symbol": win_sym,
                "winner_company": win_co,
                "question": (
                    f"Between {ma['company']} ({sym_a}) and {mb['company']} ({sym_b}), "
                    f"which company achieved the higher {desc} in FY2026 (ended 2026-06-30)? "
                    f"State both companies' figures."
                ),
                "answer": f"{win_val:.2f}% — {win_co} ({win_sym}) had the higher {desc} ({win_val:.2f}% vs {lose_val:.2f}%).",
                "gold_operands": ops,
                "gold_formula": ratio_name,
                "gold_pages": [list(p) for p in pages],
                "answerable": True,
            })

    # 5. UNANSWERABLE (>= 50: 18 missing period + 18 qtr vs annual + 18 field/basis = 54)
    # 5a. Missing periods (FY2022 and FY2020 not in corpus)
    for sym in syms:
        meta = by_sym[sym]
        for fy, pend, field_txt in [
            ("FY2022", "2022-06-30", "revenue"),
            ("FY2020", "2020-06-30", "return on equity (ROE)"),
        ]:
            qs.append({
                "id": f"psx2_{sym}_unans_period_{fy}",
                "type": "unanswerable",
                "template": "unanswerable",
                "unanswerable_subtype": "missing_period",
                "diff_type": "period_not_in_corpus",
                "question_type": "unanswerable",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "question": f"What was {meta['company']} ({sym})'s {field_txt} in {fy} (year ended {pend})?",
                "answer": "UNANSWERABLE",
                "gold_operands": [],
                "gold_formula": "abstain",
                "gold_pages": [],
                "answerable": False,
            })

    # 5b. Quarterly vs annual period mismatch
    for sym in syms:
        meta = by_sym[sym]
        qs.append({
            "id": f"psx2_{sym}_unans_qtr_vs_ann_rev",
            "type": "unanswerable",
            "template": "unanswerable",
            "unanswerable_subtype": "period_mismatch",
            "diff_type": "period_mismatch",
            "question_type": "unanswerable",
            "doc_name": meta["doc_id"],
            "symbol": sym,
            "question": (
                f"Compare {meta['company']} ({sym})'s Q1 FY2026 quarterly revenue with its "
                f"full-year FY2026 annual revenue and compute the annualised quarterly growth rate."
            ),
            "answer": "UNANSWERABLE",
            "gold_operands": [],
            "gold_formula": "abstain",
            "gold_pages": [],
            "answerable": False,
        })
        qs.append({
            "id": f"psx2_{sym}_unans_half_vs_ann_eps",
            "type": "unanswerable",
            "template": "unanswerable",
            "unanswerable_subtype": "period_mismatch",
            "diff_type": "period_mismatch",
            "question_type": "unanswerable",
            "doc_name": meta["doc_id"],
            "symbol": sym,
            "question": (
                f"What is the percentage difference between {meta['company']} ({sym})'s "
                f"half-yearly (6-month) EPS and annual full-year FY2026 EPS?"
            ),
            "answer": "UNANSWERABLE",
            "gold_operands": [],
            "gold_formula": "abstain",
            "gold_pages": [],
            "answerable": False,
        })

    # 5c. Unavailable basis (consolidated requested when only unconsolidated exists) + unreported fields
    standalone_only = [sym for sym in syms if by_sym[sym]["basis"] == "unconsolidated"]  # GHNI, PIOC, POWER, PRL
    for sym in standalone_only:
        meta = by_sym[sym]
        for fld in ("consolidated revenue", "consolidated net profit margin"):
            qs.append({
                "id": f"psx2_{sym}_unans_basis_{fld.replace(' ', '_')}",
                "type": "unanswerable",
                "template": "unanswerable",
                "unanswerable_subtype": "unavailable_basis",
                "diff_type": "basis",
                "question_type": "unanswerable",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "question": f"What was {meta['company']} ({sym})'s {fld} in FY2026 ({meta['period_end']})?",
                "answer": "UNANSWERABLE",
                "gold_operands": [],
                "gold_formula": "abstain",
                "gold_pages": [],
                "answerable": False,
            })

    unreported_prompts = [
        ("cloud_arr", "annual recurring revenue (ARR) from cloud software subscriptions"),
        ("ai_capex", "capital expenditure specifically spent on AI GPU clusters"),
    ]
    # Add 10 unreported-field questions across companies -> 8 + 10 = 18
    for sym in syms[:5]:
        meta = by_sym[sym]
        for tag, metric_txt in unreported_prompts:
            qs.append({
                "id": f"psx2_{sym}_unans_field_{tag}",
                "type": "unanswerable",
                "template": "unanswerable",
                "unanswerable_subtype": "missing_field",
                "diff_type": "terminology",
                "question_type": "unanswerable",
                "doc_name": meta["doc_id"],
                "symbol": sym,
                "question": f"What was {meta['company']} ({sym})'s {metric_txt} in FY2026 ({meta['period_end']})?",
                "answer": "UNANSWERABLE",
                "gold_operands": [],
                "gold_formula": "abstain",
                "gold_pages": [],
                "answerable": False,
            })

    return qs


def main() -> None:
    qs = build_questions()
    out_path = DATA / "psx_qa_v2.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for q in qs:
            f.write(json.dumps(q) + "\n")
    counts = Counter(q["type"] for q in qs)
    ans_cnt = sum(1 for q in qs if q["answerable"])
    unans_cnt = sum(1 for q in qs if not q["answerable"])
    print(f"Wrote {len(qs)} questions to {out_path} (answerable={ans_cnt}, unanswerable={unans_cnt})")
    for t in ("lookup", "growth", "ratio", "cross_company", "unanswerable"):
        print(f"  {t:15s}: {counts[t]}")


if __name__ == "__main__":
    main()
