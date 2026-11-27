"""Reporting-period and statement-basis metadata (deterministic, no AI).

Why: a quarterly figure must never be compared with an annual one, and a
consolidated figure must never be mixed with an unconsolidated one. So every
document gets

  period_type     annual | half-yearly | quarterly | nine-months  (same names as store.py)
  period_end      YYYY-MM-DD
  months_covered  12 | 9 | 6 | 3 | None

read from the filing TITLE and checked against the date printed in the
statement HEADERS ("For the nine months period ended March 31, 2026"). If the two
disagree, the statements win and a warning is kept on the document.

Every statement page is also tagged with what it is (income / balance /
comprehensive / cash_flow / equity) and its basis (consolidated /
unconsolidated), read from the page title.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|" \
       r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
_DATE = (rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON}\s*,?\s*(\d{{4}})"      # 30 June 2026 / 30th June, 2026
         rf"|{_MON}\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})"          # June 30, 2026
         r"|(\d{1,2})[./-](\d{1,2})[./-](\d{4}))")                         # 30.06.2026
DATE_RE = re.compile(_DATE, re.I)
# "for the nine months period ended", "first quarter ended", "half year ended", "year ended"
_SPAN = (r"(year|twelve months|12 months|half[\s-]*year(?:ly)?|six months|6 months|nine months|9 months|"
         r"three months|3 months|(?:first|second|third|1st|2nd|3rd)\s+quarter|quarter)")
PERIOD_RE = re.compile(rf"{_SPAN}\s*(?:period\s*)?(?:ended|ending|end)\s*(?:on\s*)?(?:the\s*)?{_DATE}", re.I)
AS_AT_RE = re.compile(rf"as\s*(?:at|of|on)\s*{_DATE}", re.I)


@dataclass
class Period:
    period_type: str = ""          # annual | half-yearly | quarterly | other | ""
    period_end: str = ""           # YYYY-MM-DD
    months_covered: int | None = None
    source: str = ""               # title | statements


def parse_date(m: re.Match) -> str:
    g = m.groups()
    # the date groups are the last 9 groups of either regex
    d1, mon1, y1, mon2, d2, y2, dn, mn, yn = g[-9:]
    try:
        if y1:
            day, month, year = int(d1), MONTHS[mon1.lower().rstrip(".")], int(y1)
        elif y2:
            day, month, year = int(d2), MONTHS[mon2.lower().rstrip(".")], int(y2)
        else:
            day, month, year = int(dn), int(mn), int(yn)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return ""
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (KeyError, TypeError, ValueError):
        return ""


def _span_to_period(span: str) -> tuple[str, int | None]:
    s = span.lower()
    if "year" in s and "half" not in s or "twelve" in s or "12" in s:
        return "annual", 12
    if "half" in s or "six" in s or "6 " in s + " ":
        return "half-yearly", 6
    if "nine" in s or "9 " in s + " ":
        return "nine-months", 9        # third-quarter reports cover 9 months (store.py's name)
    if "third" in s or "3rd" in s:
        return "quarterly", None       # "third quarter ended": 3 months or 9 cumulative
    if "second" in s or "2nd" in s:
        return "quarterly", None
    return "quarterly", 3


def period_from_title(title: str) -> Period:
    """From an announcement title like 'Transmission of Quarterly Financial
    Statements for the Period Ended 30.09.2026' or 'Annual Report 2026'."""
    t = re.sub(r"\s+", " ", title or "")
    m = PERIOD_RE.search(t)
    if m:
        kind, months = _span_to_period(m.group(1))
        return Period(kind, parse_date(m), months, "title")
    low = t.lower()
    if "annual" in low or "year end" in low:
        kind, months = "annual", 12
    elif "half" in low or "six month" in low:
        kind, months = "half-yearly", 6
    elif "nine month" in low:
        kind, months = "nine-months", 9
    elif "quarter" in low or "three month" in low:
        kind, months = "quarterly", None
    else:
        kind, months = "", None
    dm = DATE_RE.search(t)
    return Period(kind, parse_date(dm) if dm else "", months, "title")


def _head(text: str, n: int = 600) -> str:
    return re.sub(r"\s+", " ", (text or "")[:n])


