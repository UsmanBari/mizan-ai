"""Shared helpers for the evaluation scripts.

Data
  FinanceBench open-source sample (Islam et al., 2023): 150 questions over 84 US
  filings with gold answers and gold evidence pages (evidence_page_num is 0-based,
  so the 1-based PDF page is evidence_page_num + 1).
  Split: 10 dev questions (prompt writing only) / 140 test questions.

  PSX set (ours): built from hand-labelled values, see build_psx_testset.py / build_psx_qa_v2.py.
"""
from __future__ import annotations

import csv
import json
import pickle
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mizan.ingest.pipeline import ingest_pdf  # noqa: E402
from mizan.store import MemoryStore, load_psx_labels  # noqa: E402

EVAL = ROOT / "eval"
DATA = EVAL / "data"
RESULTS = EVAL / "results"
CACHE = EVAL / ".cache"
RESULTS.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)


def load_financebench(split: str = "test") -> list[dict]:
    qs = [json.loads(l) for l in open(DATA / "financebench_open_source.jsonl", encoding="utf-8")]
    dev = set(json.load(open(DATA / "financebench_split.json", encoding="utf-8"))["dev_ids"])
    for q in qs:
        q["id"] = q["financebench_id"]
        q["gold_pages"] = sorted({(e["doc_name"], int(e["evidence_page_num"]) + 1) for e in q["evidence"]})
        q["split"] = "dev" if q["id"] in dev else "test"
    if split == "all":
        return qs
    return [q for q in qs if q["split"] == split]


def financebench_pdf_dir() -> Path:
    for cand in (DATA / "financebench_pdfs", ROOT.parent / "financebench" / "pdfs", Path("/tmp/fb/financebench/pdfs")):
        if cand.exists() and any(cand.glob("*.pdf")):
            return cand
    raise FileNotFoundError("FinanceBench PDFs not found. Run: python eval/download_financebench.py")


def build_store(questions: list[dict], cache_name: str = "financebench_store.pkl",
                find_tables: bool = False) -> MemoryStore:
    """Ingest every filing the questions refer to (cached on disk)."""
    cache = CACHE / cache_name
    if cache.exists():
        return pickle.load(open(cache, "rb"))
    pdfs = financebench_pdf_dir()
    store = MemoryStore()
    docs = sorted({q["doc_name"] for q in questions})
    t0 = time.time()
    for i, d in enumerate(docs, 1):
        company = d.split("_")[0].title()
        ingest_pdf(store, pdfs / f"{d}.pdf", d, company, find_tables=find_tables)
        if i % 10 == 0:
            print(f"  ingested {i}/{len(docs)} filings ({time.time() - t0:.0f}s)")
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(store, f)
    tmp.replace(cache)
    return store


# ------------------------------------------------------------------ scoring
_NUM = re.compile(r"\(?-?\$?\d[\d,]*\.?\d*\)?%?")


def numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(str(text)):
        s = m.replace("$", "").replace(",", "").replace("%", "")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            v = float(s)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def _years(v: float) -> bool:
    return float(v).is_integer() and 1990 <= v <= 2035


def numeric_match(pred: str, gold: str, rel_tol: float = 0.01) -> dict:
    """FinanceBench-style numeric check. The gold answer's main number (first non-year
    number) must appear in the prediction within 1% relative tolerance (or 0.1 absolute
    for small values like percentages / ratios). A match after rescaling by 1e3/1e6
    (e.g. '1.58 billion' vs '1577 million') counts as correct but is tagged
    'scale' so unit mistakes are visible in error analysis."""
    g = [x for x in numbers(gold) if not _years(x)]
    if not g:
        return {"numeric": False, "correct": None, "scale": False}
    target = g[0]
    preds = [x for x in numbers(pred) if not _years(x)]
    for p in preds:
        for scale in (1, 1e3, 1e-3, 1e6, 1e-6, 100, 0.01):
            v = p * scale
            if abs(v - target) <= max(rel_tol * abs(target), 0.1 if abs(target) < 100 else 0) or \
               abs(abs(v) - abs(target)) <= rel_tol * abs(target):
                return {"numeric": True, "correct": True, "scale": scale != 1}
    return {"numeric": True, "correct": False, "scale": False}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def save_json(obj, name: str) -> Path:
    path = RESULTS / name
    path.write_text(json.dumps(obj, indent=2, default=str))
    return path


def update_summary(section: str, payload: dict) -> None:
    path = RESULTS / "summary.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[section] = payload
    path.write_text(json.dumps(data, indent=2, default=str))


def load_psx() -> list[dict]:
    """PSX QA set built by build_psx_testset.py (all of it is test data)."""
    path = DATA / "psx_qa.jsonl"
    if not path.exists():
        raise FileNotFoundError("run eval/build_psx_testset.py after labelling")
    qs = [json.loads(l) for l in open(path, encoding="utf-8")]
    for q in qs:
        q["split"] = "test"
        q["gold_pages"] = [tuple(p) for p in q["gold_pages"]]
    return qs


def load_psx_v2() -> list[dict]:
    """PSX QA v2 benchmark built by build_psx_qa_v2.py (with stage gold + unanswerables)."""
    path = DATA / "psx_qa_v2.jsonl"
    if not path.exists():
        raise FileNotFoundError("run eval/build_psx_qa_v2.py first")
    qs = [json.loads(l) for l in open(path, encoding="utf-8")]
    for q in qs:
        q["split"] = "test"
        q["gold_pages"] = [tuple(p) for p in q.get("gold_pages", [])]
    return qs


def build_psx_store(cache_name: str = "psx_store.pkl") -> MemoryStore:
    """Ingest verified PSX filings and load verified facts from psx_labels.csv (cached)."""
    cache = CACHE / cache_name
    if cache.exists():
        store = pickle.load(open(cache, "rb"))
        if not store.get_facts():
            load_psx_labels(store)
        return store

    docs_meta: dict[str, dict] = {}
    with open(DATA / "psx_labels.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["doc_id"].startswith("EXAMPLE"):
                continue
            if (r.get("labeller") or "").strip().lower() in ("", "claude-draft"):
                continue
            docs_meta[r["doc_id"]] = {"company": r["company"], "symbol": r["symbol"]}

    store = MemoryStore()
    for doc_id, m in sorted(docs_meta.items()):
        pdf = DATA / "psx_pdfs" / f"{doc_id}.pdf"
        if pdf.exists():
            ingest_pdf(store, pdf, doc_id, m["company"], m["symbol"], "annual", doc_id.split("_")[-1])
    load_psx_labels(store)

    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(store, f)
    tmp.replace(cache)
    return store
