# Notes for Burhan (API Contracts & Integration Notes)

This document describes the new deterministic endpoints and updated `/ask` response shape added in Revision v2.0 so you can wire up the frontend Compare, Trends, Facts, and Three-Part Answer views without touching backend retrieval/agent logic.

---

## 1. Updated `POST /ask` Response Shape (`AskResponse`)

`POST /ask` returns all existing `Answer` fields (`answer`, `citations`, `calculations`, `context_pages`, `grounding`, `evidence`, `mode`, `steps`, `latency_s`, `tokens_in`, `tokens_out`, `cost_usd`, `refused`), plus the new structured fields:

```json
{
  "question": "What was HUBC's net profit margin in FY2026?",
  "answer": "HUBC's consolidated net margin for FY2026 was 69.78%.",
  "basis": "consolidated",
  "refused": false,
  "refusal_reason": null,
  "reported_figures": [
    {
      "field": "net_profit",
      "value": 49630724.0,
      "unit": "thousands",
      "statement": "Consolidated Statement of Profit or Loss",
      "period": "2026-06-30",
      "page": 275
    },
    {
      "field": "revenue",
      "value": 71126352.0,
      "unit": "thousands",
      "statement": "Consolidated Statement of Profit or Loss",
      "period": "2026-06-30",
      "page": 275
    }
  ],
  "calculated_values": [
    {
      "name": "net_margin",
      "formula": "net_profit / revenue * 100",
      "operands": [
        {"field": "net_profit", "period": "2026-06-30", "value": 49630724.0, "doc_id": "HUBC_FY2026", "page": 275, "basis": "consolidated"},
        {"field": "revenue", "period": "2026-06-30", "value": 71126352.0, "doc_id": "HUBC_FY2026", "page": 275, "basis": "consolidated"}
      ],
      "result": 69.7783
    }
  ],
  "explanation": "The report does not state a reason.",
  "citations": [{"doc_id": "HUBC_FY2026", "page": 275, "quote": ""}],
  "calculations": [...],
  "grounding": 1.0,
  "evidence": [...]
}
```

When an answer is deterministically refused (missing operand, period mismatch, or conflicting values > 0.5%):
- `"refused": true`
- `"refusal_reason": "..."` (human-readable reason, including both values and pages when a conflict occurred).
- `explanation` defaults to `"The report does not state a reason."` unless verbatim quoted text from a cited/retrieved page is present.

---

## 2. `GET /facts/{symbol}`

Optional query parameters: `period_end` (`YYYY-MM-DD`), `basis` (`consolidated` | `unconsolidated`), `field`.
Returns `404` if no facts exist for that symbol.

```json
{
  "symbol": "HUBC",
  "company": "The Hub Power Company Limited",
  "facts": [
    {
      "company": "The Hub Power Company Limited",
      "symbol": "HUBC",
      "field": "revenue",
      "period_end": "2026-06-30",
      "period_type": "annual",
      "months": 12,
      "basis": "consolidated",
      "value": 71126352.0,
      "unit": "thousands",
      "doc_id": "HUBC_FY2026",
      "page": 275,
      "source": "label",
      "conflict": false,
      "labeller": "usman"
    }
  ],
  "conflicts": []
}
```

---

## 3. `GET /compare`

Compare multiple companies using ONLY verified facts and `ratios.py` (no LLM).

Query parameters:
- `symbols`: comma-separated tickers (e.g. `LUCK,HUBC,PIOC`) — required
- `period_end`: `YYYY-MM-DD` (optional; defaults to each company's latest period)
- `metrics`: comma-separated raw fields or ratio names (default: `revenue,net_profit,net_margin,roe`)
- `basis`: `consolidated` | `unconsolidated` (optional; defaults per symbol to consolidated if available, else unconsolidated)

Example response (`GET /compare?symbols=LUCK,HUBC&period_end=2026-06-30&metrics=revenue,net_margin`):
```json
{
  "period_end": "2026-06-30",
  "symbols": ["LUCK", "HUBC"],
  "metrics": ["revenue", "net_margin"],
  "rows": [
    {
      "symbol": "LUCK",
      "metric": "revenue",
      "period_end": "2026-06-30",
      "period_type": "annual",
      "months": 12,
      "basis": "consolidated",
      "value": 516358811.0,
      "unit": "thousands",
      "doc_id": "LUCK_FY2026",
      "page": 289,
      "source": "label",
      "refused": false
    },
    {
      "symbol": "LUCK",
      "metric": "net_margin",
      "period_end": "2026-06-30",
      "basis": "consolidated",
      "value": 17.2442,
      "unit": "%",
      "formula": "net_profit / revenue * 100",
      "operands": [...],
      "doc_id": "LUCK_FY2026",
      "page": 289,
      "refused": false
    }
  ],
  "table": {
    "LUCK": { "revenue": {...}, "net_margin": {...} },
    "HUBC": { "revenue": {...}, "net_margin": {...} }
  }
}
```
Notice every cell carries `doc_id` and `page` (for click-to-highlight PDF preview), and if a metric is missing / has growth base <= 0 / has conflicting facts, `refused: true` and `reason` are returned cleanly on that cell.

---

## 4. `GET /trends/{symbol}`

Chronological time-series from the facts store + `ratios.py` (no LLM). Returns `404` if symbol has no facts.

Query parameters:
- `metrics`: comma-separated metrics (default: `revenue,net_profit,net_margin,revenue_growth`)
- `basis`: optional basis override

Example response (`GET /trends/HUBC?metrics=revenue,net_margin,revenue_growth`):
```json
{
  "symbol": "HUBC",
  "company": "The Hub Power Company Limited",
  "basis": "consolidated",
  "metrics": ["revenue", "net_margin", "revenue_growth"],
  "periods": ["2025-06-30", "2026-06-30"],
  "series": {
    "2025-06-30": {
      "revenue": {"symbol": "HUBC", "metric": "revenue", "period_end": "2025-06-30", "value": 83351492.0, "unit": "thousands", "doc_id": "HUBC_FY2026", "page": 275, "refused": false},
      "net_margin": {"symbol": "HUBC", "metric": "net_margin", "period_end": "2025-06-30", "value": 55.3454, "unit": "%", "doc_id": "HUBC_FY2026", "page": 275, "refused": false},
      "revenue_growth": {"symbol": "HUBC", "metric": "revenue_growth", "period_end": "2025-06-30", "value": null, "refused": true, "reason": "Ratio 'revenue_growth' requires 2 periods (current and prior), but only 1 period(s) provided."}
    },
    "2026-06-30": { ... }
  }
}
```

---

## 5. Notes on Extractor / Ingestion Improvements You Own

- `backend/mizan/store.py` already converts `FinancialHighlights` passed to `store.save_financials(doc_id, fh)` into `FinancialFact` rows and persists `data/store.pkl` automatically on every `add_document` / `save_financials`.
- When you expand `extraction/extractor.py` with the extra fields (`cost_of_sales`, `gross_profit`, `operating_profit`, `finance_cost`, `current_assets`, `current_liabilities`), remember `models.FIELDS` currently has the original 9 fields — once your parser populates `FinancialHighlights` or calls `store.add_facts(...)`, `ratios.py` (`gross_margin`, `operating_margin`, `current_ratio`, `interest_coverage`) and `/compare` + `/trends` will pick them up automatically.
- Make sure quarterly/half-yearly ingestion sets `doc.doc_type` cleanly (`quarterly`, `half-yearly`, `annual`) so `months` (3/6/12) is tagged accurately and `ratios.py` continues refusing cross-frequency comparisons.
