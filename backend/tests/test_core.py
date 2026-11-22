"""Unit tests for the deterministic parts (no network, no models)."""
import pytest

from mizan.calculator import calculate, parse_number
from mizan.extraction.extractor import RuleExtractor, locate_statement_pages, normalised, validate
from mizan.ingest.psx import classify, parse_company_page
from mizan.models import FieldValue, FinancialHighlights
from mizan.retrieval.retrievers import BM25Retriever, rrf_fuse, tokenize
from mizan.models import Hit, Chunk


# ---------------------------------------------------------------- calculator
@pytest.mark.parametrize("expr,vars,expected", [
    ("a + b", {"a": 2, "b": 3}, 5),
    ("(new - old) / old * 100", {"new": 30000, "old": 24000}, 25.0),
    ("pct_change(n, o)", {"n": 110, "o": 100}, 10.0),
    ("cagr(e, s, 2)", {"e": 121, "s": 100}, 10.0),
    ("round(x / 3, 2)", {"x": 10}, 3.33),
    ("avg(a, b, c)", {"a": 1, "b": 2, "c": 6}, 3.0),
])
def test_calculator_ok(expr, vars, expected):
    assert calculate(expr, vars).result == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("expr", ["__import__('os').system('ls')", "a.b", "x[0]", "lambda: 1",
                                  "open('f')", "1,577 + 2", "2 ** 1000"])
def test_calculator_rejects_unsafe(expr):
    c = calculate(expr, {"a": 1, "x": 1})
    assert c.result is None and c.error


def test_calculator_div_zero_and_unknown_var():
    assert calculate("a / b", {"a": 1, "b": 0}).error == "division by zero"
    assert "unknown variable" in calculate("a + z", {"a": 1}).error


@pytest.mark.parametrize("text,val", [("1,577", 1577), ("(1,577)", -1577), ("Rs. 3.42", 3.42),
                                      ("12.5%", 12.5), ("-45", -45), ("n/a", None)])
def test_parse_number(text, val):
    assert parse_number(text) == val


# ---------------------------------------------------------------- ingestion
def test_ingest_pages_and_chunks(store):
    doc = store.get_document("HDB_FY2025")
    assert doc.n_pages == 3
    assert "Profit after taxation" in store.get_page("HDB_FY2025", 2)
    chunks = store.chunks()
    assert all(c.text.startswith("[Habib Demo Bank") for c in chunks)
    assert {c.page for c in chunks} == {1, 2, 3}


def test_tokenize_keeps_numbers():
    assert "1577" in tokenize("Capex was 1,577 in FY2018")
    assert "2018" in tokenize("FY 2018")


# ---------------------------------------------------------------- retrieval
def test_bm25_finds_right_page(store):
    hits = BM25Retriever(store).retrieve("profit after taxation 2025", k=1)
    assert hits[0].chunk.page == 2


def test_bm25_respects_doc_filter(store):
    assert BM25Retriever(store).retrieve("profit", k=3, doc_ids=["OTHER"]) == []


def test_rrf_fusion_prefers_agreement():
    mk = lambda i: Hit(chunk=Chunk(chunk_id=str(i), doc_id="d", company="c", page=i, text="t"), score=0)
    fused = rrf_fuse([[mk(1), mk(2), mk(3)], [mk(2), mk(4), mk(1)]], k=3)
    assert [h.chunk.chunk_id for h in fused][:2] == ["2", "1"]


# ---------------------------------------------------------------- extraction
def test_locate_statement_pages(store):
    pages = {p: store.get_page("HDB_FY2025", p) for p in (1, 2, 3)}
    assert set(locate_statement_pages(pages)) >= {2, 3}


def test_rule_extractor(store):
    pages = {p: store.get_page("HDB_FY2025", p) for p in (1, 2, 3)}
    res = RuleExtractor().extract(pages, "Habib Demo Bank")
    fh = res.highlights
    assert fh.revenue.value == 120500
    assert fh.net_profit.value == 30000
    assert fh.total_assets.value == 900000
    assert fh.unit == "thousands"
    assert normalised(fh)["net_profit"] == 30_000_000
    assert res.warnings == []


def test_validation_flags_inconsistent_balance_sheet():
    fh = FinancialHighlights(total_assets=FieldValue(value=100), total_liabilities=FieldValue(value=50),
                             total_equity=FieldValue(value=10))
    assert any("total_assets" in w for w in validate(fh))


# ---------------------------------------------------------------- PSX parsing
PSX_HTML = """<table><tr><td>Oct 28, 2026</td><td>Financial Results for the Quarter Ended September 30, 2026</td>
<td><a href="/download/document/287134.pdf">PDF</a></td></tr>
<tr><td>Sep 11, 2026</td><td>Transmission of Annual Report for the year ended June 30, 2026</td>
<td><a href="https://dps.psx.com.pk/download/document/282570.pdf">PDF</a></td></tr>
<tr><td>Sep 1, 2026</td><td>Board Meeting</td><td>-</td></tr></table>"""


def test_parse_psx_company_page():
    links = parse_company_page(PSX_HTML, "psx")
    assert [l.remote_id for l in links] == ["287134", "282570"]
    assert links[0].url == "https://dps.psx.com.pk/download/document/287134.pdf"
    assert links[1].doc_type == "annual" and links[1].period == "A2026"
    assert links[0].date == "Oct 28, 2026"


def test_classify():
    assert classify("Half Yearly Report December 31, 2025")[0] == "half-yearly"
    assert classify("Quarterly report for the period ended March 31, 2026")[0] == "quarterly"


def test_number_evidence_ignores_references_and_tags_sources():
    """Doc ids and page references are not claims; numbers are tagged found/computed/unverified."""
    from mizan.agent.engine import grounding_check, number_evidence
    from mizan.models import Answer, Calculation, Citation

    class _Store:
        def get_page(self, doc_id, page):
            return "Profit after taxation 17,130,585 14,617,657" if (doc_id, page) == ("LUCK_Q2026_1", 22) else None

    ans = Answer(question="q", answer="PAT was 17,130,585 (LUCK_Q2026_1, p. 22), up 17.19% (pp. 12, 25). Also 99,999,999.",
                 citations=[Citation(doc_id="LUCK_Q2026_1", page=22)],
                 calculations=[Calculation(expression="pct_change(a, b)", variables={"a": 17130585, "b": 14617657},
                                           result=17.1912)])
    ev = {e["text"]: e for e in number_evidence(ans, _Store())}
    assert set(ev) == {"17,130,585", "17.19", "99,999,999"}      # no 288146-style ids, no page numbers
    assert ev["17,130,585"]["status"] == "found" and ev["17,130,585"]["page"] == 22
    assert ev["17.19"]["status"] == "computed"
    assert ev["99,999,999"]["status"] == "unverified"
    assert abs(grounding_check(ans, _Store()) - 2 / 3) < 1e-9
