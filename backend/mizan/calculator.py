"""Deterministic calculator used by the agent.

The LLM never does arithmetic itself: it finds numbers in the filings, names them
as variables and writes an expression. This module evaluates the expression with
Python's AST (no eval/exec), so results are exact and reproducible.

Example:
    calculate("(np_2025 - np_2024) / np_2024 * 100", {"np_2025": 59.6, "np_2024": 41.2})
"""
from __future__ import annotations

import ast
import math
import operator as op

from .models import Calculation

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
        ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv}
_UNARY = {ast.UAdd: op.pos, ast.USub: op.neg}
_FUNCS = {"abs": abs, "round": lambda x, n=0: round(x, int(n)), "min": min, "max": max, "sum": lambda *a: sum(a),
          "avg": lambda *a: sum(a) / len(a), "sqrt": math.sqrt, "log": math.log,
          "pct_change": lambda new, old: (new - old) / abs(old) * 100,
          "cagr": lambda end, start, years: ((end / start) ** (1 / years) - 1) * 100}


class CalcError(ValueError):
    pass


def _eval(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise CalcError(f"unknown variable '{node.id}'")
        return float(env[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise CalcError("exponent too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        return float(_FUNCS[node.func.id](*[_eval(a, env) for a in node.args]))
    raise CalcError(f"unsupported expression element: {type(node).__name__}")


def calculate(expression: str, variables: dict[str, float] | None = None) -> Calculation:
    variables = {k: float(v) for k, v in (variables or {}).items()}
    calc = Calculation(expression=expression, variables=variables)
    if len(expression) > 500:
        calc.error = "expression too long"
        return calc
    try:
        # thousands separators are not allowed inside expressions ("1,577" would be
        # a tuple); numbers must be passed as variables or written without commas
        tree = ast.parse(expression, mode="eval")
        calc.result = _eval(tree, variables)
        if math.isnan(calc.result) or math.isinf(calc.result):
            raise CalcError("result is not a finite number")
    except ZeroDivisionError:
        calc.result, calc.error = None, "division by zero"
    except (CalcError, SyntaxError, TypeError, ValueError, OverflowError) as e:
        calc.result, calc.error = None, str(e)
    return calc


def parse_number(text: str) -> float | None:
    """Parse numbers as printed in financial statements:
    '1,577' -> 1577 ; '(1,577)' -> -1577 ; 'Rs. 3.42' -> 3.42 ; '12.5%' -> 12.5"""
    s = str(text).strip().replace("Rs.", "").replace("Rs", "").replace("$", "")
    s = s.replace("PKR", "").replace("USD", "").replace("%", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s.startswith("-") or s.startswith("−"):
        neg, s = True, s[1:]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v
