"""Structured extraction of financial highlights from a report.

Pipeline (AI only where needed):
  1. locate_statement_pages  - deterministic keyword scoring finds the income
                               statement and balance sheet pages
  2. LLMExtractor            - LLM maps those pages to the FinancialHighlights
                               schema (JSON mode + Pydantic validation + retry)
     RuleExtractor           - regex baseline over the same pages (no AI)
  3. validate / normalise    - deterministic checks (A = L + E, sign of EPS,
                               unit scaling) done in code, never by the LLM

The three extractors (rule baseline, API LLM, local LLM) are compared in
eval/run_extraction.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..calculator import parse_number
from ..llm import LLM, Usage
from ..models import FIELDS, FieldValue, FinancialHighlights

# title patterns are matched on lower-case text with ALL whitespace removed, because
# PDF text often splits words ("Statement of Incom e", "Cash Flow s")
INCOME_TITLE = re.compile(r"statements?of(?:consolidated)?(?:income|operations|earnings|profitorloss|"
                          r"profitandloss)|incomestatements?|profitandlossaccount")
BALANCE_TITLE = re.compile(r"statements?of(?:consolidated)?financialposition|balancesheets?")
BAD_TITLE = re.compile(r"changesin(?:shareholders|stockholders)?'?equity|cashflows?|notesto|reportof"
                       r"independent|auditor|supplemental|selectedfinancial|parentcompany|guarantor|"
                       r"summarized|condensed(?:parent)")
LINE_HINTS = ["revenue", "sales", "gross profit", "operating profit", "profit before tax",
              "net income", "profit for the", "earnings per share", "total assets",
              "total liabilities", "total equity", "markup", "interest income"]


def locate_statement_pages(pages: dict[int, str], max_pages: int = 4) -> list[int]:
    """Deterministic: score every page by (statement title near the top) + (line-item
    hints) + (number density) - (prose). Returns the best income-statement pages
    and the best balance-sheet pages."""
    def score(text: str, title_re: re.Pattern) -> float:
        t = text.lower()
        head = re.sub(r"\s+", "", t[:400])
        title = 10 if title_re.search(head) else 0
        if title and BAD_TITLE.search(head[:head.find(title_re.search(head).group(0)) + 1]):
            title -= 6
        if "comprehensiveincome" in head and "profitorloss" not in head and "statementsofincome" not in head \
                and "statementofincome" not in head and title_re is INCOME_TITLE:
            title -= 6
        # PSX reports often contain BOTH unconsolidated and consolidated statements.
        # Prefer consolidated, so the income statement and balance sheet come from the
        # same set (otherwise the LLM sees a mix and rightly leaves fields empty).
        cons = 3 if title and re.search(r"(?<!un)consolidated", head) else 0
        hints = sum(1 for h in LINE_HINTS if h in t)
        nums = min(len(re.findall(r"\d[\d,]{3,}", t)), 60) / 10
        prose = len(re.findall(r"[a-z]{4,} [a-z]{4,} [a-z]{4,} [a-z]{4,}", t)) / 10
        return title + cons + hints + nums - prose

    def best(title_re: re.Pattern, n: int) -> list[int]:
        ranked = sorted(pages, key=lambda p: score(pages[p], title_re), reverse=True)
        top = ranked[:1]
        # statements often run over to the next page; include it if it is also numeric
        if top and n > 1 and top[0] + 1 in pages and len(re.findall(r"\d[\d,]{3,}", pages[top[0] + 1])) > 20:
            top.append(top[0] + 1)
        for p in ranked[1:]:
            if len(top) >= n:
                break
            if p not in top:
                top.append(p)
        return top

    half = max(1, max_pages // 2)
    return sorted(set(best(INCOME_TITLE, half) + best(BALANCE_TITLE, half)))


EXTRACT_PROMPT = """You extract figures from a company's financial statements.
From the pages below, fill this JSON for the CURRENT period only (not the comparative
column). Copy numbers exactly as printed (negative if in brackets), do not convert units.
If a field is not present, use null. `page` is the page number tag where you read it.
Prefer CONSOLIDATED statements if both are present and set "consolidated" accordingly.
For banks, revenue = total income (net markup/interest income + non-markup income).
Fields: revenue, gross_profit, operating_profit, profit_before_tax, net_profit
(profit after tax attributable to owners if shown), eps_basic, total_assets,
total_liabilities, total_equity.
JSON shape:
{"company": "", "period_end": "YYYY-MM-DD", "currency": "PKR", "unit": "units|thousands|millions|billions",
 "consolidated": true,
 "revenue": {"value": 123, "page": 10, "label": "Revenue from contracts with customers"},
 ... same for every field ...}"""


@dataclass
class ExtractionResult:
    highlights: FinancialHighlights | None
    pages_used: list[int]
    usage: Usage
    error: str | None = None
    warnings: list[str] | None = None


class LLMExtractor:
    name = "llm"

    def __init__(self, llm: LLM, name: str | None = None, fallback: bool = True) -> None:
        self.llm = llm
        self.name = name or f"llm:{llm.model}"
        # fallback=True (the app): if the LLM call fails, use the rule baseline instead
        # of crashing. fallback=False (the experiment): report the failure honestly so
        # the LLM's accuracy is not mixed up with the baseline's.
        self.fallback = fallback

    def extract(self, pages: dict[int, str], company_hint: str = "") -> ExtractionResult:
        use = locate_statement_pages(pages)
        body = "\n\n".join(f"=== page {p} ===\n{pages[p][:7000]}" for p in use)
        msgs = [{"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"Company: {company_hint}\n\n{body}"}]
        try:
            fh, usage, err = self.llm.structured(msgs, FinancialHighlights, retries=2)
        except Exception as e:  # API down (503), rate limit (429), bad key, timeout ...
            fh, usage, err = None, Usage(), f"LLM call failed: {type(e).__name__}: {str(e)[:200]}"
        if fh is None and self.fallback:
            res = RuleExtractor().extract(pages, company_hint)
            res.error = None
            res.warnings = [f"used rule baseline because the LLM failed ({err})"] + (res.warnings or [])
            return res
        warnings = validate(fh) if fh else []
        return ExtractionResult(fh, use, usage, err, warnings)


_RULES: dict[str, list[str]] = {
    "revenue": [r"^(?:net\s+)?(?:revenue|sales|turnover)s?\b(?! cost)", r"^total (?:net )?revenues?\b",
                r"^total income\b"],
    "gross_profit": [r"^gross (?:profit|margin)\b"],
    "operating_profit": [r"^(?:operating (?:profit|income))\b", r"^profit from operations\b"],
    "profit_before_tax": [r"^profit(?:\s*/?\s*\(?loss\)?)?\s+before\s+(?:income\s+)?tax", r"^income before income tax"],
    "net_profit": [r"^(?:net )?profit(?:\s*/?\s*\(?loss\)?)?\s+(?:after tax|for the (?:year|period))",
                   r"^net income\b", r"^net earnings\b"],
    "eps_basic": [r"^(?:basic\b.*earnings per share|earnings per share.*basic|basic and diluted)",
                  r"^earnings per share\b"],
    "total_assets": [r"^total assets\b"],
    "total_liabilities": [r"^total liabilities\b(?! and)"],
    "total_equity": [r"^total (?:shareholders'?|stockholders'?)?\s*equity\b(?! and)", r"^total equity\b"],
}
_NUM = re.compile(r"\(?-?[\d][\d,]*\.?\d*\)?")


class RuleExtractor:
    """Non-AI baseline: find the line item label, take the first number after it."""
    name = "rules"

    def extract(self, pages: dict[int, str], company_hint: str = "") -> ExtractionResult:
        use = locate_statement_pages(pages)
        fh = FinancialHighlights(company=company_hint)
        for field in FIELDS:
            for p in use:
                val = self._find(pages[p], _RULES[field])
                if val is not None:
                    setattr(fh, field, FieldValue(value=val, page=p, label=field))
                    break
        fh.unit = _guess_unit("\n".join(pages[p] for p in use))
        return ExtractionResult(fh, use, Usage(), None, validate(fh))

    @staticmethod
    def _find(text: str, patterns: list[str]) -> float | None:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            low = line.lower()
            m = next((re.search(p, low) for p in patterns if re.search(p, low)), None)
            if m:
                # numbers on the same line after the label, else on the next lines
                same_line = _NUM.findall(line[m.end():])
                look = same_line + [n for l in lines[i + 1:i + 4] for n in _NUM.findall(l)]
                for c in look:
                    v = parse_number(c)
                    # skip note references like "24" and years
                    if v is not None and not (float(v).is_integer() and (abs(v) < 100 or 1990 <= abs(v) <= 2035)):
                        return v
        return None


def _guess_unit(text: str) -> str:
    t = text.lower()
    if re.search(r"rupees? in (?:'?000|thousand)|rs\.? ?'?000|\(in thousands|in thousands", t):
        return "thousands"
    if re.search(r"in millions|\(millions\)|rs\.? in million|rupees in million|\$ ?millions", t):
        return "millions"
    if re.search(r"in billions", t):
        return "billions"
    return "units"


SCALE = {"units": 1, "thousands": 1e3, "millions": 1e6, "billions": 1e9}


def normalised(fh: FinancialHighlights) -> dict[str, float | None]:
    """Absolute values in currency units (EPS is never scaled)."""
    out = {}
    for f in FIELDS:
        v = getattr(fh, f).value
        out[f] = None if v is None else (v if f == "eps_basic" else v * SCALE[fh.unit])
    return out


def validate(fh: FinancialHighlights | None) -> list[str]:
    """Deterministic sanity checks. Returns human-readable warnings."""
    if fh is None:
        return ["no output"]
    w = []
    a, l, e = fh.total_assets.value, fh.total_liabilities.value, fh.total_equity.value
    if a and l is not None and e is not None and abs(a - (l + e)) > 0.02 * abs(a):
        w.append("total_assets != total_liabilities + total_equity (2% tolerance)")
    np_, pbt = fh.net_profit.value, fh.profit_before_tax.value
    if np_ is not None and pbt is not None and pbt > 0 and np_ > pbt * 1.05:
        w.append("net_profit greater than profit_before_tax")
    if fh.eps_basic.value is not None and np_ is not None and (fh.eps_basic.value > 0) != (np_ > 0):
        w.append("eps sign differs from net profit sign")
    return w
