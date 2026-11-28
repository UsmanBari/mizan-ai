"""Score RQ1 stage-wise error attribution, RQ3 abstention, Retrieval->QA, and RQ2 transfer.

Outputs saved into eval/results/summary.json under:
  - psx_v2_stages         (RQ1: extraction, operand selection, formula selection, arithmetic, final)
  - psx_v2_abstention     (RQ3: abstention P/R/F1, selective accuracy, coverage)
  - psx_v2_retrieval_qa   (Retrieval R@5 vs Agent accuracy for bm25, dense, hybridx)
  - rq2_transfer          (FinanceBench vs PSX per shared template + difference-type failure tags)

Usage:
  python eval/score_stages.py
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter

from common import DATA, RESULTS, build_psx_store, load_financebench, load_psx_v2, numbers, numeric_match, update_summary

from mizan.calculator import calculate
from mizan.ratios import FIELD_ALIASES, canonical_ratio_name
from mizan.retrieval.retrievers import build_retriever

_SCALE_FACTORS = (1.0, 1e3, 1e-3, 1e6, 1e-6)


def _norm_field(raw: str) -> str:
    low = re.sub(r"_(?:20\d\d|19\d\d|cur|current|pri|prior).*$", "", raw.lower().strip())
    low = re.sub(r"^(?:a|b)_", "", low)
    for canon, aliases in FIELD_ALIASES.items():
        if low == canon or any(low == a or a in low for a in aliases):
            return canon
    if "pat" in low or "profit" in low and "before" not in low:
        return "net_profit"
    if "pbt" in low:
        return "profit_before_tax"
    if "rev" in low or "sales" in low or "turnover" in low:
        return "revenue"
    if "asset" in low:
        return "total_assets"
    if "eq" in low:
        return "total_equity"
    if "eps" in low:
        return "eps_basic"
    return low


def _close_any_scale(val: float, target: float, rel_tol: float = 0.005) -> bool:
    for s in _SCALE_FACTORS:
        v = val * s
        if abs(v - target) <= max(rel_tol * abs(target), 0.01 if abs(target) < 100 else 0):
            return True
    return False


def _trace_operands(rec: dict) -> list[dict]:
    """Extract normalized operand dicts from a QA record's trace."""
    ops = []
    for cv in rec.get("calculated_values") or []:
        for o in cv.get("operands") or []:
            if isinstance(o, dict) and o.get("value") is not None:
                ops.append({
                    "field": _norm_field(str(o.get("field", ""))),
                    "period": str(o.get("period", "")),
                    "value": float(o["value"]),
                    "basis": str(o.get("basis", rec.get("basis") or "")),
                    "doc_id": str(o.get("doc_id", "")),
                    "page": o.get("page"),
                })
    if ops:
        return ops
    for rf in rec.get("reported_figures") or []:
        if isinstance(rf, dict) and rf.get("value") is not None:
            raw_name = str(rf.get("field", ""))
            yr = re.search(r"(20\d\d)", raw_name) or re.search(r"(20\d\d)", str(rf.get("period", "")))
            ops.append({
                "field": _norm_field(raw_name),
                "period": str(rf.get("period") or (yr.group(1) if yr else "")),
                "value": float(rf["value"]),
                "basis": str(rf.get("basis") or rec.get("basis") or ""),
                "doc_id": str(rf.get("doc_id", "")),
                "page": rf.get("page"),
            })
    if ops:
        return ops
    for calc in rec.get("calculations") or []:
        for k, v in (calc.get("variables") or {}).items():
            yr = re.search(r"(20\d\d)", str(k))
            ops.append({
                "field": _norm_field(str(k)),
                "period": yr.group(1) if yr else "",
                "value": float(v),
                "basis": str(rec.get("basis") or ""),
                "doc_id": "",
                "page": None,
            })
    return ops


def _periods_year_set(period_str: str) -> str:
    m = re.search(r"(20\d\d|19\d\d)", str(period_str))
    return m.group(1) if m else str(period_str)


