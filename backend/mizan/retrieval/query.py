"""Query understanding (deterministic, explainable):

1. expand_query  - finance glossary: adds the words filings actually use
                   ("capex" -> "purchases of property plant and equipment") and the
                   statement title when the question names a statement.
2. route_documents - reads company names, fiscal years and quarters from the question
                   and narrows the search to the matching filings (metadata filter).

Both are evaluated as ablations in eval/run_retrieval.py (bm25 vs bm25x vs routed).
"""
from __future__ import annotations

import re

from ..models import Document

GLOSSARY: dict[str, str] = {
    r"\bcapex\b|capital expenditure": "purchases of property plant and equipment additions to property capital expenditures",
    r"\brevenue|top line|sales\b": "revenue net sales total revenues turnover",
    r"net income|net profit|bottom line|profit after tax": "net income net earnings profit after taxation attributable",
    r"\bebitda\b": "operating income depreciation and amortization",
    r"operating (?:income|profit)|\bebit\b": "operating income operating profit income from operations",
    r"gross (?:margin|profit)": "gross profit cost of sales cost of goods sold",
    r"quick ratio|acid test": "cash and cash equivalents marketable securities accounts receivable total current liabilities",
    r"current ratio|working capital|liquidity": "total current assets total current liabilities",
    r"fixed asset turnover|pp&e|property, plant": "property plant and equipment net revenue",
    r"inventory turnover|days inventory|dio\b": "inventories cost of sales",
    r"receivable": "accounts receivable trade receivables net",
    r"payable": "accounts payable trade payables",
    r"dividend": "dividends paid cash dividends per share",
    r"debt|leverage|borrowing": "long-term debt short-term borrowings total debt notes payable",
    r"interest coverage|interest expense": "interest expense operating income",
    r"\beps\b|earnings per share": "earnings per share basic diluted",
    r"total assets|return on assets|\broa\b": "total assets",
    r"equity|return on equity|\broe\b": "total shareholders equity stockholders equity",
    r"free cash flow|\bfcf\b": "net cash provided by operating activities purchases of property plant and equipment",
    r"cash conversion|operating cash flow|cash from operations": "net cash provided by operating activities",
    r"effective tax|tax rate": "provision for income taxes income before income taxes effective tax rate",
    r"share repurchase|buyback": "repurchases of common stock treasury stock",
    r"segment": "segment results operating segments business segment",
    r"\bmarkup\b|interest income": "mark-up return interest earned net interest income",
}
STATEMENTS: dict[str, str] = {
    r"cash flow statement|statement of cash flows?|cash flows": "consolidated statement of cash flows",
    r"income statement|statement of (?:income|operations|earnings)|p&l|profit (?:and|or) loss":
        "consolidated statement of income operations profit or loss",
    r"balance sheet|statement of financial position": "consolidated balance sheet statement of financial position",
}


def expand_query(q: str) -> str:
    low = q.lower()
    extra = [words for pat, words in {**GLOSSARY, **STATEMENTS}.items() if re.search(pat, low)]
    return q + (" " + " ".join(extra) if extra else "")


_QTR = re.compile(r"\bq([1-4])\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def route_documents(q: str, docs: list[Document]) -> list[str] | None:
    """Return doc_ids whose company AND fiscal year match the question, or None if
    the question names no known company (then search everything)."""
    qn = _norm(q)
    by_company: dict[str, list[Document]] = {}
    for d in docs:
        names = {_norm(d.company), _norm(d.symbol), _norm(d.doc_id.split("_")[0])}
        names = {n for n in names if len(n) >= 2}
        # multi-word names: also try the first word if it is distinctive (e.g. "habib")
        first = _norm(d.company.split()[0]) if d.company.split() else ""
        if len(first) >= 5:
            names.add(first)
        if any(n and n in qn for n in names):
            by_company.setdefault(d.doc_id, []).append(d)
    cands = [d for lst in by_company.values() for d in lst]
    if not cands:
        return None
    years = set(re.findall(r"(?:fy\s?|\b)(20\d\d)\b", q.lower()))
    years |= {f"20{y}" for y in re.findall(r"\bfy\s?'?(\d\d)\b", q.lower())}
    if years:
        def doc_years(d: Document) -> set[str]:
            return set(re.findall(r"20\d\d", d.doc_id + " " + d.period))
        dated = [d for d in cands if doc_years(d) & years]
        # comparatives: FY2017 numbers are also in the FY2018/FY2019 filings
        later = [d for d in cands if any(str(int(y) + k) in doc_years(d) for y in years for k in (1, 2))]
        cands = dated or later or cands
        m = _QTR.search(q)
        if m and dated:
            qtr = [d for d in cands if f"q{m.group(1)}" in d.doc_id.lower()]
            cands = qtr or cands
        elif dated:
            annual = [d for d in cands if "10k" in d.doc_id.lower() or d.doc_type == "annual"]
            cands = annual or cands
    return sorted({d.doc_id for d in cands})


class ExpandedRetriever:
    """Wraps any retriever: applies glossary expansion and metadata routing."""

    def __init__(self, base, store, expand: bool = True, route: bool = True) -> None:
        self.base, self.store, self.expand, self.route = base, store, expand, route
        self.name = base.name + ("x" if expand else "") + ("+route" if route else "")

    def retrieve(self, query, k=6, doc_ids=None):
        scope = doc_ids
        if scope is None and self.route:
            scope = route_documents(query, self.store.list_documents())
        q = expand_query(query) if self.expand else query
        return self.base.retrieve(q, k, scope)
