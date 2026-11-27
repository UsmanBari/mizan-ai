"""Tests for Agent v2 (compute_ratio tool, basis rule, three-part answer, deterministic abstention) and new API endpoints (/facts, /compare, /trends, /ask v2)."""
from fastapi.testclient import TestClient

from mizan.agent.engine import QAEngine, detect_requested_basis
from mizan.agent.prompts import PROMPT_VERSION
from mizan.extraction.extractor import RuleExtractor
from mizan.models import Document, FinancialFact
from mizan.retrieval.retrievers import BM25Retriever
from mizan.store import MemoryStore, load_psx_labels

from .conftest import FakeLLM


def _psx_fact_store():
    s = MemoryStore()
    load_psx_labels(s)
    return s


def test_prompt_version_is_v2():
    assert PROMPT_VERSION == "v2.0"


def test_basis_detection_rule():
    assert detect_requested_basis("What is HUBC's standalone net margin?") == "unconsolidated"
    assert detect_requested_basis("Show unconsolidated revenue for LUCK.") == "unconsolidated"
    assert detect_requested_basis("Give company-only profit.") == "unconsolidated"
    assert detect_requested_basis("What is HUBC's consolidated net margin?") == "consolidated"
    assert detect_requested_basis("What is HUBC's net margin?") is None


def test_agent_compute_ratio_and_three_part_answer():
    s = _psx_fact_store()
    # Add a synthetic page so quoted explanation verification can check against cited page text
    from mizan.ingest.parser import Chunk
    doc = Document(doc_id="HUBC_FY2026", company="The Hub Power Company Limited", symbol="HUBC", period="FY2026", n_pages=277)
    page_text = "Consolidated Statement of Profit or Loss 2026 Revenue 71,126,352 Profit 49,630,724. Higher dividend income drove earnings."
    s.add_document(doc, [Chunk(chunk_id="HUBC_FY2026:p275:c0", doc_id="HUBC_FY2026", company="HUBC", page=275, text=page_text)], {275: page_text})

    fake = FakeLLM([
        {"tool_calls": [{"name": "compute_ratio", "arguments": {"name": "net_margin", "symbol": "HUBC", "period": "2026-06-30"}}]},
        {"tool_calls": [{"name": "final_answer", "arguments": {
            "answer": "HUBC's consolidated net margin in FY2026 was 69.78%.",
            "basis": "consolidated",
            "explanation": "\"Higher dividend income drove earnings.\"",
            "citations": [{"doc_id": "HUBC_FY2026", "page": 275}],
        }}]},
    ])
    eng = QAEngine(s, BM25Retriever(s), fake, k=3)
    ans = eng.answer("What was HUBC's net profit margin in FY2026?", mode="agent")
    assert ans.refused is False
    assert ans.basis == "consolidated"
    assert len(ans.reported_figures) == 2
    assert {rf["field"] for rf in ans.reported_figures} == {"net_profit", "revenue"}
    assert len(ans.calculated_values) == 1
    assert ans.calculated_values[0]["name"] == "net_margin"
    assert round(ans.calculated_values[0]["result"], 2) == 69.78
    assert "Higher dividend income" in ans.explanation


def test_agent_unquoted_explanation_falls_back_to_default():
    s = _psx_fact_store()
    fake = FakeLLM([
        {"tool_calls": [{"name": "compute_ratio", "arguments": {"name": "net_margin", "symbol": "LUCK", "period": "2026-06-30"}}]},
        {"tool_calls": [{"name": "final_answer", "arguments": {
            "answer": "LUCK consolidated net margin was 17.24%.",
            "explanation": "Invented management narrative not present anywhere in filings.",
            "citations": [{"doc_id": "LUCK_FY2026", "page": 289}],
        }}]},
    ])
    ans = QAEngine(s, BM25Retriever(s), fake, k=3).answer("LUCK net margin 2026?", mode="agent")
    assert ans.explanation == "The report does not state a reason."


def test_agent_deterministic_abstention_on_conflict():
    s = _psx_fact_store()
    s.add_facts([FinancialFact(
        company="The Hub Power Company Limited", symbol="HUBC", field="revenue",
        period_end="2026-06-30", basis="consolidated", value=99_000_000,
        unit="thousands", doc_id="HUBC_CONFLICT", page=12, source="extraction",
    )])
    # Even if FakeLLM returns final answer, deterministic conflict check abstains showing both values
    fake = FakeLLM([
        {"tool_calls": [{"name": "compute_ratio", "arguments": {"name": "net_margin", "symbol": "HUBC", "period": "2026-06-30"}}]},
        {"tool_calls": [{"name": "final_answer", "arguments": {
            "answer": "HUBC net margin was 50%.",
            "citations": [{"doc_id": "HUBC_FY2026", "page": 275}],
        }}]},
    ])
    ans = QAEngine(s, BM25Retriever(s), fake, k=3).answer("HUBC net margin?", mode="agent")
    assert ans.refused is True
    assert "71,126,352" in ans.refusal_reason and "99,000,000" in ans.refusal_reason
    assert "p.275" in ans.refusal_reason and "p.12" in ans.refusal_reason