def _check_extraction(rec: dict, gold_ops: list[dict], trace_ops: list[dict]) -> bool | None:
    if not gold_ops:
        return None
    cand_vals = [o["value"] for o in trace_ops]
    if not cand_vals:
        # For single lookup without explicit calc trace, check answer numbers
        if rec.get("type") == "lookup" and not rec.get("refused"):
            cand_vals = numbers(rec.get("answer", ""))
        else:
            return False if rec.get("mode") != "rag_direct" else None
    if not cand_vals:
        return False
    return all(any(_close_any_scale(cv, float(go["value"])) for cv in cand_vals) for go in gold_ops)


def _check_operand_selection(rec: dict, gold_ops: list[dict], trace_ops: list[dict], q: dict) -> bool | None:
    if not gold_ops:
        return None
    if not trace_ops:
        if rec.get("mode") == "rag_direct":
            return None
        return False
    gold_fields = {_norm_field(go["field"]) for go in gold_ops}
    sys_fields = {_norm_field(so["field"]) for so in trace_ops}
    # Allow (total_assets, total_equity) -> debt_to_equity or liabilities
    if gold_fields == {"total_assets", "total_equity"} and {"total_liabilities", "total_equity"} <= sys_fields:
        fields_ok = True
    else:
        fields_ok = gold_fields <= sys_fields

    gold_years = {_periods_year_set(go["period"]) for go in gold_ops if go.get("period")}
    sys_years = {_periods_year_set(so["period"]) for so in trace_ops if so.get("period")}
    if not sys_years:
        # Check if periods appeared in question/calc variables when trace omits period tag
        periods_ok = True if rec.get("mode") == "rag_calc" and len(gold_years) == 1 else False
    else:
        periods_ok = gold_years <= sys_years

    gold_bases = {go.get("basis", "") for go in gold_ops if go.get("basis")}
    sys_basis = rec.get("basis") or ""
    sys_bases = {so.get("basis", "") for so in trace_ops if so.get("basis")} or ({sys_basis} if sys_basis else set())
    basis_ok = (not sys_bases) or bool(gold_bases & sys_bases)
    return fields_ok and periods_ok and basis_ok


def _check_formula(rec: dict, q: dict) -> bool | None:
    gf = q.get("gold_formula", "")
    if gf in ("lookup", "abstain", ""):
        return None
    if rec.get("mode") == "rag_direct":
        return None
    cvs = rec.get("calculated_values") or []
    calcs = rec.get("calculations") or []
    names = [canonical_ratio_name(cv.get("name", "")) or cv.get("name", "") for cv in cvs]
    exprs = [str(cv.get("formula", "")) for cv in cvs] + [str(c.get("expression", "")) for c in calcs]
    joined = " ".join(exprs).lower()

    canon_gf = canonical_ratio_name(gf) or gf
    if canon_gf in names:
        return True
    if "change_amount" in " ".join(str(cv.get("name", "")) for cv in cvs) and "-" in joined and "prior" in joined:
        return True
    if canon_gf in ("net_margin", "gross_margin", "operating_margin"):
        return "/" in joined and "* 100" in joined.replace("*100", "* 100")
    if canon_gf in ("revenue_growth", "earnings_growth", "eps_growth"):
        return "pct_change" in joined or ("-" in joined and "/" in joined)
    if canon_gf in ("roe", "roa"):
        return "/" in joined and ("avg" in joined or "/ 2" in joined or "/2" in joined)
    if canon_gf == "debt_to_equity":
        return "/" in joined and ("-" in joined or "liab" in joined or len(calcs) >= 1)
    if "-" in gf and "-" in joined:  # base <= 0 change in amount
        return True
    return False


def _check_arithmetic(rec: dict, q: dict) -> bool | None:
    if q.get("gold_formula") in ("lookup", "abstain", ""):
        return None
    if rec.get("mode") == "rag_direct":
        return None
    calcs = rec.get("calculations") or []
    cvs = rec.get("calculated_values") or []
    if cvs and all(cv.get("result") is not None for cv in cvs):
        # Verify AST calcs agree where present
        for c in calcs:
            if c.get("error"):
                return False
            if c.get("expression") and c.get("variables"):
                recalc = calculate(c["expression"], c["variables"])
                if recalc.result is not None and c.get("result") is not None:
                    if not _close_any_scale(recalc.result, float(c["result"])):
                        return False
        return True
    if not calcs:
        return False
    ok_any = False
    for c in calcs:
        if c.get("error") or c.get("result") is None:
            return False
        recalc = calculate(c["expression"], c["variables"])
        if recalc.result is None or not _close_any_scale(recalc.result, float(c["result"])):
            return False
        ok_any = True
    return ok_any


