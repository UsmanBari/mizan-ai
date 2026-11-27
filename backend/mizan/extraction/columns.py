"""Column-safe reading of statement tables (deterministic, no AI).

Problem (supervisor's point 4, and our failure log): a statement row reads
"Profit after taxation | 36 | 96,456,241 | 84,498,377". Taking "the first number
after the label" can give the note reference (36) or, when the current figure is
blank or split over two lines, the PRIOR-year figure.

Fix: use the word x-positions from the PDF.
  1. find the column-header row above the table ("Note | 2026 | 2025",
     "June 30, 2026 | June 30, 2025", "Nine months ended ... 2026 2025 2026 2025");
  2. every header cell with a year becomes a column, at the header's x-span;
     a "Note" header becomes the note column, whose numbers are dropped;
  3. every number in a row is assigned to the nearest column;
  4. the CURRENT column is the latest date (latest year; on ties the latest
     month, else the left-most, which is the cumulative period in PSX interim
     reports); the PRIOR column is the comparative next to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..calculator import parse_number
from .extractor import _RULES, ExtractionResult, FieldValue, FinancialHighlights, _guess_unit, \
    locate_statement_pages, validate
from ..ingest.metadata import MONTHS, statement_basis, tag_statement_pages
from ..llm import Usage
from ..models import FIELDS

YEAR = re.compile(r"^\(?(19[89]\d|20[0-4]\d)\)?[,.]?$")
NUM = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?$")
DASH = {"-", "–", "—", "--", "nil", "Nil"}


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Column:
    x0: float
    x1: float
    year: int | None = None
    month: int | None = None
    is_note: bool = False
    months: int | None = None    # 3 / 6 / 9 / 12 from a "Nine months ended" header above it

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Row:
    y: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Table:
    """The column layout of one statement table (a landscape page can hold two
    tables side by side, e.g. assets on the left, equity and liabilities right)."""
    header_y: float
    columns: list[Column]
    current: int | None          # index into columns
    prior: int | None
    x_lo: float = 0.0            # the table's horizontal region (label + numbers)
    x_hi: float = 1e9


@dataclass
class PageRows:
    page: int
    rows: list[Row]
    tables: list[Table] = field(default_factory=list)

    def table_for(self, y: float, x: float | None = None) -> Table | None:
        above = [t for t in self.tables if t.header_y <= y + 1 and (x is None or t.x_lo <= x < t.x_hi)]
        return max(above, key=lambda t: t.header_y) if above else None


def words_to_rows(words: list[tuple], ytol: float = 3.0) -> list[Row]:
    ws = [Word(w[0], w[1], w[2], w[3], str(w[4]).strip()) for w in words if str(w[4]).strip()]
    rows: list[Row] = []
    for w in sorted(ws, key=lambda w: (w.cy, w.x0)):
        if rows and abs(rows[-1].y - w.cy) <= ytol:
            rows[-1].words.append(w)
        else:
            rows.append(Row(w.cy, [w]))
    for r in rows:
        r.words.sort(key=lambda w: w.x0)
    return rows


def _cells(row: Row, gap: float = 8.0) -> list[list[Word]]:
    """Group a row's words into cells separated by horizontal gaps."""
    cells: list[list[Word]] = []
    for w in row.words:
        if cells and w.x0 - cells[-1][-1].x1 <= gap:
            cells[-1].append(w)
        else:
            cells.append([w])
    return cells


def _header_columns(row: Row) -> list[Column]:
    cols = []
    for cell in _cells(row):
        texts = [w.text for w in cell]
        years = [int(YEAR.match(t).group(1)) for t in texts if YEAR.match(t)]
        x0, x1 = cell[0].x0, cell[-1].x1
        if len(years) > 1:
            # "2026 2025" glued into one cell: split per year word
            for w in cell:
                m = YEAR.match(w.text)
                if m:
                    cols.append(Column(w.x0, w.x1, int(m.group(1))))
            continue
        if years:
            month = next((MONTHS[t.lower().strip(".,")] for t in texts if t.lower().strip(".,") in MONTHS), None)
            cols.append(Column(x0, x1, years[0], month))
        elif any(t.lower().strip(".") in ("note", "notes") for t in texts):
            cols.append(Column(x0, x1, is_note=True))
    return cols


def _is_header(row: Row, cols: list[Column]) -> bool:
    n_years = sum(c.year is not None for c in cols)
    if n_years < 2:
        return False
    # a data row has large numbers; a header has years and words only
    big = [w for w in row.words if NUM.match(w.text) and not YEAR.match(w.text)
           and (parse_number(w.text) or 0) >= 1000]
    return not big