def test_agent_deterministic_abstention_on_period_mismatch_and_missing_period():
    s = _psx_fact_store()
    eng = QAEngine(s, BM25Retriever(s), FakeLLM([]), k=3)
    ans = eng.answer("Compare HUBC's Q1 quarterly revenue with annual FY2026 revenue.", mode="agent")
    assert ans.refused is True
    assert "Incompatible periods" in (ans.refusal_reason or "")

    # Missing period FY2022 via compute_ratio with no PDF passages
    fake = FakeLLM([
        {"tool_calls": [{"name": "compute_ratio", "arguments": {"name": "net_margin", "symbol": "HUBC", "period": "FY2022"}}]},
        {"tool_calls": [{"name": "final_answer", "arguments": {
            "answer": "HUBC net margin in FY2022 was 10%.",
            "citations": [],
        }}]},
    ])
    ans2 = QAEngine(s, BM25Retriever(s), fake, k=3).answer("HUBC net margin in FY2022?", mode="agent")
    assert ans2.refused is True
    assert "2022" in (ans2.refusal_reason or "")


def test_api_facts_compare_trends_and_ask_v2(monkeypatch):
    from mizan import services
    from mizan.api import main
    from mizan.store import set_store

    s = _psx_fact_store()
    set_store(s)
    monkeypatch.setattr(services, "get_retriever", lambda kind=None: BM25Retriever(s))
    monkeypatch.setattr(main, "get_retriever", lambda kind=None: BM25Retriever(s))
    monkeypatch.setattr(main, "get_extractor", lambda: RuleExtractor())
    monkeypatch.setattr(main, "get_llm", lambda: None)
    fake = FakeLLM([
        {"tool_calls": [{"name": "compute_ratio", "arguments": {"name": "net_margin", "symbol": "HUBC", "period": "2026-06-30"}}]},
        {"tool_calls": [{"name": "final_answer", "arguments": {
            "answer": "HUBC consolidated net margin was 69.78%.",
            "citations": [{"doc_id": "HUBC_FY2026", "page": 275}],
        }}]},
    ])
    monkeypatch.setattr(main, "get_engine", lambda: QAEngine(s, BM25Retriever(s), fake, k=3))
    client = TestClient(main.app)

    # /facts/{symbol}
    rf = client.get("/facts/HUBC")
    assert rf.status_code == 200
    assert rf.json()["symbol"] == "HUBC"
    assert len(rf.json()["facts"]) == 12  # 6 fields x 2 periods
    assert client.get("/facts/UNKNOWN_SYM").status_code == 404

    # /compare (including derived D/E and PRL base<=0 earnings_growth)
    rc = client.get("/compare", params={
        "symbols": "LUCK,PRL",
        "period_end": "2026-06-30",
        "metrics": "revenue,net_margin,debt_to_equity,earnings_growth",
    })
    assert rc.status_code == 200
    tbl = rc.json()["table"]
    assert tbl["LUCK"]["revenue"]["doc_id"] == "LUCK_FY2026" and tbl["LUCK"]["revenue"]["page"] == 289
    assert round(tbl["LUCK"]["net_margin"]["value"], 2) == 17.24
    # PRL prior year net profit is negative (-4,659,666) -> earnings_growth refused, change_amount reported
    assert tbl["PRL"]["earnings_growth"]["refused"] is True
    assert tbl["PRL"]["earnings_growth"]["change_amount"] == 15779957 - (-4659666)
    assert tbl["PRL"]["debt_to_equity"]["refused"] is False
    assert tbl["PRL"]["debt_to_equity"]["page"] == 67

    # /trends/{symbol}
    rt = client.get("/trends/HUBC", params={"metrics": "revenue,net_margin,roe"})
    assert rt.status_code == 200
    data = rt.json()
    assert data["periods"] == ["2025-06-30", "2026-06-30"]
    assert data["series"]["2025-06-30"]["roe"]["refused"] is True  # only 1 period up to 2025
    assert data["series"]["2026-06-30"]["roe"]["refused"] is False
    assert data["series"]["2026-06-30"]["roe"]["page"] in (275, 277)

    # /ask returns three-part answer
    ra = client.post("/ask", json={"question": "What was HUBC's net margin in FY2026?", "mode": "agent"})
    assert ra.status_code == 200
    body = ra.json()
    assert body["basis"] == "consolidated"
    assert len(body["reported_figures"]) == 2
    assert len(body["calculated_values"]) == 1
    assert body["explanation"] == "The report does not state a reason."


def test_api_facts_index_ratios_and_labelled_pdf_pages(tmp_path, monkeypatch):
    """Burhan's frontend pickers: /facts lists companies + periods, /ratios lists formulas,
    and a fact's page can be opened even when its report was never ingested."""
    from mizan.api import main
    from mizan.store import set_store

    from .conftest import make_pdf

    s = _psx_fact_store()
    set_store(s)
    client = TestClient(main.app)
    idx = client.get("/facts").json()
    hubc = next(c for c in idx if c["symbol"] == "HUBC")
    assert {"period_end": "2026-06-30", "period_type": "annual", "months": 12} in hubc["periods"]
    assert "consolidated" in hubc["bases"]
    names = {r["name"]: r for r in client.get("/ratios").json()}
    assert names["net_margin"]["formula"] == "net_profit / revenue * 100"
    # labelled PDF fallback: eval/data/psx_pdfs/<doc_id>.pdf
    make_pdf(tmp_path / "DEMO_FY2026.pdf", ["Statement of Profit or Loss\nRevenue 1,234 1,000"])
    monkeypatch.setattr(main, "_EVAL_PDFS", tmp_path)
    r = client.get("/documents/DEMO_FY2026/pages/1")
    assert r.status_code == 200 and "1,234" in r.json()["text"]
    assert client.get("/documents/..%2Fsecret/pages/1").status_code == 404