def score_file(path, q_map: dict[str, dict]) -> dict:
    last = {}
    for row in map(json.loads, open(path, encoding="utf-8")):
        if "error" in row and row["id"] in last and "error" not in last[row["id"]]:
            continue
        last[row["id"]] = row
    ok = [r for r in last.values() if "error" not in r and r["id"] in q_map]
    if not ok:
        return {}

    ans_recs = [r for r in ok if q_map[r["id"]].get("answerable", True)]
    unans_recs = [r for r in ok if not q_map[r["id"]].get("answerable", True)]

    ext_scores, op_scores, form_scores, arith_scores = [], [], [], []
    for r in ans_recs:
        q = q_map[r["id"]]
        gold_ops = q.get("gold_operands") or []
        trace_ops = _trace_operands(r)
        e = _check_extraction(r, gold_ops, trace_ops)
        o = _check_operand_selection(r, gold_ops, trace_ops, q)
        f = _check_formula(r, q)
        a = _check_arithmetic(r, q)
        if e is not None:
            ext_scores.append(e)
        if o is not None:
            op_scores.append(o)
        if f is not None:
            form_scores.append(f)
        if a is not None:
            arith_scores.append(a)

    by_type = {}
    for t in ("lookup", "growth", "ratio", "cross_company", "unanswerable"):
        sub = [r for r in ok if r.get("type") == t]
        if sub:
            by_type[t] = {
                "n": len(sub),
                "accuracy": round(sum(bool(r.get("correct")) for r in sub) / len(sub), 3),
            }

    # RQ3 abstention
    tp = sum(1 for r in unans_recs if r.get("refused"))
    fn = sum(1 for r in unans_recs if not r.get("refused"))
    fp = sum(1 for r in ans_recs if r.get("refused"))
    tn = sum(1 for r in ans_recs if not r.get("refused"))
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec_abst = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec_abst / (prec + rec_abst)) if (prec + rec_abst) else 0.0
    answered = [r for r in ok if not r.get("refused")]
    sel_acc = sum(bool(r.get("correct")) for r in answered) / len(answered) if answered else 0.0
    cov = len(answered) / len(ok)
    ans_cov = tn / len(ans_recs) if ans_recs else 0.0

    return {
        "n_total": len(ok),
        "n_answerable": len(ans_recs),
        "n_unanswerable": len(unans_recs),
        "stages": {
            "extraction_accuracy": round(statistics.mean(ext_scores), 3) if ext_scores else None,
            "operand_selection_accuracy": round(statistics.mean(op_scores), 3) if op_scores else None,
            "formula_selection_accuracy": round(statistics.mean(form_scores), 3) if form_scores else None,
            "arithmetic_accuracy": round(statistics.mean(arith_scores), 3) if arith_scores else None,
            "answerable_accuracy": round(sum(bool(r.get("correct")) for r in ans_recs) / len(ans_recs), 3) if ans_recs else None,
            "overall_accuracy": round(sum(bool(r.get("correct")) for r in ok) / len(ok), 3),
        },
        "by_type": by_type,
        "abstention": {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 3),
            "recall": round(rec_abst, 3),
            "f1": round(f1, 3),
            "selective_accuracy": round(sel_acc, 3),
            "coverage": round(cov, 3),
            "answerable_coverage": round(ans_cov, 3),
        },
    }


def _fb_template(q: dict) -> str:
    txt = q["question"].lower()
    if any(k in txt for k in ("gross margin", "operating margin", "net margin", "profit margin", "ebitda margin")):
        return "margin"
    if any(k in txt for k in ("growth", "year-over-year", "yoy", "percent change", "percentage change", "cagr", "grew")):
        return "growth"
    if q.get("question_reasoning") == "Information extraction" or any(k in txt for k in ("how much", "what was the fy", "what is the fy")):
        return "lookup"
    return "other"