def detect_tables(rows: list[Row]) -> list[Table]:
    tables = []
    for r in rows:
        cols = _header_columns(r)
        if not _is_header(r, cols):
            continue
        # a "Note" header is often on the row above the years ("Note" / "2026 2025")
        if not any(c.is_note for c in cols):
            for r2 in rows:
                if 0 < r.y - r2.y <= 16:
                    cols += [c for c in _header_columns(r2) if c.is_note]
        cols.sort(key=lambda c: c.x0)
        _tag_spans(cols, [r2 for r2 in rows if 0 < r.y - r2.y <= 45])
        # side-by-side tables: a big horizontal gap between dated columns splits them
        groups, cur_g = [], [cols[0]]
        for a, b in zip(cols, cols[1:]):
            if b.x0 - a.x1 > 250 and any(c.year for c in cur_g):
                groups.append(cur_g)
                cur_g = []
            cur_g.append(b)
        groups.append(cur_g)
        for g in groups:
            t = _make_table(r.y, g)
            if t:
                tables.append(t)
    # regions: each table owns the space from the previous table's numbers to its own
    by_x = sorted({(round(t.columns[0].x0), round(t.columns[-1].x1)) for t in tables})
    for t in tables:
        lo = [hi for (_, hi) in by_x if hi < t.columns[0].x0 - 1]
        t.x_lo = (max(lo) + 5) if lo else 0.0
    for t in tables:
        right = [u.x_lo for u in tables if u.x_lo > t.columns[-1].x1]
        t.x_hi = min(right) if right else 1e9
    return tables


_SPAN_WORDS = [(r"twelve months|year ended|\byear\b", 12), (r"nine months|9 months", 9),
               (r"six months|half[\s-]*year|6 months", 6), (r"three months|3 months|quarter", 3)]


def _span_months(text: str) -> int | None:
    t = text.lower()
    for rx, m in _SPAN_WORDS[1:] + _SPAN_WORDS[:1]:      # "nine months" before a stray "year"
        if re.search(rx, t):
            return m
    return None


def _tag_spans(cols: list[Column], above: list[Row]) -> None:
    """Interim statements put two periods side by side: "Three months ended |
    Nine months ended" over "2026 2025 2026 2025". Each dated column gets the
    period length of the header cell above it. The order differs between
    companies (ATRL puts three months first), so it must be read, not assumed."""
    spans = []
    for r2 in above:
        for cell in _cells(r2, gap=12):
            m = _span_months(" ".join(w.text for w in cell))
            if m:
                spans.append((cell[0].x0, cell[-1].x1, m))
    if len({m for *_, m in spans}) < 2:
        return                      # one period only (annual reports): nothing to tell apart
    for c in cols:
        if c.year is None:
            continue
        inside = [m for x0, x1, m in spans if x0 - 15 <= c.cx <= x1 + 15]
        if inside:
            c.months = inside[0]
        else:
            near = min(spans, key=lambda s: abs((s[0] + s[1]) / 2 - c.cx))
            if abs((near[0] + near[1]) / 2 - c.cx) <= 90:
                c.months = near[2]


def _make_table(y: float, cols: list[Column]) -> Table | None:
    if True:
        dated = [i for i, c in enumerate(cols) if c.year is not None]
        if len(dated) < 2:          # a lone date is a title ("for the year ended June 30, 2026")
            return None
        # current = the longest period (the report's own, e.g. nine months), then the latest date
        cur = max(dated, key=lambda i: (cols[i].months or 0, cols[i].year, cols[i].month or 0, -cols[i].x0))
        if cols[cur].months:
            same = [i for i in dated if cols[i].months == cols[cur].months]
            earlier_same = [i for i in same if (cols[i].year, cols[i].month or 0) < (cols[cur].year, cols[cur].month or 0)]
            if earlier_same:
                prior = max(earlier_same, key=lambda i: (cols[i].year, cols[i].month or 0))
                return Table(y, cols, cur, prior)
        later = [i for i in dated if i > cur]
        earlier = [i for i in dated if cols[i].year < cols[cur].year or
                   (cols[i].year == cols[cur].year and (cols[i].month or 0) < (cols[cur].month or 0))]
        # the comparative is normally the next column to the right; else the latest earlier one
        prior = later[0] if later else (max(earlier, key=lambda i: (cols[i].year, cols[i].month or 0))
                                        if earlier else None)
        return Table(y, cols, cur, prior)