def period_from_statements(pages: dict[int, str], page_nums: list[int] | None = None) -> Period:
    """From the statement headers. Uses the most common 'for the ... ended <date>'
    on the given pages (or on every page whose top looks like a statement)."""
    nums = page_nums or [p for p, t in pages.items() if statement_kind(t)]
    found, as_at = Counter(), Counter()
    for p in nums:
        head = _head(pages.get(p, ""))
        m = PERIOD_RE.search(head)
        if m:
            kind, months = _span_to_period(m.group(1))
            d = parse_date(m)
            if d:
                found[(kind, d, months)] += 1
        a = AS_AT_RE.search(head)
        if a and parse_date(a):
            as_at[parse_date(a)] += 1
    if found:
        (kind, d, months), _ = found.most_common(1)[0]
        return Period(kind, d, months, "statements")
    if as_at:
        return Period("", as_at.most_common(1)[0][0], None, "statements")
    return Period(source="statements")


def reconcile(title: Period, stmt: Period) -> tuple[Period, list[str]]:
    """Statements win; disagreements are reported, never silently ignored."""
    warnings = []
    if title.period_type and stmt.period_type and title.period_type != stmt.period_type:
        warnings.append(f"period type mismatch: title says {title.period_type}, "
                        f"statements say {stmt.period_type}")
    if title.period_end and stmt.period_end and title.period_end != stmt.period_end:
        warnings.append(f"period end mismatch: title says {title.period_end}, "
                        f"statements say {stmt.period_end}")
    if title.months_covered and stmt.months_covered and title.months_covered != stmt.months_covered:
        warnings.append(f"months covered mismatch: title says {title.months_covered}, "
                        f"statements say {stmt.months_covered}")
    if not stmt.period_end and not stmt.period_type:
        warnings.append("no period found in the statement headers; using the title only")
    out = Period(stmt.period_type or title.period_type, stmt.period_end or title.period_end,
                 stmt.months_covered or title.months_covered,
                 "statements" if (stmt.period_type or stmt.period_end) else "title")
    return out, warnings


# ---- statement pages -------------------------------------------------------
_KINDS = [  # (kind, title regex on lower-case text with whitespace removed)
    ("comprehensive", r"statements?of(?:\w+)?comprehensive(?:income|loss)"),
    ("income", r"statements?of(?:\w+)?(?:profitorloss|profitandloss|income|operations)|profitandlossaccount"
               r"|incomestatement"),
    ("balance", r"statements?of(?:\w+)?financialposition|balancesheet"),
    ("cash_flow", r"statements?of(?:\w+)?cashflows?|cashflowstatement"),
    ("equity", r"statements?of(?:\w+)?changesin(?:\w+)?equity"),
]
_NOT_STATEMENT = re.compile(r"notestothe|independentauditor|auditor'?sreport|reviewreport|contents|"
                            r"directors'?report|analysisof|sixyears|tenyears|horizontal|vertical")


def statement_kind(text: str) -> str:
    """'income', 'balance', ... if the page TOP is a primary statement title, else ''."""
    head = re.sub(r"\s+", "", (text or "")[:350].lower())
    if _NOT_STATEMENT.search(head[:120]):
        return ""
    best = ""
    pos = 10 ** 6
    for kind, rx in _KINDS:
        m = re.search(rx, head)
        if m and m.start() < pos:
            best, pos = kind, m.start()
    return best


def statement_basis(text: str) -> str:
    """consolidated / unconsolidated from the page title. A single set of
    statements with neither word is the company's own (unconsolidated) set."""
    head = re.sub(r"[\s\-–]+", "", (text or "")[:350].lower())
    if re.search(r"unconsolidated|standalone|separatefinancial", head):
        return "unconsolidated"
    if "consolidated" in head:
        return "consolidated"
    return "unconsolidated"


@dataclass
class StatementPage:
    page: int
    statement: str
    basis: str


def tag_statement_pages(pages: dict[int, str]) -> dict[int, StatementPage]:
    out = {}
    for p, t in pages.items():
        k = statement_kind(t)
        if k:
            out[p] = StatementPage(p, k, statement_basis(t))
    return out


@dataclass
class DocMetadata:
    period: Period
    warnings: list[str] = field(default_factory=list)
    statement_pages: dict[int, StatementPage] = field(default_factory=dict)

    @property
    def bases(self) -> list[str]:
        return sorted({s.basis for s in self.statement_pages.values()})


def document_metadata(pages: dict[int, str], title: str = "") -> DocMetadata:
    tagged = tag_statement_pages(pages)
    core = [p for p, s in tagged.items() if s.statement in ("income", "balance", "comprehensive")]
    stmt = period_from_statements(pages, core or None)
    final, warnings = reconcile(period_from_title(title), stmt) if title else (stmt, [])
    if not title and not (stmt.period_type or stmt.period_end):
        warnings.append("no period found in the statement headers")
    return DocMetadata(final, warnings, tagged)