def _psx_failure_diff_tag(rec: dict, q: dict, notes_by_doc: dict[str, str]) -> str:
    if not q.get("answerable", True):
        return q.get("diff_type") or "period_mismatch"
    if rec.get("scale_issue"):
        return "unit convention"
    q_txt = q["question"].lower()
    doc = q.get("doc_name", "")
    note = notes_by_doc.get(doc, "").lower()
    if q.get("type") == "cross_company" or "consolidated" in q_txt or "unconsolidated" in q_txt:
        return "basis"
    if "two printed pages" in note or "no label" in note or "unlabelled" in note:
        return "layout/columns"
    if "turnover" in note or "net sales" in note or "contracts with customers" in note or "ligature" in note:
        return "terminology"
    if any(w in q_txt for w in ("profit before tax", "profit after tax", "revenue", "net profit")):
        return "statement naming"
    return "unit convention"


def compute_psx_retrieval_r5(qs: list[dict], store, retriever_kind: str) -> dict:
    retr = build_retriever(store, retriever_kind)
    by_tmpl = {"lookup": [], "growth": [], "margin": [], "all": []}
    for q in qs:
        if not q.get("answerable", True) or not q.get("gold_pages"):
            continue
        gold = set(map(tuple, q["gold_pages"]))
        hits = retr.retrieve(q["question"], 20, None)
        pages = []
        seen = set()
        for h in hits:
            k = (h.chunk.doc_id, h.chunk.page)
            if k not in seen:
                seen.add(k)
                pages.append(k)
        r5 = len(gold & set(pages[:5])) / len(gold)
        by_tmpl["all"].append(r5)
        t = q.get("template")
        if t in by_tmpl:
            by_tmpl[t].append(r5)
    return {k: round(statistics.mean(v), 3) if v else None for k, v in by_tmpl.items()}