def assign(table: Table, w: Word, tol: float = 45.0) -> int | None:
    """Index of the column this number belongs to (numbers are usually right-
    aligned under their header, so use the closer of centre and right edge)."""
    best, dist = None, tol
    for i, c in enumerate(table.columns):
        d = min(abs(w.cx - c.cx), abs(w.x1 - c.x1))
        if d < dist:
            best, dist = i, d
    return best


def row_values(pr: PageRows, row: Row) -> dict[int, float | None]:
    """column index -> value for one row (a dash counts as 0; notes dropped)."""
    t = pr.table_for(row.y, row.words[0].x0)
    if t is None:
        return {}
    out: dict[int, float | None] = {}
    for w in row.words:
        if NUM.match(w.text) or w.text in DASH:
            i = assign(t, w)
            if i is None or t.columns[i].is_note:
                continue
            v = 0.0 if w.text in DASH else parse_number(w.text)
            if v is not None and i not in out:
                out[i] = v
    return out


def label_of(pr: PageRows, row: Row) -> str:
    t = pr.table_for(row.y, row.words[0].x0)
    left = min((c.x0 for c in t.columns), default=1e9) - 5 if t else 1e9
    # PDF words often carry trailing tabs, so their right edge runs into the
    # number columns: use the left edge
    out = []
    for w in row.words:
        if w.x0 >= left:
            break
        if NUM.match(w.text) or w.text in DASH:
            continue            # a note reference or a "Sales - net" dash
        out.append(w.text)
    return _LIG.sub(lambda m: _LIGS[m.group(0)], " ".join(out)).strip()


_LIGS = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "–": "-", "—": "-", "’": "'"}
_LIG = re.compile("|".join(_LIGS))


def current_prior(pr: PageRows, row: Row) -> tuple[float | None, float | None]:
    t = pr.table_for(row.y, row.words[0].x0)
    if t is None:
        return None, None
    vals = row_values(pr, row)
    return vals.get(t.current), (vals.get(t.prior) if t.prior is not None else None)


def page_rows_from_words(page: int, words: list[tuple]) -> PageRows:
    rows = words_to_rows(words)
    tables = detect_tables(rows)
    regions = sorted({(t.x_lo, t.x_hi) for t in tables})
    if len(regions) > 1:          # split every row at the table boundaries
        split = []
        for r in rows:
            for lo, hi in regions:
                ws = [w for w in r.words if lo <= w.x0 < hi]
                if ws:
                    split.append(Row(r.y, ws))
        rows = split
    return PageRows(page, rows, tables)


def read_page_rows(pdf_path: str | Path, page: int) -> PageRows:
    import pymupdf
    with pymupdf.open(str(pdf_path)) as doc:
        return page_rows_from_words(page, doc[page - 1].get_text("words"))


def _close(a: float, b: float) -> bool:
    """Same printed number (sign ignored: brackets are often dropped). Exact, not
    "within 0.5%": neighbouring rows like 'Profit before taxation and levy'
    116,557,102 and 'Profit before taxation' 116,190,243 are 0.3% apart."""
    return abs(abs(a) - abs(b)) <= (0.006 if abs(b) < 1000 and not float(b).is_integer() else 0.5)


def find_row_with_value(pr: PageRows, value: float) -> Row | None:
    for r in pr.rows:
        if any(_close(v, value) for v in row_values(pr, r).values() if v is not None):
            return r
    return None


def prior_for_value(pr: PageRows, value: float) -> float | None:
    """Prior-period value on the row whose CURRENT column holds `value`."""
    for r in pr.rows:
        cur, pri = current_prior(pr, r)
        if cur is not None and _close(cur, value):
            return pri
    return None


def correct_to_current(pr: PageRows, value: float) -> tuple[float, str]:
    """If `value` sits in the prior-year column of its row, return the current-
    year value of that row instead. Returns (value, what_happened)."""
    r = find_row_with_value(pr, value)
    if r is None:
        return value, "row_not_found"
    cur, pri = current_prior(pr, r)
    if cur is not None and _close(cur, value):
        return value, "current"
    if pri is not None and _close(pri, value) and cur is not None:
        return cur, "was_prior_column"
    return value, "other_column"


