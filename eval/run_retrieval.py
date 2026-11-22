"""Retrieval experiment: which retriever finds the gold evidence page?

Alternatives: bm25 | dense | hybrid (RRF) | hybrid+rerank (| bm25+rerank)
Settings:
  scoped : search only inside the question's filing (product use: user picks a company/report)
  open   : search across all 84 filings (harder: must also find the right document/year)
Metrics (page level): Recall@1/3/5/10, MRR@10, nDCG@10. Latency per query.

Usage:
  python eval/run_retrieval.py --retrievers bm25                      # runs anywhere, no models
  python eval/run_retrieval.py --retrievers bm25 dense hybrid hybrid+rerank   # needs sentence-transformers
"""
from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import Counter

from common import build_store, load_financebench, percentile, save_json, update_summary

from mizan.retrieval.retrievers import build_retriever

KS = (1, 3, 5, 10)


def ranked_pages(hits) -> list[tuple[str, int]]:
    seen, out = set(), []
    for h in hits:
        key = (h.chunk.doc_id, h.chunk.page)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def score(pages: list[tuple[str, int]], gold: set[tuple[str, int]]) -> dict:
    res = {}
    for k in KS:
        res[f"recall@{k}"] = len(gold & set(pages[:k])) / len(gold)
    rr = 0.0
    for i, p in enumerate(pages[:10], 1):
        if p in gold:
            rr = 1 / i
            break
    res["mrr@10"] = rr
    dcg = sum(1 / math.log2(i + 1) for i, p in enumerate(pages[:10], 1) if p in gold)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 10) + 1))
    res["ndcg@10"] = dcg / idcg
    return res


def failure_cause(q: dict, pages: list[tuple[str, int]], gold: set) -> str:
    top5 = pages[:5]
    gold_docs = {d for d, _ in gold}
    if not any(d in gold_docs for d, _ in top5):
        same_company = any(d.split("_")[0] == q["doc_name"].split("_")[0] for d, _ in top5)
        return "wrong_period_same_company" if same_company else "wrong_company"
    if any(d in gold_docs and min(abs(p - gp) for _, gp in gold) == 1 for d, p in top5):
        return "adjacent_page"
    if len(gold) > 1 and gold & set(top5):
        return "partial_multi_page_evidence"
    if q["question_type"] == "novel-generated" or "?" in q["question"] and len(q["question"]) < 80:
        return "short_or_vague_question"
    return "vocabulary_mismatch"


def run(retriever_names: list[str], settings: list[str], k_pool: int = 20) -> dict:
    qs = load_financebench("test")
    store = build_store(load_financebench("all"))
    print(f"store: {len(store.list_documents())} filings, {len(store.chunks())} chunks")
    summary, per_query = {}, []
    for name in retriever_names:
        t0 = time.time()
        if ":" in name:  # ablations: bm25:expand (glossary only) / bm25:route (routing only)
            from mizan.retrieval.query import ExpandedRetriever
            base, part = name.split(":")
            retr = ExpandedRetriever(build_retriever(store, base), store,
                                     expand=part == "expand", route=part == "route")
        else:
            retr = build_retriever(store, name)
        print(f"[{name}] ready in {time.time() - t0:.0f}s")
        for setting in settings:
            rows, lat, causes, failures = [], [], Counter(), []
            for q in qs:
                gold = set(map(tuple, q["gold_pages"]))
                scope = [q["doc_name"]] if setting == "scoped" else None
                t = time.perf_counter()
                hits = retr.retrieve(q["question"], k_pool, scope)
                lat.append(time.perf_counter() - t)
                pages = ranked_pages(hits)
                s = score(pages, gold)
                rows.append(s)
                rec = {"id": q["id"], "retriever": name, "setting": setting, **s,
                       "gold": sorted(gold), "top5": pages[:5]}
                if s["recall@5"] == 0:
                    rec["cause"] = failure_cause(q, pages, gold)
                    causes[rec["cause"]] += 1
                    failures.append({**rec, "question": q["question"], "type": q["question_type"]})
                per_query.append(rec)
            agg = {m: round(statistics.mean(r[m] for r in rows), 4) for m in rows[0]}
            agg.update(n=len(rows), latency_p50_ms=round(percentile(lat, .5) * 1000, 1),
                       latency_p95_ms=round(percentile(lat, .95) * 1000, 1),
                       failures_at5=sum(causes.values()), failure_causes=dict(causes))
            summary[f"{name}|{setting}"] = agg
            save_json(failures, f"retrieval_failures_{name.replace('+', '_').replace(':', '_')}_{setting}.json")
            print(f"  {setting:6s} R@1={agg['recall@1']:.3f} R@5={agg['recall@5']:.3f} "
                  f"R@10={agg['recall@10']:.3f} MRR={agg['mrr@10']:.3f} p50={agg['latency_p50_ms']}ms")
    save_json(per_query, "retrieval_per_query.json")
    update_summary("retrieval", summary)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrievers", nargs="+", default=["bm25"])
    ap.add_argument("--settings", nargs="+", default=["scoped", "open"])
    a = ap.parse_args()
    run(a.retrievers, a.settings)
