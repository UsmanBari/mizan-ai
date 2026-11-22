"""QA experiment (the R&D research question).

RQ1: Does making the LLM hand arithmetic to a deterministic calculator
     (rag_calc / agent) reduce numerical errors compared with letting it compute
     (rag_direct)? closed_book is the no-retrieval lower bound.

For every test question and mode we record: correctness, refusal, grounding,
whether a gold page was retrieved, latency, tokens, cost, steps, tool errors.
Repeated runs (--runs, default 3) give mean +/- std; a paired McNemar test
compares two modes on the same questions.

Usage (needs an LLM key, e.g. free Gemini key in MIZAN_LLM_API_KEY):
  python eval/run_qa.py --modes rag_direct rag_calc agent closed_book --runs 3
  python eval/run_qa.py --modes rag_direct rag_calc --limit 20 --runs 1      # quick check
Results are appended to eval/results/qa_<mode>_run<r>.jsonl (resumable), then
summarised into eval/results/summary.json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from collections import Counter
from pathlib import Path

from common import (RESULTS, build_psx_store, build_store, load_financebench, load_psx, numeric_match,
                    percentile, update_summary)

from mizan.agent.engine import _PAGEREF_RE, QAEngine, grounding_check
from mizan.agent.prompts import PROMPT_VERSION
from mizan.config import get_settings
from mizan.llm import LLM, extract_json
from mizan.retrieval.retrievers import build_retriever

JUDGE_PROMPT = """You grade answers to financial questions against a gold answer.
The candidate is CORRECT if it reaches the same conclusion / same figure as the gold
answer (allow rounding and equivalent units). It is INCORRECT if it gives a different
figure or conclusion, or refuses. Ignore extra explanation.
Return JSON: {"correct": true|false, "reason": "short"}"""


class Judge:
    """LLM-as-judge, used ONLY when the gold answer has no number (yes/no or
    explanation questions). Cached on disk so re-scoring is free and reproducible."""

    def __init__(self, model: str | None, cache: Path) -> None:
        self.llm = LLM(model=model) if model else None
        self.cache_path = cache
        self.cache = json.loads(cache.read_text()) if cache.exists() else {}

    def __call__(self, q: str, gold: str, pred: str) -> dict:
        key = f"{q}||{gold}||{pred}"
        if key in self.cache:
            return self.cache[key]
        if self.llm is None:
            return {"correct": None, "reason": "no judge configured"}
        r = None
        delay = 5
        for attempt in range(6):
            try:
                r = self.llm.chat([{"role": "system", "content": JUDGE_PROMPT},
                                   {"role": "user", "content": f"Question: {q}\nGold: {gold}\nCandidate: {pred}"}],
                                  json_mode=True, max_tokens=200)
                break
            except Exception as e:
                msg = str(e)
                retryable = any(k in msg for k in ("503", "429", "overloaded", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                                                    "timed out", "Timeout", "Connection"))
                if not retryable or attempt == 5:
                    return {"correct": None, "reason": f"judge error: {msg[:100]}"}
                time.sleep(delay)
                delay = min(delay * 2, 60)
        if r is None:
            return {"correct": None, "reason": "judge failed"}
        try:
            out = extract_json(r.content)
            out = {"correct": bool(out.get("correct")), "reason": str(out.get("reason", ""))[:200]}
        except ValueError:
            out = {"correct": None, "reason": "judge output unparsable"}
        self.cache[key] = out
        self.cache_path.write_text(json.dumps(self.cache))
        return out


def grade(q: dict, ans, store, judge: Judge) -> dict:
    gold = str(q["answer"])
    m = numeric_match(ans.answer, gold)
    if m["numeric"] and q["question_type"] != "domain-relevant":
        correct, method = m["correct"], "numeric"
        if ans.refused:
            correct = False
    else:
        j = judge(q["question"], gold, ans.answer)
        correct, method = j["correct"], "judge"
        if ans.refused:
            correct = False
    gold_pages = {tuple(p) for p in q["gold_pages"]}
    ctx = {(c.doc_id, c.page) for c in ans.context_pages} | {(c.doc_id, c.page) for c in ans.citations}
    cited_pages = {c.page for c in ans.citations}
    inline_pages = {int(n) for ref in _PAGEREF_RE.findall(ans.answer) for n in re.findall(r"\d+", ref)}
    return {"correct": correct, "method": method, "scale_issue": m.get("scale", False),
            # pages written in the answer text that are not among the returned citations
            "inline_page_mismatch": bool(inline_pages - cited_pages),
            "gold_page_retrieved": bool(gold_pages & ctx),
            "gold_page_cited": bool(gold_pages & {(c.doc_id, c.page) for c in ans.citations}),
            "grounding": round(grounding_check(ans, store), 3)}


def answer_with_backoff(engine, question, mode, doc_ids, tries: int = 6):
    """Gemini 3.x often returns 503 'overloaded' / 429 rate limit on long runs:
    retry with exponential backoff (5, 10, 20, 40, 60, 60 s) before giving up."""
    delay = 5
    for attempt in range(tries):
        try:
            return engine.answer(question, mode, doc_ids)
        except Exception as e:  # openai.APIStatusError, timeouts, ...
            msg = str(e)
            retryable = any(k in msg for k in ("503", "429", "overloaded", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                                                "timed out", "Timeout", "Connection"))
            if not retryable or attempt == tries - 1:
                raise
            print(f"    retry {attempt + 1}/{tries - 1} in {delay}s: {msg[:80]}")
            time.sleep(delay)
            delay = min(delay * 2, 60)


def error_cause(rec: dict) -> str:
    """Automatic first-pass grouping of failures (checked by hand in the notebook)."""
    if rec["refused"]:
        return "refusal" + ("_after_retrieval_miss" if not rec["gold_page_retrieved"] else "_despite_evidence")
    if "step limit" in rec["answer"]:
        return "agent_step_limit"
    if any(c.get("error") for c in rec["calculations"]) or "[calculation failed]" in rec["answer"]:
        return "calculation_tool_error"
    if not rec["gold_page_retrieved"]:
        return "retrieval_miss"
    if rec["grounding"] < 1:
        return "ungrounded_number (hallucination)"
    return "wrong_value_or_reasoning_with_evidence"


def run(modes, runs, limit, retriever_kind, scoped, judge_model, dataset="financebench"):
    if dataset == "psx":
        qs, store = load_psx(), build_psx_store()
    else:
        qs, store = load_financebench("test"), build_store(load_financebench("all"))
    qs = qs[:limit] if limit else qs
    retriever = build_retriever(store, retriever_kind)
    s = get_settings()
    llm = LLM()
    judge = Judge(judge_model, RESULTS / "judge_cache.json")
    engine = QAEngine(store, retriever, llm)
    print(f"model={s.llm_model} retriever={retriever_kind} questions={len(qs)} runs={runs}")
    for r in range(1, runs + 1):
        for mode in modes:
            out = RESULTS / f"qa{'' if dataset == 'financebench' else '_' + dataset}_{mode}_run{r}.jsonl"
            # resume: skip questions already answered; questions that failed with an
            # API error last time are tried again
            done = {r["id"] for r in map(json.loads, open(out)) if "error" not in r} if out.exists() else set()
            with open(out, "a") as f:
                for i, q in enumerate(qs, 1):
                    if q["id"] in done:
                        continue
                    try:
                        ans = answer_with_backoff(engine, q["question"], mode, [q["doc_name"]] if scoped else None)
                    except Exception as e:  # count API failures, do not crash the run
                        rec = {"id": q["id"], "mode": mode, "run": r, "error": str(e)[:300]}
                        f.write(json.dumps(rec) + "\n")
                        continue
                    rec = {"id": q["id"], "mode": mode, "run": r, "type": q["question_type"],
                           "question": q["question"], "gold": q["answer"], "answer": ans.answer,
                           "refused": ans.refused, "latency_s": ans.latency_s, "cost_usd": ans.cost_usd,
                           "tokens_in": ans.tokens_in, "tokens_out": ans.tokens_out, "steps": ans.steps,
                           "calculations": [c.model_dump() for c in ans.calculations],
                           "citations": [c.model_dump() for c in ans.citations],
                           "model": s.llm_model, "retriever": retriever_kind, "prompt_version": PROMPT_VERSION}
                    rec.update(grade(q, ans, store, judge))
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    if i % 10 == 0:
                        print(f"  run {r} {mode}: {i}/{len(qs)}")
    return summarise(modes, runs, dataset)


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    """Exact two-sided McNemar test on paired outcomes."""
    n01 = sum(1 for x, y in zip(a, b) if not x and y)
    n10 = sum(1 for x, y in zip(a, b) if x and not y)
    n = n01 + n10
    if n == 0:
        return {"a_only_correct": 0, "b_only_correct": 0, "p_value": 1.0}
    k = min(n01, n10)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"a_only_correct": n10, "b_only_correct": n01, "p_value": round(p, 4)}


def summarise(modes, runs, dataset="financebench") -> dict:
    tag = "" if dataset == "financebench" else "_" + dataset
    summary, majority = {}, {}
    for mode in modes:
        per_run, recs_all = [], []
        for r in range(1, runs + 1):
            path = RESULTS / f"qa{tag}_{mode}_run{r}.jsonl"
            if not path.exists():
                continue
            # keep the last record per question (a retried error is replaced by its success)
            last = {}
            for r in map(json.loads, open(path)):
                if "error" in r and r["id"] in last and "error" not in last[r["id"]]:
                    continue
                last[r["id"]] = r
            recs = list(last.values())
            ok = [x for x in recs if "error" not in x]
            graded = [x for x in ok if x["correct"] is not None]
            if not graded:
                continue
            per_run.append(sum(x["correct"] for x in graded) / len(graded))
            recs_all += [dict(x, _failed=False) for x in ok] + [dict(x, _failed=True) for x in recs if "error" in x]
        ok = [x for x in recs_all if not x["_failed"]]
        if not ok:
            continue
        graded = [x for x in ok if x["correct"] is not None]
        answered = [x for x in graded if not x["refused"]]
        lat = [x["latency_s"] for x in ok]
        calcs = [c for x in ok for c in x["calculations"]]
        failures = [x for x in graded if not x["correct"]]
        causes = Counter(error_cause(x) for x in failures)
        by_type = {}
        for t in ("metrics-generated", "domain-relevant", "novel-generated"):
            g = [x for x in graded if x["type"] == t]
            if g:
                by_type[t] = round(sum(x["correct"] for x in g) / len(g), 3)
        summary[mode] = {
            "runs": len(per_run),
            "accuracy_mean": round(statistics.mean(per_run), 3),
            "accuracy_std": round(statistics.pstdev(per_run), 3) if len(per_run) > 1 else 0.0,
            "accuracy_by_type": by_type,
            "numeric_accuracy": round(statistics.mean(x["correct"] for x in graded if x["method"] == "numeric"), 3)
            if any(x["method"] == "numeric" for x in graded) else None,
            "refusal_rate": round(statistics.mean(x["refused"] for x in ok), 3),
            "hallucination_rate": round(sum(1 for x in answered if not x["correct"] and x["grounding"] < 1)
                                        / max(1, len(answered)), 3),
            "grounding_mean": round(statistics.mean(x["grounding"] for x in ok), 3),
            "gold_page_retrieved": round(statistics.mean(x["gold_page_retrieved"] for x in ok), 3),
            "citation_correct": round(statistics.mean(x["gold_page_cited"] for x in ok), 3),
            "inline_page_mismatch_rate": round(statistics.mean(x.get("inline_page_mismatch", False) for x in ok), 3),
            "latency_p50_s": round(percentile(lat, .5), 2), "latency_p95_s": round(percentile(lat, .95), 2),
            "cost_per_request_usd": round(statistics.mean(x["cost_usd"] for x in ok), 5),
            "api_failure_rate": round(sum(x["_failed"] for x in recs_all) / len(recs_all), 3),
            "steps_mean": round(statistics.mean(x["steps"] for x in ok), 2),
            "tool_calls_per_task": round(len(calcs) / len(ok), 2),
            "calc_tool_success_rate": round(sum(1 for c in calcs if not c.get("error")) / len(calcs), 3) if calcs else None,
            "error_causes": dict(causes),
            "n_graded": len(graded), "judge_share": round(sum(x["method"] == "judge" for x in graded) / len(graded), 3),
        }
        # majority vote per question across runs, for the paired test
        votes: dict[str, list[bool]] = {}
        for x in graded:
            votes.setdefault(x["id"], []).append(bool(x["correct"]))
        majority[mode] = {k: sum(v) > len(v) / 2 for k, v in votes.items()}
        failures_out = [{k: x[k] for k in ("id", "type", "question", "gold", "answer", "grounding",
                                           "gold_page_retrieved")} | {"cause": error_cause(x)}
                        for x in failures]
        (RESULTS / f"qa{tag}_failures_{mode}.json").write_text(json.dumps(failures_out, indent=1))
    pairs = [("rag_direct", "rag_calc"), ("rag_direct", "agent"), ("rag_calc", "agent"), ("closed_book", "rag_direct")]
    tests = {}
    for a, b in pairs:
        if a in majority and b in majority:
            ids = sorted(set(majority[a]) & set(majority[b]))
            tests[f"{a}_vs_{b}"] = mcnemar([majority[a][i] for i in ids], [majority[b][i] for i in ids]) | {"n": len(ids)}
    summary["paired_tests"] = tests
    update_summary("qa" + tag, summary)
    for m, v in summary.items():
        if m != "paired_tests":
            print(f"{m:12s} acc={v['accuracy_mean']:.3f}±{v['accuracy_std']:.3f} halluc={v['hallucination_rate']:.3f} "
                  f"refuse={v['refusal_rate']:.3f} p50={v['latency_p50_s']}s cost=${v['cost_per_request_usd']}")
    print(json.dumps(tests, indent=1))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["closed_book", "rag_direct", "rag_calc", "agent"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retriever", default="bm25x", help="bm25x (no models) or hybridx+rerank")
    ap.add_argument("--scoped", action="store_true", help="restrict search to the question's filing")
    ap.add_argument("--judge-model", default=None, help="model for non-numeric answers (default: same as MIZAN_LLM_MODEL)")
    ap.add_argument("--dataset", choices=["financebench", "psx"], default="financebench")
    ap.add_argument("--summarise-only", action="store_true")
    a = ap.parse_args()
    if a.summarise_only:
        summarise(a.modes, a.runs, a.dataset)
    else:
        run(a.modes, a.runs, a.limit, a.retriever, a.scoped, a.judge_model or get_settings().llm_model, a.dataset)