def locate_by_tags(pages: dict[int, str]) -> list[int]:
    """Statement pages from the page-title tags (metadata.tag_statement_pages):
    the income statement and balance sheet of ONE basis that sit next to each
    other (consolidated preferred, like the labels), plus the page after each,
    since statements often run over. Falls back to keyword scoring."""
    tags = tag_statement_pages(pages)
    best = None
    for basis in ("consolidated", "unconsolidated"):
        inc = [p for p, t in tags.items() if t.basis == basis and t.statement == "income"] or \
              [p for p, t in tags.items() if t.basis == basis and t.statement == "comprehensive"]
        bal = [p for p, t in tags.items() if t.basis == basis and t.statement == "balance"]
        pairs = sorted(((abs(i - b), b, i) for i in inc for b in bal if abs(i - b) <= 6))
        if pairs:
            best = pairs[0]
            break
    if best is None:
        return locate_statement_pages(pages)
    _, b, i = best
    out = {b, i}
    # a balance sheet often takes two titled pages (assets / equity and liabilities)
    for q in (b - 1, b + 1):
        t = tags.get(q)
        if t and t.statement == "balance" and t.basis == tags[b].basis:
            out.add(q)
    for p in (b, i):
        if p + 1 in pages and not tag_statement_pages({p + 1: pages[p + 1]}):
            out.add(p + 1)          # continuation page without its own title
    return sorted(out)


def unit_of(pages: dict[int, str], use: list[int]) -> str:
    """Unit from the statement headers: "(PKR in '000')", "Rupees in thousand",
    "Rs. in million", or plain "Rupees". Curly quotes are normalised first."""
    votes: dict[str, int] = {}
    for p in use:
        t = re.sub(r"[‘’`´']", "'", pages[p][:1500].lower())
        t = re.sub(r"\s+", " ", t)
        if re.search(r"(?:rs\.?|rupees?|pkr)\s*(?:in)?\s*\(?\s*'?\s*000|in thousands?|rupees in thousand"
                     r"|\(?'000\)?", t):
            u = "thousands"
        elif re.search(r"(?:rs\.?|rupees?|pkr)\s*(?:in)?\s*millions?|in millions?", t):
            u = "millions"
        elif re.search(r"(?:rs\.?|rupees?|pkr)\s*in\s*billions?|in billions?", t):
            u = "billions"
        elif re.search(r"[-–]{2,}\s*rupees\s*[-–]{2,}|\(rupees\)|\brupees\b", t):
            u = "units"
        else:
            continue
        votes[u] = votes.get(u, 0) + 1
    return max(votes, key=votes.get) if votes else _guess_unit("\n".join(pages[p] for p in use))


BALANCE_FIELDS = {"total_assets", "total_liabilities", "total_equity"}
# labels the baseline misses (from our failure log): "Earnings / (loss) per share",
# "Profit / (loss) after taxation"
EXTRA_RULES = {
    "eps_basic": [r"^(?:earnings|\(?loss\)?)\s*/\s*\(?(?:loss|earnings)\)?\s+per share"],
    "net_profit": [r"^(?:net )?(?:profit|\(loss\))\s*/\s*\(?(?:loss|profit)\)?\s+(?:after tax|for the (?:year|period))"],
    "profit_before_tax": [r"^(?:profit|\(loss\))\s*/\s*\(?(?:loss|profit)\)?\s+before\s+(?:income\s+)?tax"],
}


