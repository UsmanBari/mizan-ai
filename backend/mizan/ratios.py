"""Deterministic financial ratio and growth library.

Every formula lives in Python code here — never computed by the LLM.
All ratios declare their required fields and period count, validate period
compatibility (same period_type and months covered), handle derived liabilities
(total_assets - total_equity), and refuse cleanly with an explicit reason
when operands are missing, periods are incompatible, or growth bases are <= 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

SCALE: dict[str, float] = {
    "units": 1.0,
    "thousands": 1e3,
    "millions": 1e6,
    "billions": 1e9,
}

_MONTHS_BY_TYPE: dict[str, int] = {
    "annual": 12,
    "nine-months": 9,
    "half-yearly": 6,
    "quarterly": 3,
}
_TYPE_BY_MONTHS: dict[int, str] = {v: k for k, v in _MONTHS_BY_TYPE.items()}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "turnover", "total_income"),
    "gross_profit": ("gross_profit",),
    "operating_profit": ("operating_profit", "ebit", "operating_income"),
    "profit_before_tax": ("profit_before_tax", "pbt"),
    "net_profit": ("net_profit", "net_income", "profit_after_tax", "earnings"),
    "eps_basic": ("eps_basic", "eps"),
    "total_assets": ("total_assets", "assets"),
    "total_liabilities": ("total_liabilities", "liabilities"),
    "total_equity": ("total_equity", "equity", "shareholders_equity"),
    "current_assets": ("current_assets", "total_current_assets"),
    "current_liabilities": ("current_liabilities", "total_current_liabilities"),
    "interest_expense": ("interest_expense", "finance_cost", "finance_costs", "interest"),
}

RATIO_ALIASES: dict[str, str] = {
    "gross_margin": "gross_margin",
    "gross_margin_pct": "gross_margin",
    "gross_profit_margin": "gross_margin",
    "operating_margin": "operating_margin",
    "operating_margin_pct": "operating_margin",
    "operating_profit_margin": "operating_margin",
    "net_margin": "net_margin",
    "net_margin_pct": "net_margin",
    "net_profit_margin": "net_margin",
    "profit_margin": "net_margin",
    "revenue_growth": "revenue_growth",
    "revenue_growth_pct": "revenue_growth",
    "sales_growth": "revenue_growth",
    "earnings_growth": "earnings_growth",
    "earnings_growth_pct": "earnings_growth",
    "net_profit_growth": "earnings_growth",
    "profit_growth": "earnings_growth",
    "eps_growth": "eps_growth",
    "eps_growth_pct": "eps_growth",
    "roe": "roe",
    "return_on_equity": "roe",
    "roa": "roa",
    "return_on_assets": "roa",
    "debt_to_equity": "debt_to_equity",
    "d_e": "debt_to_equity",
    "de_ratio": "debt_to_equity",
    "current_ratio": "current_ratio",
    "interest_coverage": "interest_coverage",
    "interest_coverage_ratio": "interest_coverage",
}


@dataclass(frozen=True)
class RatioSpec:
    name: str
    required_fields: tuple[str, ...]
    n_periods: int
    unit: str
    formula: str
    optional_fields: tuple[str, ...] = ()
    description: str = ""


RATIOS: dict[str, RatioSpec] = {
    "gross_margin": RatioSpec(
        name="gross_margin",
        required_fields=("gross_profit", "revenue"),
        n_periods=1,
        unit="%",
        formula="gross_profit / revenue * 100",
        description="Gross profit as a percentage of revenue",
    ),
    "operating_margin": RatioSpec(
        name="operating_margin",
        required_fields=("operating_profit", "revenue"),
        n_periods=1,
        unit="%",
        formula="operating_profit / revenue * 100",
        description="Operating profit (EBIT) as a percentage of revenue",
    ),
    "net_margin": RatioSpec(
        name="net_margin",
        required_fields=("net_profit", "revenue"),
        n_periods=1,
        unit="%",
        formula="net_profit / revenue * 100",
        description="Net profit as a percentage of revenue",
    ),
    "revenue_growth": RatioSpec(
        name="revenue_growth",
        required_fields=("revenue",),
        n_periods=2,
        unit="%",
        formula="(revenue_current - revenue_prior) / revenue_prior * 100",
        description="Period-over-period revenue growth % (requires base > 0)",
    ),
    "earnings_growth": RatioSpec(
        name="earnings_growth",
        required_fields=("net_profit",),
        n_periods=2,
        unit="%",
        formula="(net_profit_current - net_profit_prior) / net_profit_prior * 100",
        description="Period-over-period net profit growth % (requires base > 0)",
    ),
    "eps_growth": RatioSpec(
        name="eps_growth",
        required_fields=("eps_basic",),
        n_periods=2,
        unit="%",
        formula="(eps_basic_current - eps_basic_prior) / eps_basic_prior * 100",
        description="Period-over-period basic EPS growth % (requires base > 0)",
    ),
    "roe": RatioSpec(
        name="roe",
        required_fields=("net_profit", "total_equity"),
        n_periods=2,
        unit="%",
        formula="net_profit_current / ((total_equity_current + total_equity_prior) / 2) * 100",
        description="Return on average equity %",
    ),
    "roa": RatioSpec(
        name="roa",
        required_fields=("net_profit", "total_assets"),
        n_periods=2,
        unit="%",
        formula="net_profit_current / ((total_assets_current + total_assets_prior) / 2) * 100",
        description="Return on average total assets %",
    ),
    "debt_to_equity": RatioSpec(
        name="debt_to_equity",
        required_fields=("total_liabilities", "total_equity"),
        optional_fields=("total_assets",),
        n_periods=1,
        unit="x",
        formula="total_liabilities / total_equity",
        description="Total liabilities divided by total equity (derives liabilities = assets - equity if missing)",
    ),
    "current_ratio": RatioSpec(
        name="current_ratio",
        required_fields=("current_assets", "current_liabilities"),
        n_periods=1,
        unit="x",
        formula="current_assets / current_liabilities",
        description="Current assets divided by current liabilities",
    ),
    "interest_coverage": RatioSpec(
        name="interest_coverage",
        required_fields=("operating_profit", "interest_expense"),
        n_periods=1,
        unit="x",
        formula="operating_profit / interest_expense",
        description="Operating profit (EBIT) divided by interest expense / finance cost",
    ),
}


def canonical_ratio_name(name: str) -> str | None:
    key = re.sub(r"[\s\-]+", "_", str(name).strip().lower()).strip("_")
    return RATIO_ALIASES.get(key)


def _refusal(reason: str, name: str = "", **extra: Any) -> dict[str, Any]:
    out = {"refused": True, "reason": reason}
    if name:
        out["name"] = name
    out.update(extra)
    return out


def _period_sort_key(period: str) -> tuple[int, int, int, str]:
    s = str(period).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), s)
    low = s.lower()
    if low == "current":
        return (9999, 12, 31, s)
    if low == "prior":
        return (9998, 12, 31, s)
    y = re.search(r"(20\d{2}|19\d{2})", s)
    q = re.search(r"q([1-4])", low)
    if y:
        return (int(y.group(1)), int(q.group(1)) * 3 if q else 12, 0, s)
    return (0, 0, 0, s)


def _extract_item(item: Any, field: str, period: str, meta: dict | None = None) -> dict[str, Any] | None:
    if item is None:
        return None
    meta = meta or {}
    if isinstance(item, (int, float)):
        val = float(item)
        raw = {}
    elif isinstance(item, dict):
        if item.get("value") is None:
            return None
        val = float(item["value"])
        raw = item
    else:
        v = getattr(item, "value", None)
        if v is None:
            return None
        val = float(v)
        raw = {
            "period": getattr(item, "period_end", None) or getattr(item, "period", period),
            "period_type": getattr(item, "period_type", None),
            "months": getattr(item, "months", None),
            "basis": getattr(item, "basis", None),
            "doc_id": getattr(item, "doc_id", None),
            "page": getattr(item, "page", None),
            "unit": getattr(item, "unit", None),
            "currency": getattr(item, "currency", None),
        }

    ptype = (raw.get("period_type") or meta.get("period_type") or "").strip().lower() or None
    months = raw.get("months") if raw.get("months") is not None else meta.get("months")
    if months is not None:
        months = int(months)
    if ptype is None and months in _TYPE_BY_MONTHS:
        ptype = _TYPE_BY_MONTHS[months]
    if months is None and ptype in _MONTHS_BY_TYPE:
        months = _MONTHS_BY_TYPE[ptype]

    return {
        "field": field,
        "period": str(raw.get("period") or raw.get("period_end") or period),
        "value": val,
        "doc_id": str(raw.get("doc_id") or meta.get("doc_id") or ""),
        "page": raw.get("page") if raw.get("page") is not None else meta.get("page"),
        "basis": str(raw.get("basis") or meta.get("basis") or ""),
        "period_type": ptype or "annual",
        "months": months if months is not None else 12,
        "unit": str(raw.get("unit") or meta.get("unit") or ("Rupees per share" if field == "eps_basic" else "")),
        "currency": str(raw.get("currency") or meta.get("currency") or ""),
    }


def _lookup_field(period_map: dict[str, Any], canon_field: str, period: str) -> dict[str, Any] | None:
    meta = period_map.get("_meta") if isinstance(period_map.get("_meta"), dict) else {}
    for alias in FIELD_ALIASES.get(canon_field, (canon_field,)):
        if alias in period_map and period_map[alias] is not None:
            parsed = _extract_item(period_map[alias], canon_field, period, meta)
            if parsed is not None:
                return parsed
    return None


def _public_operand(op: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": op["field"],
        "period": op["period"],
        "value": op["value"],
        "doc_id": op["doc_id"],
        "page": op["page"],
        "basis": op["basis"],
    }


def _validate_compatibility(operands: list[dict[str, Any]], spec: RatioSpec) -> Optional[str]:
    if not operands:
        return "No operands supplied."
    ptypes = {op["period_type"] for op in operands if op.get("period_type")}
    if len(ptypes) > 1:
        return (
            f"Incompatible period_type values ({', '.join(sorted(ptypes))}): "
            "cannot compare different period types (e.g. quarterly vs annual; never annualise)."
        )
    months = {op["months"] for op in operands if op.get("months") is not None}
    if len(months) > 1:
        return (
            f"Incompatible period durations ({', '.join(str(m) + ' months' for m in sorted(months))}): "
            "periods cover different numbers of months (never annualise)."
        )
    bases = {op["basis"].lower() for op in operands if op.get("basis")}
    if len(bases) > 1:
        return f"Incompatible reporting basis ({', '.join(sorted(bases))}): cannot mix consolidated and unconsolidated."
    currencies = {op["currency"].upper() for op in operands if op.get("currency")}
    if len(currencies) > 1:
        return f"Incompatible currencies ({', '.join(sorted(currencies))})."
    # Non-EPS monetary units must be either identical or convertible via SCALE
    mon_units = {
        op["unit"].lower()
        for op in operands
        if op["field"] != "eps_basic" and op.get("unit")
    }
    unknown = [u for u in mon_units if u not in SCALE]
    if len(mon_units) > 1 and unknown:
        return f"Incompatible units ({', '.join(sorted(mon_units))})."
    return None


def _scaled_value(op: dict[str, Any], target_unit: str) -> float:
    val = float(op["value"])
    if op["field"] == "eps_basic":
        return val
    src = (op.get("unit") or "").lower()
    tgt = (target_unit or "").lower()
    if src in SCALE and tgt in SCALE and src != tgt:
        return val * (SCALE[src] / SCALE[tgt])
    return val


def compute(name: str, values_by_period: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute a named ratio or growth metric from period-indexed values.

    `values_by_period` maps period key (e.g. "2026-06-30") -> dict of field values
    (either raw numeric floats or dicts with keys value, doc_id, page, basis,
    period_type, months, unit).

    Returns:
      Success: {value, formula, operands: [{field, period, value, doc_id, page, basis}], unit, name, refused: False}
      Refusal: {refused: True, reason: str, ...}
    """
    canon = canonical_ratio_name(name)
    if canon is None:
        return _refusal(f"Unknown ratio '{name}'. Supported ratios: {', '.join(RATIOS)}.", name=name)
    spec = RATIOS[canon]

    if not values_by_period:
        return _refusal(f"No period data provided for '{canon}'.", name=canon)

    periods = sorted(values_by_period.keys(), key=_period_sort_key, reverse=True)
    if spec.n_periods == 2 and len(periods) < 2:
        return _refusal(
            f"Ratio '{canon}' requires 2 periods (current and prior), but only {len(periods)} period(s) provided.",
            name=canon,
        )

    cur_p = periods[0]
    cur_map = values_by_period[cur_p]

    # Single-period ratios -------------------------------------------------
    if spec.n_periods == 1:
        if canon == "debt_to_equity":
            eq = _lookup_field(cur_map, "total_equity", cur_p)
            if eq is None:
                return _refusal(f"Missing required field 'total_equity' for period {cur_p}.", name=canon)
            liab = _lookup_field(cur_map, "total_liabilities", cur_p)
            derived = False
            if liab is not None:
                raw_ops = [liab, eq]
                formula_used = "total_liabilities / total_equity"
            else:
                assets = _lookup_field(cur_map, "total_assets", cur_p)
                if assets is None:
                    return _refusal(
                        f"Missing required field 'total_liabilities' (and fallback 'total_assets') for period {cur_p}.",
                        name=canon,
                    )
                raw_ops = [assets, eq]
                derived = True
                formula_used = "(total_assets - total_equity) / total_equity"

            compat_err = _validate_compatibility(raw_ops, spec)
            if compat_err:
                return _refusal(compat_err, name=canon)
            base_unit = raw_ops[0].get("unit") or ""
            eq_v = _scaled_value(eq, base_unit)
            if eq_v <= 0:
                return _refusal(
                    f"Total equity is {eq['value']} (<= 0) for period {cur_p}; debt-to-equity ratio is not meaningful.",
                    name=canon,
                )
            liab_v = (_scaled_value(raw_ops[0], base_unit) - eq_v) if derived else _scaled_value(raw_ops[0], base_unit)
            val = liab_v / eq_v
            return {
                "refused": False,
                "name": canon,
                "value": round(val, 4),
                "unit": spec.unit,
                "formula": formula_used,
                "operands": [_public_operand(o) for o in raw_ops],
                "basis": eq["basis"] or None,
                "period": cur_p,
            }

        # Standard 1-period two-field ratios
        f_num, f_den = spec.required_fields
        op_num = _lookup_field(cur_map, f_num, cur_p)
        if op_num is None:
            return _refusal(f"Missing required field '{f_num}' for period {cur_p}.", name=canon)
        op_den = _lookup_field(cur_map, f_den, cur_p)
        if op_den is None:
            return _refusal(f"Missing required field '{f_den}' for period {cur_p}.", name=canon)
        raw_ops = [op_num, op_den]
        compat_err = _validate_compatibility(raw_ops, spec)
        if compat_err:
            return _refusal(compat_err, name=canon)

        base_unit = op_num.get("unit") or op_den.get("unit") or ""
        num_v = _scaled_value(op_num, base_unit)
        den_v = _scaled_value(op_den, base_unit)
        if den_v <= 0 if canon in ("current_ratio", "interest_coverage") else den_v == 0:
            return _refusal(
                f"Denominator '{f_den}' is {op_den['value']} in period {cur_p}; cannot compute '{canon}'.",
                name=canon,
            )
        val = (num_v / den_v * 100.0) if spec.unit == "%" else (num_v / den_v)
        return {
            "refused": False,
            "name": canon,
            "value": round(val, 4),
            "unit": spec.unit,
            "formula": spec.formula,
            "operands": [_public_operand(o) for o in raw_ops],
            "basis": op_num["basis"] or op_den["basis"] or None,
            "period": cur_p,
        }

    # Two-period ratios ----------------------------------------------------
    prior_p = periods[1]
    prior_map = values_by_period[prior_p]

    if canon in ("revenue_growth", "earnings_growth", "eps_growth"):
        field = spec.required_fields[0]
        op_cur = _lookup_field(cur_map, field, cur_p)
        if op_cur is None:
            return _refusal(f"Missing required field '{field}' for current period {cur_p}.", name=canon)
        op_pri = _lookup_field(prior_map, field, prior_p)
        if op_pri is None:
            return _refusal(f"Missing required field '{field}' for prior period {prior_p}.", name=canon)
        raw_ops = [op_cur, op_pri]
        compat_err = _validate_compatibility(raw_ops, spec)
        if compat_err:
            return _refusal(compat_err, name=canon)

        base_unit = op_cur.get("unit") or op_pri.get("unit") or ""
        cur_v = _scaled_value(op_cur, base_unit)
        pri_v = _scaled_value(op_pri, base_unit)
        if pri_v <= 0:
            diff = round(cur_v - pri_v, 4)
            unit_lbl = base_unit or "units"
            return _refusal(
                f"Growth base for '{field}' in {prior_p} is {op_pri['value']} (<= 0); "
                f"reporting change in amount instead: {diff:+,.2f} {unit_lbl}.",
                name=canon,
                change_amount=diff,
                change_unit=unit_lbl,
                formula=f"{field}_current - {field}_prior",
                operands=[_public_operand(o) for o in raw_ops],
                basis=op_cur["basis"] or op_pri["basis"] or None,
                period=f"{cur_p} vs {prior_p}",
            )
        val = (cur_v - pri_v) / pri_v * 100.0
        return {
            "refused": False,
            "name": canon,
            "value": round(val, 4),
            "unit": spec.unit,
            "formula": spec.formula,
            "operands": [_public_operand(o) for o in raw_ops],
            "basis": op_cur["basis"] or op_pri["basis"] or None,
            "period": f"{cur_p} vs {prior_p}",
        }

    # ROE / ROA: net_profit (current) / average denominator (current & prior)
    f_num, f_den = spec.required_fields
    op_num = _lookup_field(cur_map, f_num, cur_p)
    if op_num is None:
        return _refusal(f"Missing required field '{f_num}' for current period {cur_p}.", name=canon)
    op_den_cur = _lookup_field(cur_map, f_den, cur_p)
    if op_den_cur is None:
        return _refusal(f"Missing required field '{f_den}' for current period {cur_p}.", name=canon)
    op_den_pri = _lookup_field(prior_map, f_den, prior_p)
    if op_den_pri is None:
        return _refusal(f"Missing required field '{f_den}' for prior period {prior_p}.", name=canon)

    raw_ops = [op_num, op_den_cur, op_den_pri]
    compat_err = _validate_compatibility(raw_ops, spec)
    if compat_err:
        return _refusal(compat_err, name=canon)

    base_unit = op_num.get("unit") or op_den_cur.get("unit") or ""
    num_v = _scaled_value(op_num, base_unit)
    den_cur_v = _scaled_value(op_den_cur, base_unit)
    den_pri_v = _scaled_value(op_den_pri, base_unit)
    avg_den = (den_cur_v + den_pri_v) / 2.0
    if avg_den <= 0:
        return _refusal(
            f"Average '{f_den}' across {prior_p} and {cur_p} is {avg_den:,.2f} (<= 0); cannot compute '{canon}'.",
            name=canon,
        )
    val = num_v / avg_den * 100.0
    return {
        "refused": False,
        "name": canon,
        "value": round(val, 4),
        "unit": spec.unit,
        "formula": spec.formula,
        "operands": [_public_operand(o) for o in raw_ops],
        "basis": op_num["basis"] or op_den_cur["basis"] or None,
        "period": f"{cur_p} (avg balance {prior_p}/{cur_p})",
    }
