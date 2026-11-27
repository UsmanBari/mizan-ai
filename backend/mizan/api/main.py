"""FastAPI backend.

Run:  uvicorn mizan.api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import shutil
import statistics
import uuid
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..agent.engine import (
    MODES,
    _facts_to_values_by_period,
    _fields_for_ratio,
    format_conflict_message,
    grounding_check,
    number_evidence,
    resolve_basis_for_symbol,
)
from ..config import get_settings
from ..ingest.pipeline import ingest_pdf, ingest_psx_symbol
from ..models import Answer
from ..ratios import canonical_ratio_name, compute as compute_ratio
from ..services import get_engine, get_extractor, get_llm, get_retriever, reset_retriever
from ..store import get_store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Mizan AI", version="0.4.0",
              description="Agentic analyst for Pakistan Stock Exchange filings")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Highlight-Hits", "X-Highlight-Y"])


class AskRequest(BaseModel):
    question: str
    mode: str = "agent"
    doc_ids: Optional[list[str]] = None


class AskResponse(Answer):
    grounding: float = 1.0
    evidence: list[dict] = []   # per-number provenance for the UI (found / computed / unverified)


class WatchRequest(BaseModel):
    symbol: str
    telegram_chat_id: str = ""
    email: str = ""


def _compute_metric_cell(store, symbol: str, metric: str, period_end: Optional[str], basis: Optional[str]) -> dict:
    """Evaluate one cell (raw field or ratio) from facts store + ratios.py only (zero LLM)."""
    sym = symbol.upper().strip()
    sym_basis = resolve_basis_for_symbol(store, sym, requested=basis, period=period_end)
    all_facts = store.get_facts(symbol=sym, basis=sym_basis) if sym_basis else store.get_facts(symbol=sym)
    if not all_facts:
        return {
            "symbol": sym,
            "metric": metric,
            "period_end": period_end,
            "basis": sym_basis,
            "value": None,
            "doc_id": None,
            "page": None,
            "refused": True,
            "reason": f"No verified facts found for {sym}" + (f" ({sym_basis})" if sym_basis else ""),
        }

    if period_end is None:
        annual_ends = sorted({f.period_end for f in all_facts if f.period_type == "annual"})
        target_end = annual_ends[-1] if annual_ends else sorted({f.period_end for f in all_facts})[-1]
    else:
        target_end = period_end

    canon = canonical_ratio_name(metric)
    if canon is None:
        # Raw field lookup
        matches = [f for f in all_facts if f.field == metric and f.period_end == target_end]
        if not matches:
            return {
                "symbol": sym,
                "metric": metric,
                "period_end": target_end,
                "basis": sym_basis,
                "value": None,
                "doc_id": None,
                "page": None,
                "refused": True,
                "reason": f"Missing field '{metric}' for {sym} at {target_end}",
            }
        conflicts = store.fact_conflicts(symbol=sym, field=metric, period_end=target_end, basis=sym_basis)
        if conflicts:
            return {
                "symbol": sym,
                "metric": metric,
                "period_end": target_end,
                "basis": sym_basis,
                "value": None,
                "doc_id": matches[0].doc_id,
                "page": matches[0].page,
                "conflict": True,
                "values": conflicts[0]["values"],
                "refused": True,
                "reason": format_conflict_message(conflicts),
            }
        chosen = next((f for f in matches if f.source == "label"), matches[0])
        return {
            "symbol": sym,
            "metric": metric,
            "period_end": chosen.period_end,
            "period_type": chosen.period_type,
            "months": chosen.months,
            "basis": chosen.basis,
            "value": chosen.value,
            "unit": chosen.unit,
            "doc_id": chosen.doc_id,
            "page": chosen.page,
            "source": chosen.source,
            "refused": False,
        }

    # Ratio / growth computation restricted to target_end and prior periods of matching type
    target_facts = [f for f in all_facts if f.period_end == target_end]
    if not target_facts:
        return {
            "symbol": sym,
            "metric": canon,
            "period_end": target_end,
            "basis": sym_basis,
            "value": None,
            "doc_id": None,
            "page": None,
            "refused": True,
            "reason": f"No facts found for {sym} at period {target_end}",
        }
    ptypes = {f.period_type for f in target_facts}
    scoped = [f for f in all_facts if f.period_end <= target_end and (len(ptypes) > 1 or f.period_type in ptypes)]

    rel_fields = set(_fields_for_ratio(canon))
    conflicts = [
        c for c in store.fact_conflicts(symbol=sym, basis=sym_basis)
        if c["field"] in rel_fields and c["period_end"] in {f.period_end for f in scoped}
    ]
    if conflicts:
        return {
            "symbol": sym,
            "metric": canon,
            "period_end": target_end,
            "basis": sym_basis,
            "value": None,
            "doc_id": conflicts[0]["values"][0].get("doc_id"),
            "page": conflicts[0]["values"][0].get("page"),
            "conflict": True,
            "conflicts": conflicts,
            "refused": True,
            "reason": format_conflict_message(conflicts),
        }

    res = compute_ratio(canon, _facts_to_values_by_period(scoped))
    if res.get("refused"):
        ops = res.get("operands", [])
        return {
            "symbol": sym,
            "metric": canon,
            "period_end": target_end,
            "basis": sym_basis,
            "value": None,
            "change_amount": res.get("change_amount"),
            "change_unit": res.get("change_unit"),
            "formula": res.get("formula"),
            "operands": ops,
            "doc_id": ops[0]["doc_id"] if ops else None,
            "page": ops[0]["page"] if ops else None,
            "refused": True,
            "reason": res["reason"],
        }
    ops = res["operands"]
    return {
        "symbol": sym,
        "metric": canon,
        "period_end": target_end,
        "basis": res.get("basis") or sym_basis,
        "value": res["value"],
        "unit": res["unit"],
        "formula": res["formula"],
        "operands": ops,
        "doc_id": ops[0]["doc_id"] if ops else None,
        "page": ops[0]["page"] if ops else None,
        "refused": False,
    }


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "store": "memory" if s.database_url == "memory" else "postgres",
            "llm": s.llm_model if get_llm() else None, "documents": len(get_store().list_documents())}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if req.mode not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    if len(req.question) > 1000:
        raise HTTPException(400, "question too long")
    try:
        engine = get_engine()
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    ans = engine.answer(req.question, req.mode, req.doc_ids)
    store = get_store()
    return AskResponse(**ans.model_dump(), grounding=round(grounding_check(ans, store), 3),
                       evidence=number_evidence(ans, store))


@app.get("/facts/{symbol}")
def facts(
    symbol: str,
    period_end: Optional[str] = None,
    basis: Optional[str] = None,
    field: Optional[str] = None,
):
    store = get_store()
    rows = store.get_facts(symbol=symbol, field=field, period_end=period_end, basis=basis)
    if not rows:
        raise HTTPException(404, f"no verified facts found for {symbol.upper()}")
    return {
        "symbol": symbol.upper(),
        "company": rows[0].company,
        "facts": [f.model_dump() for f in rows],
        "conflicts": store.fact_conflicts(symbol=symbol, field=field, period_end=period_end, basis=basis),
    }


@app.get("/compare")
def compare(
    symbols: str,
    period_end: Optional[str] = None,
    metrics: str = "revenue,net_profit,net_margin,roe",
    basis: Optional[str] = None,
):
    store = get_store()
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    if not sym_list:
        raise HTTPException(400, "at least one symbol is required")
    if not metric_list:
        raise HTTPException(400, "at least one metric is required")

    rows, table = [], {}
    for sym in sym_list:
        table[sym] = {}
        for m in metric_list:
            cell = _compute_metric_cell(store, sym, m, period_end, basis)
            rows.append(cell)
            table[sym][m] = cell
    return {
        "period_end": period_end,
        "symbols": sym_list,
        "metrics": metric_list,
        "rows": rows,
        "table": table,
    }


@app.get("/trends/{symbol}")
def trends(
    symbol: str,
    metrics: str = "revenue,net_profit,net_margin,revenue_growth",
    basis: Optional[str] = None,
):
    store = get_store()
    sym = symbol.upper().strip()
    sym_basis = resolve_basis_for_symbol(store, sym, requested=basis)
    sym_facts = store.get_facts(symbol=sym, basis=sym_basis) if sym_basis else store.get_facts(symbol=sym)
    if not sym_facts:
        raise HTTPException(404, f"no verified facts found for {sym}")
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    if not metric_list:
        raise HTTPException(400, "at least one metric is required")

    periods = sorted({f.period_end for f in sym_facts})
    series = {}
    for p in periods:
        series[p] = {m: _compute_metric_cell(store, sym, m, p, sym_basis) for m in metric_list}
    return {
        "symbol": sym,
        "company": sym_facts[0].company,
        "basis": sym_basis,
        "metrics": metric_list,
        "periods": periods,
        "series": series,
    }


@app.get("/documents")
def documents(symbol: Optional[str] = None):
    return [d.model_dump() for d in get_store().list_documents(symbol)]


@app.get("/documents/{doc_id}/pages/{page}")
def page(doc_id: str, page: int):
    text = get_store().get_page(doc_id, page)
    if text is None:
        raise HTTPException(404, "page not found")
    return {"doc_id": doc_id, "page": page, "text": text}


@app.get("/documents/{doc_id}/pages/{page}/image")
def page_image(doc_id: str, page: int, highlight: str = "", dpi: int = 110):
    """The real PDF page as a PNG, with every occurrence of `highlight` boxed."""
    import pymupdf
    doc = get_store().get_document(doc_id)
    if doc is None or not doc.path or not Path(doc.path).exists():
        raise HTTPException(404, "PDF file not available for this document")
    with pymupdf.open(doc.path) as pdf:
        if not 1 <= page <= len(pdf):
            raise HTTPException(404, "page not found")
        pg = pdf[page - 1]
        hits = pg.search_for(highlight) if highlight.strip() else []
        for r in hits:
            box = pymupdf.Rect(r.x0 - 3, r.y0 - 2, r.x1 + 3, r.y1 + 2)
            pg.draw_rect(box, color=(0.043, 0.478, 0.333), fill=(0.043, 0.478, 0.333),
                         fill_opacity=0.15, width=1.6)
        png = pg.get_pixmap(dpi=max(60, min(dpi, 200))).tobytes("png")
        y = f"{hits[0].y0 / pg.rect.height:.4f}" if hits else ""
    return Response(png, media_type="image/png",
                    headers={"X-Highlight-Hits": str(len(hits)), "X-Highlight-Y": y,
                             "Cache-Control": "max-age=600"})


def _post_ingest(doc_id: str, extract: bool):
    reset_retriever()
    get_retriever()
    if extract:
        store = get_store()
        doc = store.get_document(doc_id)
        pages = {p: store.get_page(doc_id, p) or "" for p in range(1, doc.n_pages + 1)}
        res = get_extractor().extract(pages, doc.company)
        if res.highlights:
            store.save_financials(doc_id, res.highlights)


@app.post("/documents/upload")
async def upload(bg: BackgroundTasks, file: UploadFile = File(...), company: str = Form(...),
                 symbol: str = Form(""), period: str = Form(""), doc_type: str = Form("annual"),
                 extract: bool = Form(True)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "only PDF files are accepted")
    s = get_settings()
    dest = Path(s.data_dir) / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    doc_id = f"{(symbol or company)[:12].upper().replace(' ', '')}_{period or 'X'}_{uuid.uuid4().hex[:6]}"
    path = dest / f"{doc_id}.pdf"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    doc = ingest_pdf(get_store(), path, doc_id, company, symbol.upper(), doc_type, period)
    bg.add_task(_post_ingest, doc_id, extract)
    return doc.model_dump()


@app.post("/ingest/psx/{symbol}")
def ingest_psx(symbol: str, bg: BackgroundTasks, limit: int = 2, company: str = ""):
    try:
        docs = ingest_psx_symbol(get_store(), symbol, company, limit)
    except Exception as e:
        raise HTTPException(502, f"PSX fetch failed: {e}")
    for d in docs:
        bg.add_task(_post_ingest, d.doc_id, True)
    return [d.model_dump() for d in docs]


@app.get("/financials/{doc_id}")
def financials(doc_id: str):
    from ..extraction.extractor import normalised, validate
    fh = get_store().get_financials(doc_id)
    if fh is None:
        raise HTTPException(404, "no extracted financials yet")
    return {"highlights": fh.model_dump(), "absolute": normalised(fh), "warnings": validate(fh)}


@app.post("/financials/{doc_id}/extract")
def extract_now(doc_id: str):
    store = get_store()
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "unknown document")
    pages = {p: store.get_page(doc_id, p) or "" for p in range(1, doc.n_pages + 1)}
    res = get_extractor().extract(pages, doc.company)
    if res.highlights is None:
        raise HTTPException(502, f"extraction failed: {res.error}")
    store.save_financials(doc_id, res.highlights)
    return financials(doc_id)


@app.post("/watchlist")
def watch(req: WatchRequest):
    get_store().watch(req.symbol, req.telegram_chat_id, req.email)
    return get_store().watchlist()


@app.get("/watchlist")
def watchlist():
    return get_store().watchlist()


@app.post("/alerts/run")
def run_alerts():
    from ..alerts.watcher import poll_watchlist
    return [a.model_dump() for a in poll_watchlist(get_store(), get_extractor(), get_llm())]


@app.post("/alerts/test/{doc_id}")
def alert_for_doc(doc_id: str):
    from ..alerts.watcher import process_new_document
    a = process_new_document(get_store(), doc_id, get_extractor(), get_llm())
    if a is None:
        raise HTTPException(404, "document not found or extraction failed")
    return a.model_dump()


@app.get("/alerts")
def alerts():
    return [a.model_dump() for a in get_store().alerts()]


@app.get("/metrics")
def metrics():
    """Live system metrics from the answer log (latency p50/p95, cost, refusal rate)."""
    log = get_store().answer_log()
    if not log:
        return {"requests": 0}
    lat = sorted(a.latency_s for a in log)
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]
    by_mode = {}
    for a in log:
        by_mode.setdefault(a.mode, []).append(a)
    return {"requests": len(log), "latency_p50_s": p(0.5), "latency_p95_s": p(0.95),
            "mean_cost_usd": statistics.mean(a.cost_usd for a in log),
            "refusal_rate": sum(a.refused for a in log) / len(log),
            "by_mode": {m: {"n": len(v), "mean_latency_s": statistics.mean(x.latency_s for x in v),
                            "mean_steps": statistics.mean(x.steps for x in v)} for m, v in by_mode.items()}}


@app.get("/eval/summary")
def eval_summary():
    """Serves eval/results/summary.json so the frontend can show the results dashboard."""
    import json
    repo = Path(__file__).resolve().parents[3]
    for cand in (repo / "eval/results/summary.json", Path("eval/results/summary.json"),
                 Path("/app/eval/results/summary.json")):
        if cand.exists():
            return json.loads(cand.read_text())
    raise HTTPException(404, "run the evaluation scripts first")