def main() -> None:
    psx_qs = load_psx_v2()
    q_map = {q["id"]: q for q in psx_qs}

    # Load label notes per doc for RQ2 difference tagging
    notes_by_doc = {}
    with open(DATA / "psx_labels.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            notes_by_doc[r["doc_id"]] = notes_by_doc.get(r["doc_id"], "") + " " + r.get("notes", "")

    candidates = [
        ("rag_direct|hybridx", RESULTS / "qa_psx_v2_rag_direct_run1.jsonl"),
        ("rag_calc|hybridx", RESULTS / "qa_psx_v2_rag_calc_run1.jsonl"),
        ("agent|hybridx", RESULTS / "qa_psx_v2_agent_run1.jsonl"),
        ("agent|bm25", RESULTS / "qa_psx_v2_bm25_agent_run1.jsonl"),
    ]
    stages_out, abstention_out = {}, {}
    recs_by_key = {}
    for key, p in candidates:
        if not p.exists():
            continue
        scored = score_file(p, q_map)
        if not scored:
            continue
        stages_out[key] = {
            "n_total": scored["n_total"],
            "n_answerable": scored["n_answerable"],
            **scored["stages"],
            "by_type": scored["by_type"],
        }
        abstention_out[key] = {
            "n_total": scored["n_total"],
            **scored["abstention"],
        }
        last_rows = {}
        for row in map(json.loads, open(p, encoding="utf-8")):
            if "error" in row and row["id"] in last_rows and "error" not in last_rows[row["id"]]:
                continue
            last_rows[row["id"]] = row
        recs_by_key[key] = {k: v for k, v in last_rows.items() if "error" not in v and k in q_map}
    psx_agent_recs = recs_by_key.get("agent|hybridx", {})

    if stages_out:
        update_summary("psx_v2_stages", stages_out)
        update_summary("psx_v2_abstention", abstention_out)
        print("=== RQ1 Stage-wise Attribution (PSX v2) ===")
        for k, v in stages_out.items():
            print(
                f"{k:20s} ext={v['extraction_accuracy']} op={v['operand_selection_accuracy']} "
                f"form={v['formula_selection_accuracy']} arith={v['arithmetic_accuracy']} "
                f"ans_acc={v['answerable_accuracy']} overall={v['overall_accuracy']}"
            )
        print("\n=== RQ3 Abstention (PSX v2) ===")
        for k, v in abstention_out.items():
            print(
                f"{k:20s} P={v['precision']} R={v['recall']} F1={v['f1']} "
                f"sel_acc={v['selective_accuracy']} cov={v['coverage']}"
            )

    # Retrieval -> Answers & RQ2 transfer ----------------------------------
    store = build_psx_store()
    psx_ret = {}
    for rkind in ("bm25", "dense", "hybridx"):
        psx_ret[rkind] = compute_psx_retrieval_r5(psx_qs, store, rkind)

    def _mcnemar(a: list[bool], b: list[bool]) -> dict:
        n01 = sum(1 for x, y in zip(a, b) if not x and y)
        n10 = sum(1 for x, y in zip(a, b) if x and not y)
        n = n01 + n10
        if n == 0:
            return {"n": len(a), "a_only_correct": 0, "b_only_correct": 0, "p_value": 1.0}
        k = min(n01, n10)
        p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
        return {"n": len(a), "a_only_correct": n10, "b_only_correct": n01, "p_value": round(p, 4)}

    def _trace_stats(recs: dict[str, dict]) -> dict:
        rows = list(recs.values())
        comp_ratio = 0
        only_comp_pages = 0
        search_or_read = 0
        det_guard = 0
        for r in rows:
            has_comp = any(cv.get("name") not in (None, "calculation") for cv in (r.get("calculated_values") or []))
            if has_comp:
                comp_ratio += 1
            op_pages = {
                (o.get("doc_id"), o.get("page"))
                for cv in (r.get("calculated_values") or [])
                if cv.get("name") != "calculation"
                for o in (cv.get("operands") or [])
                if o.get("doc_id") and o.get("page")
            }
            ctx_pages = {(c.get("doc_id"), c.get("page")) for c in (r.get("context_pages") or [])}
            if not ctx_pages:
                det_guard += 1
            elif not (ctx_pages - op_pages):
                only_comp_pages += 1
            else:
                search_or_read += 1
        return {
            "n": len(rows),
            "deterministic_guard_steps0": det_guard,
            "compute_ratio_used": comp_ratio,
            "compute_ratio_only_no_search_pages": only_comp_pages,
            "search_or_read_page_used": search_or_read,
            "mean_steps": round(statistics.mean(r.get("steps", 0) for r in rows), 2),
            "mean_context_pages": round(statistics.mean(len(r.get("context_pages") or []) for r in rows), 2),
        }

    ret_qa = {}
    for rkind, tag_key in [("bm25", "agent|bm25"), ("dense", "agent|dense"), ("hybridx", "agent|hybridx")]:
        if rkind == "dense":
            ret_qa[rkind] = {
                "retrieval_r5": psx_ret[rkind]["all"],
                "answerable_accuracy": None,
                "overall_accuracy": None,
                "status": "not run (free-tier quota)",
            }
            continue
        ret_qa[rkind] = {
            "retrieval_r5": psx_ret[rkind]["all"],
            "answerable_accuracy": stages_out[tag_key]["answerable_accuracy"] if tag_key in stages_out else None,
            "overall_accuracy": stages_out[tag_key]["overall_accuracy"] if tag_key in stages_out else None,
            "tool_traces": _trace_stats(recs_by_key[tag_key]) if tag_key in recs_by_key else {},
        }
    if "agent|bm25" in recs_by_key and "agent|hybridx" in recs_by_key:
        bm_d, hy_d = recs_by_key["agent|bm25"], recs_by_key["agent|hybridx"]
        paired_all = sorted(set(bm_d) & set(hy_d))
        paired_ans = [qid for qid in paired_all if q_map[qid].get("answerable", True)]
        ret_qa["mcnemar_bm25_vs_hybridx"] = {
            "overall_all_243": _mcnemar([bool(bm_d[i].get("correct")) for i in paired_all], [bool(hy_d[i].get("correct")) for i in paired_all]),
            "answerable_189": _mcnemar([bool(bm_d[i].get("correct")) for i in paired_ans], [bool(hy_d[i].get("correct")) for i in paired_ans]),
        }
    update_summary("psx_v2_retrieval_qa", ret_qa)
    print("\n=== Retrieval -> Answers (PSX v2 Agent) ===")
    for rkind in ("bm25", "dense", "hybridx"):
        v = ret_qa[rkind]
        print(f"{rkind:10s} R@5={v['retrieval_r5']} ans_acc={v['answerable_accuracy']} overall={v['overall_accuracy']} {v.get('status','')}")
    if "mcnemar_bm25_vs_hybridx" in ret_qa:
        print("McNemar bm25 vs hybridx:", ret_qa["mcnemar_bm25_vs_hybridx"])

    # RQ2 Cross-Market Transfer: FinanceBench vs PSX per shared template ---
    fb_qs = {q["id"]: q for q in load_financebench("test")}
    fb_qa_path = RESULTS / "qa_agent_run1.jsonl"
    fb_ret_path = RESULTS / "retrieval_per_query.json"
    fb_qa_by_t = {"lookup": [], "growth": [], "margin": []}
    if fb_qa_path.exists():
        for row in map(json.loads, open(fb_qa_path, encoding="utf-8")):
            if "error" not in row and row["id"] in fb_qs:
                t = _fb_template(fb_qs[row["id"]])
                if t in fb_qa_by_t and row.get("correct") is not None:
                    fb_qa_by_t[t].append(bool(row["correct"]))

    fb_ret_by_t = {"lookup": [], "growth": [], "margin": []}
    if fb_ret_path.exists():
        for row in json.loads(fb_ret_path.read_text()):
            if row.get("retriever") == "hybridx" and row.get("setting") == "open" and row["id"] in fb_qs:
                t = _fb_template(fb_qs[row["id"]])
                if t in fb_ret_by_t:
                    fb_ret_by_t[t].append(float(row["recall@5"]))

    psx_qa_by_t = {"lookup": [], "growth": [], "margin": []}
    psx_fail_tags = Counter()
    psx_fail_examples = []
    for qid, row in psx_agent_recs.items():
        q = q_map.get(qid)
        if not q:
            continue
        t = q.get("template")
        if t in psx_qa_by_t and row.get("correct") is not None:
            psx_qa_by_t[t].append(bool(row["correct"]))
        if not row.get("correct"):
            tag = _psx_failure_diff_tag(row, q, notes_by_doc)
            psx_fail_tags[tag] += 1
            if len(psx_fail_examples) < 25:
                psx_fail_examples.append({
                    "id": qid,
                    "type": q.get("type"),
                    "template": t,
                    "diff_type": tag,
                    "gold": q["answer"],
                    "answer": row.get("answer", "")[:200],
                    "refused": row.get("refused"),
                })

    templates_table = {}
    for t in ("lookup", "growth", "margin"):
        templates_table[t] = {
            "financebench_n_qa": len(fb_qa_by_t[t]),
            "financebench_accuracy": round(statistics.mean(fb_qa_by_t[t]), 3) if fb_qa_by_t[t] else None,
            "financebench_retrieval_r5_open_hybridx": round(statistics.mean(fb_ret_by_t[t]), 3) if fb_ret_by_t[t] else None,
            "psx_n_qa": len(psx_qa_by_t[t]),
            "psx_accuracy": round(statistics.mean(psx_qa_by_t[t]), 3) if psx_qa_by_t[t] else None,
            "psx_retrieval_r5_open_hybridx": psx_ret["hybridx"].get(t),
        }

    rq2_payload = {
        "templates": templates_table,
        "psx_failure_diff_types": dict(psx_fail_tags),
        "psx_failure_examples": psx_fail_examples,
    }
    update_summary("rq2_transfer", rq2_payload)
    print("\n=== RQ2 Cross-Market Transfer (FinanceBench vs PSX) ===")
    for t, row in templates_table.items():
        print(
            f"{t:8s} FB_acc={row['financebench_accuracy']} (R@5={row['financebench_retrieval_r5_open_hybridx']}) | "
            f"PSX_acc={row['psx_accuracy']} (R@5={row['psx_retrieval_r5_open_hybridx']})"
        )
    print("PSX failure difference tags:", dict(psx_fail_tags))


if __name__ == "__main__":
    main()
