"""Extraction experiment: rules (no AI) vs column-aware rules vs API LLM (+ column check) vs local LLM.

Test set: data/psx_extraction_gold.json (built from your labels).
One example = (report, field). A prediction is correct if it is within 0.5% of the
labelled value (EPS: within 0.01). Also reported: unit accuracy, coverage
(non-null rate), schema-valid output rate, statement-page location accuracy,
latency and cost per report.

  python eval/run_extraction.py --extractors rules columns api api+columns   # the main comparison
  python eval/run_extraction.py --extractors rules columns                   # no API calls at all
  python eval/run_extraction.py --extractors rules api local     # local = Ollama (qwen2.5:7b)

  columns      rules, but every value is read from the CURRENT-year column (word
               x-positions), pages found from the statement-title tags
  api+columns  the LLM's answer, with each value re-read from the current-year
               column of the row it came from (no extra API call: reuses "api")

Also reported: prior_column_rate = share of examples where the prior-year figure
was returned instead of the current one.

Reports are split into dev (the 9 reports whose failures we studied while writing
the column-aware rules) and held-out (every report added after that), so the
held-out numbers are the fair ones.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter

from common import DATA, percentile, save_json, update_summary

from mizan.config import get_settings
from mizan.extraction.columns import ColumnCheckedLLM, ColumnExtractor
from mizan.extraction.extractor import LLMExtractor, RuleExtractor
from mizan.ingest.parser import parse_pdf
from mizan.llm import LLM


def make(name: str):
    s = get_settings()
    if name == "rules":
        return RuleExtractor()
    if name == "columns":
        return ColumnExtractor()
    if name == "api+columns":
        return ColumnCheckedLLM(f"api:{s.llm_model}")
    if name == "api":
        return LLMExtractor(LLM(), f"api:{s.llm_model}", fallback=False)
    if name == "local":
        return LLMExtractor(LLM(base_url=s.local_llm_base_url, api_key="ollama", model=s.local_llm_model,
                                price_in=0, price_out=0), f"local:{s.local_llm_model}", fallback=False)
    raise ValueError(name)


# the reports whose failures we looked at while writing the column-aware rules
DEV_REPORTS = {"LUCK_FY2026", "PIOC_FY2026", "OGDC_FY2026", "POL_FY2026", "PRL_FY2026", "HUBC_FY2026",
               "AGIL_FY2026", "GHNI_FY2026", "POWER_FY2026"}


def close(pred, gold, field) -> bool:
    if pred is None:
        return False
    if field == "eps_basic":
        return abs(pred - gold) <= 0.011
    return abs(pred - gold) <= 0.005 * abs(gold) or abs(abs(pred) - abs(gold)) <= 0.005 * abs(gold)


def main(names: list[str]) -> dict:
    gold = json.load(open(DATA / "psx_extraction_gold.json"))
    pdf_dir = DATA / "psx_pdfs"
    pages_cache = {}
    for doc_id in gold:
        print(f"reading {doc_id} ...", flush=True)
        pages_cache[doc_id] = {p.page: p.text for p in parse_pdf(pdf_dir / f"{doc_id}.pdf", ocr=False)}
    summary, errors = {}, []
    api_results: dict[str, tuple] = {}          # doc_id -> (result, seconds, cost), reused by api+columns
    if "api+columns" in names and "api" not in names:
        names = ["api"] + list(names)
    names = sorted(names, key=lambda n: n == "api+columns")   # api must run first
    for name in names:
        ex = make(name)
        hits, total, unit_ok, nonnull, valid, page_hit, prior_taken = 0, 0, 0, 0, 0, 0, 0
        held_hits, held_total = 0, 0
        lat, cost, causes = [], [], Counter()
        for doc_id, g in gold.items():
            t = time.perf_counter()
            print(f"  {name}: {doc_id}", flush=True)
            pdf = pdf_dir / f"{doc_id}.pdf"
            if name == "columns":
                res = ex.extract(pages_cache[doc_id], g["_meta"]["company"], pdf_path=pdf)
            elif name == "api+columns":
                base, secs, c = api_results[doc_id]
                res = ex.correct(base, pdf)
                lat.append(secs + time.perf_counter() - t)
                cost.append(c)
            else:
                res = ex.extract(pages_cache[doc_id], g["_meta"]["company"])
            if name != "api+columns":
                lat.append(time.perf_counter() - t)
            if name != "api+columns":
                cost.append(res.usage.cost(getattr(getattr(ex, "llm", None), "price_in", 0),
                                           getattr(getattr(ex, "llm", None), "price_out", 0)))
            if name == "api":
                api_results[doc_id] = (res, lat[-1], cost[-1])
            fh = res.highlights
            valid += fh is not None
            unit_ok += fh is not None and fh.unit == g["_meta"]["unit"]
            gold_pages = {v["page"] for k, v in g.items() if k != "_meta"}
            page_hit += bool(gold_pages & set(res.pages_used))
            for field, gv in g.items():
                if field == "_meta":
                    continue
                total += 1
                pred = getattr(fh, field).value if fh else None
                nonnull += pred is not None
                ok = close(pred, gv["value"], field)
                hits += ok
                if doc_id not in DEV_REPORTS:
                    held_hits += ok
                    held_total += 1
                prior_taken += (not ok and gv.get("prior") is not None and close(pred, gv["prior"], field))
                if not ok:
                    if fh is None:
                        cause = "invalid_or_no_output"
                    elif pred is None:
                        cause = "missing_field" + ("" if gv["page"] in res.pages_used else "_page_not_located")
                    elif gv.get("prior") is not None and close(pred, gv["prior"], field):
                        cause = "took_prior_period_column"
                    elif any(close(pred * s, gv["value"], field) for s in (1e3, 1e-3, 1e6, 1e-6)):
                        cause = "unit_scale"
                    elif gv["page"] not in res.pages_used:
                        cause = "page_not_located"
                    else:
                        cause = "wrong_line_item_or_consolidation"
                    causes[cause] += 1
                    errors.append({"extractor": name, "doc_id": doc_id, "field": field, "gold": gv["value"],
                                   "pred": pred, "cause": cause, "gold_page": gv["page"], "pages_used": res.pages_used})
        n_docs = len(gold)
        summary[getattr(ex, "name", name)] = {
            "field_accuracy": round(hits / total, 3), "n_examples": total, "n_reports": n_docs,
            "coverage": round(nonnull / total, 3), "schema_valid_rate": round(valid / n_docs, 3),
            "unit_accuracy": round(unit_ok / n_docs, 3), "statement_page_located": round(page_hit / n_docs, 3),
            "latency_p50_s": round(percentile(lat, .5), 2), "latency_p95_s": round(percentile(lat, .95), 2),
            "cost_per_report_usd": round(statistics.mean(cost), 5), "error_causes": dict(causes),
            "prior_column_rate": round(prior_taken / total, 3),
            "field_accuracy_dev": round((hits - held_hits) / max(1, total - held_total), 3),
            "field_accuracy_heldout": round(held_hits / held_total, 3) if held_total else None,
            "n_examples_heldout": held_total}
        if name == "api+columns":
            summary[getattr(ex, "name", name)]["values_corrected_by_code"] = len(ex.corrections)
        print(name, summary[getattr(ex, "name", name)])
    save_json(errors, "extraction_errors.json")
    update_summary("extraction", summary)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractors", nargs="+", default=["rules", "columns", "api", "api+columns"])
    main(ap.parse_args().extractors)