class ColumnExtractor:
    """Rule baseline, but values come from the CURRENT-year column only.

    Needs the PDF (for word positions): extract(pages, company, pdf_path=...)."""
    name = "rules+columns"

    def extract(self, pages: dict[int, str], company_hint: str = "", pdf_path: str | Path | None = None,
                page_rows: dict[int, PageRows] | None = None) -> ExtractionResult:
        use = locate_by_tags(pages)
        prs = page_rows or {p: read_page_rows(pdf_path, p) for p in use}
        fh = FinancialHighlights(company=company_hint)
        tags = tag_statement_pages({p: pages[p] for p in use})
        kind = {}
        last = ""
        for p in use:                 # continuation pages inherit the statement above them
            last = tags[p].statement if p in tags else last
            kind[p] = last
        for f in FIELDS:
            want = ("balance",) if f in BALANCE_FIELDS else ("income", "comprehensive")
            order = [p for p in use if kind.get(p) in want] + [p for p in use if kind.get(p) not in want]
            for p in order:
                v, label = self._find(prs[p], _RULES[f] + EXTRA_RULES.get(f, []), f)
                if v is not None:
                    setattr(fh, f, FieldValue(value=v, page=p, label=label))
                    break
        a, l = fh.total_assets, fh.total_liabilities
        if fh.total_equity.value is None and a.value is not None and l.value is not None and a.page == l.page:
            # no "Total equity" line (AGIL): equity = assets - liabilities, computed in code
            fh.total_equity = FieldValue(value=a.value - l.value, page=a.page,
                                         label="computed: total assets - total liabilities")
        fh.unit = unit_of(pages, use)
        fh.consolidated = any(statement_basis(pages[p]) == "consolidated" for p in use)
        return ExtractionResult(fh, use, Usage(), None, validate(fh))

    @staticmethod
    def _current(pr: PageRows, r: Row) -> float | None:
        t = pr.table_for(r.y, r.words[0].x0)
        if t is None:
            return None
        for w in r.words:          # a dash in the current column means "no figure": skip the row
            if w.text in DASH and assign(t, w) == t.current:
                return None
        return current_prior(pr, r)[0]

    def _find(self, pr: PageRows, patterns: list[str], field: str = "") -> tuple[float | None, str]:
        found = self._find_all(pr, patterns, field)
        if not found:
            return None, ""
        if field == "revenue":
            # "Sales" then "Sales tax" then "NET SALES": the net line is revenue
            net = [f for f in found if re.search(r"\bnet\b", f[1].lower())]
            return (net or found)[0][:2]
        if field == "net_profit":
            owners = [f for f in found if f[2]]
            if owners:
                return owners[0][:2]
            total = [f for f in found if "continuing" not in f[1].lower()]
            return (total or found)[0][:2]
        if field == "profit_before_tax":
            # "Profit before taxation and levy / final taxes" comes before the line we label
            after = [f for f in found if not re.search(r"levy|final tax|minimum tax", f[1].lower())]
            return (after or found)[0][:2]
        return found[0][:2]

    def _find_all(self, pr: PageRows, patterns: list[str], field: str = "") -> list[tuple[float, str, bool]]:
        rows = pr.rows
        hits = []
        for i, r in enumerate(rows):
            lab = label_of(pr, r).lower()
            if not lab or not any(re.search(p, lab) for p in patterns):
                continue
            if field == "total_equity" and re.search(r"\band\b.*liabilit", lab):
                continue           # "Total equity and liabilities" is total assets, not equity
            cur = self._current(pr, r)
            j = i
            if cur is None:
                # label wrapped onto two lines: the numbers are on the next row
                for j in range(i + 1, min(i + 3, len(rows))):
                    l2 = label_of(pr, rows[j])
                    if l2 and not l2[:1].islower() and not re.match(r"^[-(]?\s*(?:and|levy|tax)", l2.lower()) \
                            and not re.search(r"\b(?:basic|diluted)\b", l2.lower()):
                        break
                    cur = self._current(pr, rows[j])
                    if cur is not None:
                        break
            if cur is None:
                continue
            owners = False
            if field in ("net_profit", "total_equity"):
                # consolidated statements split the total into owners' share and
                # non-controlling interest: the owners' share is what EPS is based on
                for r2 in rows[j + 1:j + 5]:
                    l2 = label_of(pr, r2).lower()
                    if re.search(r"(?:owners|equity holders|shareholders) of the (?:holding|parent)"
                                 r"|^owners of the|attributable to (?:the )?(?:owners|equity holders)", l2):
                        v2 = self._current(pr, r2)
                        if v2 is not None:
                            cur, r, owners = v2, r2, True
                            break
            hits.append((cur, label_of(pr, r), owners))
        return hits


class ColumnCheckedLLM:
    """'AI proposes, code decides' for extraction: the LLM picks the line item
    and page; code re-reads the value from that row's CURRENT-year column.
    Wraps an LLMExtractor result, so it costs no extra API call."""
    name = "api+columns"

    def __init__(self, inner_name: str = "api") -> None:
        self.name = f"{inner_name}+columns"
        self.corrections: list[dict] = []

    def correct(self, res: ExtractionResult, pdf_path: str | Path,
                cache: dict[int, PageRows] | None = None) -> ExtractionResult:
        fh = res.highlights
        if fh is None:
            return res
        fh = fh.model_copy(deep=True)
        cache = cache if cache is not None else {}
        for f in FIELDS:
            fv = getattr(fh, f)
            if fv.value is None or not fv.page:
                continue
            if fv.page not in cache:
                try:
                    cache[fv.page] = read_page_rows(pdf_path, fv.page)
                except Exception:
                    continue
            v, what = correct_to_current(cache[fv.page], fv.value)
            if what == "was_prior_column":
                self.corrections.append({"field": f, "page": fv.page, "llm": fv.value, "code": v})
                setattr(fh, f, FieldValue(value=v, page=fv.page, label=fv.label))
        return ExtractionResult(fh, res.pages_used, res.usage, res.error, validate(fh))
