"""Unit tests for the verified financial facts store, conflict detection, label loader, and disk persistence."""
from pathlib import Path

from mizan.ingest.pipeline import ingest_pdf
from mizan.models import FieldValue, FinancialFact, FinancialHighlights
from mizan.store import MemoryStore, load_psx_labels


def test_loads_verified_psx_labels_and_creates_current_and_prior():
    s = MemoryStore()
    n = load_psx_labels(s)
    # 9 verified companies x 6 fields x 2 periods (current + prior) = 108 facts
    assert n == 108
    hubc_rev = s.get_facts(symbol="HUBC", field="revenue")
    periods = {f.period_end: f for f in hubc_rev}
    assert set(periods) == {"2026-06-30", "2025-06-30"}
    assert periods["2026-06-30"].value == 71126352
    assert periods["2025-06-30"].value == 83351492
    assert periods["2026-06-30"].basis == "consolidated"
    assert periods["2026-06-30"].source == "label"
    assert periods["2026-06-30"].page == 275


def test_conflicts_flagged_not_merged():
    s = MemoryStore()
    f1 = FinancialFact(
        company="Hub Power", symbol="HUBC", field="revenue",
        period_end="2026-06-30", basis="consolidated",
        value=71126352, unit="thousands", doc_id="HUBC_FY2026", page=275, source="label",
    )
    f2 = FinancialFact(
        company="Hub Power", symbol="HUBC", field="revenue",
        period_end="2026-06-30", basis="consolidated",
        value=75000000, unit="thousands", doc_id="HUBC_ALT", page=12, source="extraction",
    )
    s.add_facts([f1])
    conflicts = s.add_facts([f2])
    assert len(conflicts) == 1
    stored = s.get_facts(symbol="HUBC", field="revenue", period_end="2026-06-30", basis="consolidated")
    # Both kept, never merged
    assert len(stored) == 2
    assert all(f.conflict is True for f in stored)
    assert {f.value for f in stored} == {71126352.0, 75000000.0}


def test_matching_facts_within_tolerance_not_conflicted():
    s = MemoryStore()
    f1 = FinancialFact(
        company="Hub Power", symbol="HUBC", field="revenue",
        period_end="2026-06-30", basis="consolidated",
        value=71126352, unit="thousands", doc_id="D1", page=1, source="label",
    )
    f2 = FinancialFact(
        company="Hub Power", symbol="HUBC", field="revenue",
        period_end="2026-06-30", basis="consolidated",
        value=71126.352, unit="millions", doc_id="D2", page=1, source="extraction",
    )
    conflicts = s.add_facts([f1, f2])
    assert conflicts == []
    stored = s.get_facts(symbol="HUBC", field="revenue")
    assert all(f.conflict is False for f in stored)


def test_store_persists_across_restart(tmp_path, sample_pdf):
    pkl = tmp_path / "store.pkl"
    s1 = MemoryStore(persist_path=pkl, autoload_labels=False)
    ingest_pdf(s1, sample_pdf, "HDB_FY2025", "Habib Demo Bank", "HDB", "annual", "FY2025")
    fh = FinancialHighlights(
        company="Habib Demo Bank", period_end="2025-12-31", unit="thousands", consolidated=False,
        revenue=FieldValue(value=120500, page=2), net_profit=FieldValue(value=30000, page=2),
    )
    s1.save_financials("HDB_FY2025", fh)
    assert pkl.exists()

    s2 = MemoryStore(persist_path=pkl, autoload_labels=False)
    assert s2.get_document("HDB_FY2025") is not None
    assert "Profit after taxation" in s2.get_page("HDB_FY2025", 2)
    assert s2.get_financials("HDB_FY2025").revenue.value == 120500
    facts = s2.get_facts(symbol="HDB")
    assert {f.field: f.value for f in facts} == {"revenue": 120500.0, "net_profit": 30000.0}
