"""Watchlist automation: detect new PSX results -> ingest -> extract -> alert.

Division of labour:
  deterministic code : polling, downloading, comparing with the previous report,
                       computing % changes, deciding whether to alert
  AI                 : extracting the figures (LLMExtractor) and writing a short,
                       plain-English summary FROM the computed numbers only
"""
from __future__ import annotations

import logging
from html import escape

from ..calculator import calculate
from ..llm import LLM
from ..models import Alert, FinancialHighlights
from ..store import Store
from .notify import send_email, send_telegram

log = logging.getLogger(__name__)

KEY_FIELDS = [("revenue", "Revenue"), ("net_profit", "Net profit"), ("eps_basic", "EPS"),
              ("total_assets", "Total assets")]


def compute_changes(new: FinancialHighlights, old: FinancialHighlights | None) -> list[dict]:
    rows = []
    for f, label in KEY_FIELDS:
        nv = getattr(new, f).value
        ov = getattr(old, f).value if old else None
        row = {"field": label, "new": nv, "old": ov, "change_pct": None}
        if nv is not None and ov not in (None, 0):
            row["change_pct"] = calculate("pct_change(new, old)", {"new": nv, "old": ov}).result
        rows.append(row)
    return rows


SUMMARY_PROMPT = """Write a 3-sentence plain-English alert for an investor about new financial
results. Use ONLY the numbers given (already computed); do not calculate anything,
do not give investment advice. Mention the period and the unit."""


def summarise(llm: LLM | None, company: str, period: str, unit: str, rows: list[dict]) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v:+.1f}%"

    def num(v):
        return "n/a" if v is None else f"{v:,.2f}".rstrip("0").rstrip(".")
    facts = "\n".join(f"- {r['field']}: {num(r['new'])} (previous {num(r['old'])}; change {pct(r['change_pct'])})"
                      for r in rows)
    if llm is None:
        return f"{company} published results for {period} (figures in {unit}):\n{facts}"
    reply = llm.chat([{"role": "system", "content": SUMMARY_PROMPT},
                      {"role": "user", "content": f"{company}, {period}, unit: {unit}\n{facts}"}],
                     max_tokens=250)
    return reply.content.strip() + f"\n\n{facts}"


def process_new_document(store: Store, doc_id: str, extractor, llm: LLM | None) -> Alert | None:
    doc = store.get_document(doc_id)
    if doc is None:
        return None
    pages = {p: store.get_page(doc_id, p) or "" for p in range(1, doc.n_pages + 1)}
    res = extractor.extract(pages, doc.company)
    if res.highlights is None:
        log.warning("extraction failed for %s: %s", doc_id, res.error)
        return None
    store.save_financials(doc_id, res.highlights)
    previous = [d for d in store.list_documents(doc.symbol)
                if d.doc_id != doc_id and d.doc_type == doc.doc_type and store.get_financials(d.doc_id)]
    previous.sort(key=lambda d: d.added_at, reverse=True)
    old = store.get_financials(previous[0].doc_id) if previous else None
    rows = compute_changes(res.highlights, old)
    summary = summarise(llm, doc.company, doc.period or doc.doc_type, res.highlights.unit, rows)
    alert = Alert(symbol=doc.symbol, doc_id=doc_id, title=f"{doc.symbol}: new {doc.doc_type} results",
                  summary=summary)
    for w in store.watchlist():
        if w["symbol"] != doc.symbol:
            continue
        if w.get("chat_id") and send_telegram(w["chat_id"], f"<b>{escape(alert.title)}</b>\n{escape(summary)}"):
            alert.channels.append("telegram")
        if w.get("email") and send_email(w["email"], alert.title, summary):
            alert.channels.append("email")
    store.add_alert(alert)
    return alert


def poll_watchlist(store: Store, extractor, llm: LLM | None) -> list[Alert]:
    """Called by the scheduler. For every watched symbol, ingest unseen reports and alert."""
    from ..ingest.pipeline import ingest_psx_symbol
    alerts = []
    for w in store.watchlist():
        try:
            for doc in ingest_psx_symbol(store, w["symbol"], limit=2, only_unseen=True):
                a = process_new_document(store, doc.doc_id, extractor, llm)
                if a:
                    alerts.append(a)
        except Exception as e:
            log.exception("poll failed for %s: %s", w["symbol"], e)
    return alerts
