"""Unit tests for backend/mizan/ratios.py — every formula and every refusal."""
import pytest

from mizan.ratios import RATIOS, compute


def _op(value, doc_id="D1", page=10, basis="consolidated", period_type="annual", months=12, unit="thousands"):
    return {
        "value": value,
        "doc_id": doc_id,
        "page": page,
        "basis": basis,
        "period_type": period_type,
        "months": months,
        "unit": unit,
    }


def _two_period_sample():
    return {
        "2026-06-30": {
            "revenue": _op(1000, page=1),
            "gross_profit": _op(400, page=1),
            "operating_profit": _op(250, page=1),
            "interest_expense": _op(50, page=1),
            "net_profit": _op(150, page=1),
            "eps_basic": _op(15.0, page=1, unit="Rupees per share"),
            "total_assets": _op(1200, page=2),
            "total_liabilities": _op(700, page=2),
            "total_equity": _op(500, page=2),
            "current_assets": _op(450, page=2),
            "current_liabilities": _op(225, page=2),
        },
        "2025-06-30": {
            "revenue": _op(800, page=1),
            "net_profit": _op(100, page=1),
            "eps_basic": _op(10.0, page=1, unit="Rupees per share"),
            "total_assets": _op(800, page=2),
            "total_equity": _op(400, page=2),
        },
    }


@pytest.mark.parametrize("name,expected,unit", [
    ("gross_margin", 40.0, "%"),
    ("operating_margin", 25.0, "%"),
    ("net_margin", 15.0, "%"),
    ("revenue_growth", 25.0, "%"),
    ("earnings_growth", 50.0, "%"),
    ("eps_growth", 50.0, "%"),
    ("roe", 150 / 450 * 100, "%"),      # 150 / avg(500, 400) * 100 = 33.3333%
    ("roa", 150 / 1000 * 100, "%"),     # 150 / avg(1200, 800) * 100 = 15.0%
    ("debt_to_equity", 700 / 500, "x"), # 1.4x
    ("current_ratio", 450 / 225, "x"),  # 2.0x
    ("interest_coverage", 250 / 50, "x"),
])
def test_all_ratio_formulas(name, expected, unit):
    res = compute(name, _two_period_sample())
    assert res["refused"] is False
    assert res["unit"] == unit
    assert res["value"] == pytest.approx(expected, rel=1e-4)
    assert res["formula"]
    assert len(res["operands"]) >= 2
    for o in res["operands"]:
        assert {"field", "period", "value", "doc_id", "page", "basis"} <= set(o.keys())


def test_debt_to_equity_derives_liabilities_when_missing():
    data = {
        "2026-06-30": {
            "total_assets": _op(1200, page=2),
            "total_equity": _op(500, page=2),
        }
    }
    res = compute("debt_to_equity", data)
    assert res["refused"] is False
    assert res["value"] == pytest.approx(1.4, rel=1e-4)
    assert res["formula"] == "(total_assets - total_equity) / total_equity"
    assert [o["field"] for o in res["operands"]] == ["total_assets", "total_equity"]


def test_every_ratio_declares_spec():
    for r, spec in RATIOS.items():
        assert len(spec.required_fields) >= 1
        assert spec.n_periods in (1, 2)


# ---------------------------------------------------------------- refusals
def test_refuses_unknown_ratio():
    res = compute("mystery_ratio", _two_period_sample())
    assert res["refused"] is True and "Unknown ratio" in res["reason"]


def test_refuses_missing_operand():
    res = compute("gross_margin", {"2026-06-30": {"revenue": _op(1000)}})
    assert res["refused"] is True and "gross_profit" in res["reason"]

    res_single_period = compute("roe", {"2026-06-30": {"net_profit": _op(100), "total_equity": _op(400)}})
    assert res_single_period["refused"] is True and "2 periods" in res_single_period["reason"]

    res_missing_prior_eq = compute("roe", {
        "2026-06-30": {"net_profit": _op(100), "total_equity": _op(400)},
        "2025-06-30": {"net_profit": _op(80)},
    })
    assert res_missing_prior_eq["refused"] is True and "total_equity" in res_missing_prior_eq["reason"]


def test_refuses_incompatible_period_type_or_months():
    res_qtr_vs_ann = compute("revenue_growth", {
        "2026-06-30": {"revenue": _op(1000, period_type="annual", months=12)},
        "2026-03-31": {"revenue": _op(250, period_type="quarterly", months=3)},
    })
    assert res_qtr_vs_ann["refused"] is True
    assert "quarterly" in res_qtr_vs_ann["reason"].lower()

    res_months = compute("net_margin", {
        "2026-06-30": {
            "net_profit": _op(100, period_type="half-yearly", months=6),
            "revenue": _op(1000, period_type="annual", months=12),
        }
    })
    assert res_months["refused"] is True


def test_refuses_incompatible_basis():
    res = compute("net_margin", {
        "2026-06-30": {
            "net_profit": _op(100, basis="consolidated"),
            "revenue": _op(1000, basis="unconsolidated"),
        }
    })
    assert res["refused"] is True and "basis" in res["reason"].lower()


def test_refuses_growth_when_base_le_zero_and_reports_amount_change():
    res_loss = compute("earnings_growth", {
        "2026-06-30": {"net_profit": _op(15_779_957)},
        "2025-06-30": {"net_profit": _op(-4_659_666)},
    })
    assert res_loss["refused"] is True
    assert "<= 0" in res_loss["reason"]
    assert res_loss["change_amount"] == pytest.approx(20_439_623.0)

    res_zero = compute("eps_growth", {
        "2026-06-30": {"eps_basic": _op(2.5, unit="Rupees per share")},
        "2025-06-30": {"eps_basic": _op(0.0, unit="Rupees per share")},
    })
    assert res_zero["refused"] is True
    assert res_zero["change_amount"] == pytest.approx(2.5)


def test_refuses_non_positive_denominators():
    assert compute("net_margin", {"2026-06-30": {"net_profit": _op(10), "revenue": _op(0)}})["refused"] is True
    assert compute("debt_to_equity", {"2026-06-30": {"total_liabilities": _op(100), "total_equity": _op(-10)}})["refused"] is True
    assert compute("current_ratio", {"2026-06-30": {"current_assets": _op(100), "current_liabilities": _op(0)}})["refused"] is True
    assert compute("interest_coverage", {"2026-06-30": {"operating_profit": _op(100), "interest_expense": _op(0)}})["refused"] is True
    assert compute("roe", {
        "2026-06-30": {"net_profit": _op(100), "total_equity": _op(-50)},
        "2025-06-30": {"total_equity": _op(-50)},
    })["refused"] is True


def test_scales_compatible_monetary_units():
    res = compute("net_margin", {
        "2026-06-30": {
            "net_profit": _op(150, unit="millions"),
            "revenue": _op(1_000_000, unit="thousands"),
        }
    })
    assert res["refused"] is False
    assert res["value"] == pytest.approx(15.0, rel=1e-4)
