"""Shared data types (Pydantic). These are the contracts between components."""
from __future__ import annotations

from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Document(BaseModel):
    doc_id: str                       # e.g. "HBL_2025_annual" or "3M_2018_10K"
    company: str                      # display name
    symbol: str = ""                  # PSX ticker, e.g. "HBL"
    doc_type: str = "annual"          # annual | quarterly | half-yearly | other
    period: str = ""                  # e.g. "FY2025", "Q1FY2026"
    source_url: str = ""
    path: str = ""                    # local PDF path
    n_pages: int = 0
    added_at: datetime = Field(default_factory=_utcnow)


class Chunk(BaseModel):
    chunk_id: str                     # f"{doc_id}:p{page}:c{i}"
    doc_id: str
    company: str
    page: int                         # 1-based page number in the PDF
    kind: Literal["text", "table"] = "text"
    text: str


class Hit(BaseModel):
    chunk: Chunk
    score: float
    source: str = ""                  # which retriever produced it


class Citation(BaseModel):
    doc_id: str
    page: int
    quote: str = ""


class Calculation(BaseModel):
    expression: str
    variables: dict[str, float] = {}
    result: Optional[float] = None
    error: Optional[str] = None


class Answer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = []
    calculations: list[Calculation] = []
    context_pages: list[Citation] = []   # every page the system retrieved/read (for error analysis)
    reported_figures: list[dict] = []    # [{field, value, unit, statement, period, page}]
    calculated_values: list[dict] = []   # [{name, formula, operands, result}]
    explanation: str = ""                # only quoted report text with citations; else "The report does not state a reason."
    refusal_reason: Optional[str] = None
    basis: Optional[str] = None
    mode: str = "agent"
    steps: int = 0
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    refused: bool = False             # True when the system says it cannot answer


class FinancialFact(BaseModel):
    company: str
    symbol: str
    field: str
    period_end: str                   # YYYY-MM-DD
    period_type: str = "annual"       # annual | quarterly | half-yearly | nine-months | other
    months: int = 12
    basis: Literal["consolidated", "unconsolidated"] = "consolidated"
    value: float
    unit: str = "thousands"
    doc_id: str = ""
    page: Optional[int] = None
    source: Literal["label", "extraction"] = "extraction"
    conflict: bool = False
    labeller: str = ""


# --- structured extraction --------------------------------------------------

FIELDS = [
    "revenue", "gross_profit", "operating_profit", "profit_before_tax",
    "net_profit", "eps_basic", "total_assets", "total_liabilities", "total_equity",
]


class FieldValue(BaseModel):
    value: Optional[float] = None     # in the unit stated by `unit`
    page: Optional[int] = None
    label: str = ""                   # line item name as printed in the report


class FinancialHighlights(BaseModel):
    """What the extractor must return for one report. Values are AS PRINTED
    (e.g. in Rupees '000); normalisation to absolute rupees is done in code."""
    company: str = ""
    period_end: str = ""              # YYYY-MM-DD
    currency: str = "PKR"
    unit: Literal["units", "thousands", "millions", "billions"] = "thousands"
    consolidated: bool = False
    revenue: FieldValue = FieldValue()
    gross_profit: FieldValue = FieldValue()
    operating_profit: FieldValue = FieldValue()
    profit_before_tax: FieldValue = FieldValue()
    net_profit: FieldValue = FieldValue()
    eps_basic: FieldValue = FieldValue()      # EPS is never scaled by `unit`
    total_assets: FieldValue = FieldValue()
    total_liabilities: FieldValue = FieldValue()
    total_equity: FieldValue = FieldValue()


class Alert(BaseModel):
    symbol: str
    doc_id: str
    title: str
    summary: str
    created_at: datetime = Field(default_factory=_utcnow)
    channels: list[str] = []
