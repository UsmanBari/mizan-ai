"""Question answering engine with four modes (the R&D comparison):

  closed_book : LLM only, no retrieval                     (lower bound)
  rag_direct  : retrieve top-k, LLM answers AND does math  (standard RAG baseline)
  rag_calc    : retrieve top-k, LLM extracts numbers + writes an expression,
                Python computes the result                 (program-of-thought)
  agent       : LangGraph tool-calling agent (compute_ratio / search / read_page /
                get_financials / calculate / final_answer) (full product)

Every mode returns the same `Answer` object (answer text, three-part breakdown
[reported_figures, calculated_values, explanation], citations, calculations,
tokens, cost, latency, refusal_reason) so they can be compared on the same test set.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional, TypedDict

from ..calculator import calculate
from ..config import get_settings
from ..llm import LLM, Usage, extract_json
from ..models import Answer, Calculation, Citation, FinancialFact, Hit
from ..ratios import FIELD_ALIASES, RATIOS, canonical_ratio_name, compute as compute_ratio_fn
from ..store import Store
from . import prompts as P

MODES = ("closed_book", "rag_direct", "rag_calc", "agent")
REFUSAL_PAT = re.compile(
    r"(could not find|cannot find|can't find|not (?:available|provided|disclosed|reported|found|stated) in|"
    r"unable to (?:find|determine|answer|compute)|do not contain|does not contain|"
    r"cannot (?:answer|compare|compute)|missing operand|conflicting values|incompatible period|"
    r"abstain|insufficient (?:information|evidence|data)|no (?:verified )?(?:facts|data|records) found)",
    re.I,
)
DEFAULT_EXPLANATION = "The report does not state a reason."

_UNCONSOL_PAT = re.compile(r"\b(standalone|unconsolidated|company[- ]only)\b", re.I)
_CONSOL_PAT = re.compile(r"\bconsolidated\b", re.I)
_SUBANNUAL_PAT = re.compile(r"\b(q[1-4]|quarterly|quarter|half[- ]year(?:ly)?|6[- ]month|3[- ]month|9[- ]month)\b", re.I)
_ANNUAL_PAT = re.compile(r"\b(annual|full[- ]year|12[- ]month)\b", re.I)
_COMPARE_PAT = re.compile(r"\b(compare|compar(?:ed|ing)|vs\.?|versus|growth|change|between|difference)\b", re.I)


def detect_requested_basis(question: str) -> Optional[str]:
    """Basis rule: 'standalone/unconsolidated/company-only' -> unconsolidated;
    explicit 'consolidated' -> consolidated; else None (prefer consolidated if it exists)."""
    if _UNCONSOL_PAT.search(question):
        return "unconsolidated"
    if _CONSOL_PAT.search(question):
        return "consolidated"
    return None


def detect_period_mismatch(question: str) -> Optional[str]:
    """Detect explicit cross-frequency comparisons (e.g. quarterly vs annual)."""
    if _SUBANNUAL_PAT.search(question) and _ANNUAL_PAT.search(question) and _COMPARE_PAT.search(question):
        return (
            "Incompatible periods: question compares a sub-annual period (quarterly/half-yearly) "
            "with an annual/full-year period (never annualise or compare across different durations)."
        )
    return None


def resolve_basis_for_symbol(
    store: Store,
    symbol: str,
    requested: Optional[str] = None,
    period: Optional[str] = None,
) -> Optional[str]:
    """Return requested basis if specified, else 'consolidated' if any exists, else 'unconsolidated'."""
    facts = store.get_facts(symbol=symbol)
    if period:
        pf = _filter_period_facts(facts, period)
        if pf:
            facts = pf
    bases = {f.basis for f in facts}
    if requested:
        return requested
    if "consolidated" in bases:
        return "consolidated"
    if "unconsolidated" in bases:
        return "unconsolidated"
    return None


def _filter_period_facts(facts: list[FinancialFact], period: str) -> list[FinancialFact]:
    p = str(period).strip()
    exact = [f for f in facts if f.period_end == p]
    if exact:
        return exact
    yr = re.search(r"(20\d{2}|19\d{2})", p)
    if yr:
        y = yr.group(1)
        return [f for f in facts if f.period_end.startswith(y)]
    return []


def _statement_for_field(field: str, basis: Optional[str]) -> str:
    b = (basis or "consolidated").capitalize()
    is_fields = {
        "revenue", "cost_of_sales", "gross_profit", "operating_profit",
        "profit_before_tax", "net_profit", "eps_basic", "interest_expense", "finance_cost",
    }
    if field in is_fields:
        return f"{b} Statement of Profit or Loss"
    return f"{b} Statement of Financial Position"


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def verify_explanation(raw_exp: str, citations: list[Citation], context_pages: list[Citation], store: Store) -> str:
    """Keep explanation only if quoted/grounded verbatim in cited/retrieved pages;
    otherwise return 'The report does not state a reason.'"""
    if not raw_exp or not raw_exp.strip():
        return DEFAULT_EXPLANATION
    low = raw_exp.lower()
    if "does not state a reason" in low or "does not state any reason" in low:
        return DEFAULT_EXPLANATION
    pages = list(citations) + [c for c in context_pages if (c.doc_id, c.page) not in {(x.doc_id, x.page) for x in citations}]
    page_texts = [_norm_ws(store.get_page(c.doc_id, c.page) or "") for c in pages]
    joined = " \n ".join(t for t in page_texts if t)
    if not joined:
        return DEFAULT_EXPLANATION
    quotes = [q.strip() for q in re.findall(r'"([^"]{8,})"|\'([^\']{8,})\'', raw_exp) for q in q if q]
    if quotes:
        for q in quotes:
            if _norm_ws(q) in joined:
                return raw_exp.strip()
        return DEFAULT_EXPLANATION
    # Accept if at least one 5-word span from raw_exp appears verbatim in cited/retrieved text
    words = re.findall(r"[a-z0-9]+", raw_exp.lower())
    for i in range(max(0, len(words) - 4)):
        span = " ".join(words[i:i + 5])
        if span in joined:
            return raw_exp.strip()
    return DEFAULT_EXPLANATION


def _facts_to_values_by_period(facts: list[FinancialFact]) -> dict[str, dict[str, dict]]:
    vbp: dict[str, dict[str, dict]] = {}
    for f in facts:
        pdict = vbp.setdefault(f.period_end, {})
        # If multiple non-conflicting entries exist, prefer verified human label
        if f.field in pdict and pdict[f.field].get("source") == "label" and f.source != "label":
            continue
        pdict[f.field] = {
            "value": f.value,
            "period": f.period_end,
            "period_type": f.period_type,
            "months": f.months,
            "basis": f.basis,
            "doc_id": f.doc_id,
            "page": f.page,
            "unit": f.unit,
            "source": f.source,
        }
    return vbp


def _fields_for_ratio(canon: str) -> list[str]:
    spec = RATIOS[canon]
    fields = list(spec.required_fields) + list(spec.optional_fields)
    # include aliases just in case
    expanded = set()
    for f in fields:
        expanded.add(f)
        for a in FIELD_ALIASES.get(f, ()):
            expanded.add(a)
    return list(expanded)


def format_conflict_message(conflicts: list[dict]) -> str:
    parts = []
    for c in conflicts:
        vals = "; ".join(
            f"{v['value']:,.2f} {v.get('unit', '')} ({v.get('doc_id') or 'doc'} p.{v.get('page')}, {v.get('source')})".strip()
            for v in c["values"]
        )
        parts.append(f"{c['symbol']} {c['field']} ({c['period_end']}, {c['basis']}): {vals}")
    return "Conflicting values found (>0.5% difference): " + " | ".join(parts)


class QAEngine:
    def __init__(self, store: Store, retriever, llm: LLM, k: int | None = None,
                 max_steps: int | None = None) -> None:
        s = get_settings()
        self.store, self.retriever, self.llm = store, retriever, llm
        self.k = k or s.top_k
        self.max_steps = max_steps or s.agent_max_steps

    # ------------------------------------------------------------------ public
    def answer(self, question: str, mode: str = "agent", doc_ids: list[str] | None = None) -> Answer:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        t0 = time.perf_counter()
        usage = Usage()
        ans = getattr(self, f"_{mode}")(question, doc_ids, usage)
        ans.mode = mode
        ans.latency_s = round(time.perf_counter() - t0, 3)
        ans.tokens_in, ans.tokens_out = usage.tokens_in, usage.tokens_out
        ans.cost_usd = round(usage.cost(self.llm.price_in, self.llm.price_out), 6)
        if not ans.refused and REFUSAL_PAT.search(ans.answer):
            ans.refused = True
        if ans.refused and not ans.refusal_reason:
            ans.refusal_reason = ans.answer[:300]
        if not ans.explanation:
            ans.explanation = DEFAULT_EXPLANATION
        try:
            self.store.log_answer(ans)
        except Exception:
            pass
        return ans

    # ------------------------------------------------------------------ modes
    def _closed_book(self, q, doc_ids, usage):
        obj, u = self._json([{"role": "system", "content": P.CLOSED_BOOK},
                             {"role": "user", "content": q}])
        usage.add(u)
        return Answer(question=q, answer=str(obj.get("answer", "")) if obj else "",
                      explanation=DEFAULT_EXPLANATION)

    def _retrieve(self, q, doc_ids) -> list[Hit]:
        return self.retriever.retrieve(q, self.k, doc_ids)

    def _rag_direct(self, q, doc_ids, usage):
        hits = self._retrieve(q, doc_ids)
        obj, u = self._json([{"role": "system", "content": P.RAG_DIRECT},
                             {"role": "user", "content": f"Passages:\n{P.format_passages(hits)}\n\nQuestion: {q}"}])
        usage.add(u)
        obj = obj or {}
        cites = _citations(obj.get("citations"), hits)
        ctx_pages = _pages(hits)
        exp = verify_explanation(str(obj.get("explanation", "")), cites, ctx_pages, self.store)
        return Answer(
            question=q,
            answer=str(obj.get("answer", "")),
            citations=cites,
            context_pages=ctx_pages,
            explanation=exp,
            basis=detect_requested_basis(q),
        )

    def _rag_calc(self, q, doc_ids, usage):
        hits = self._retrieve(q, doc_ids)
        obj, u = self._json([{"role": "system", "content": P.RAG_CALC},
                             {"role": "user", "content": f"Passages:\n{P.format_passages(hits)}\n\nQuestion: {q}"}])
        usage.add(u)
        obj = obj or {}
        req_basis = detect_requested_basis(q)
        values = {}
        reported: list[dict] = []
        for v in obj.get("values") or []:
            try:
                num_v = float(v["value"])
                name = _safe_name(v["name"])
                values[name] = num_v
                reported.append({
                    "field": str(v.get("name", name)),
                    "value": num_v,
                    "unit": str(v.get("unit", "")),
                    "statement": str(v.get("statement", "")),
                    "period": str(v.get("period", "")),
                    "page": int(v["page"]) if str(v.get("page", "")).isdigit() else None,
                    "doc_id": str(v.get("doc_id", "")),
                })
            except (KeyError, TypeError, ValueError):
                continue
        calcs: list[Calculation] = []
        calc_vals: list[dict] = []
        template = str(obj.get("answer", ""))
        expr = obj.get("expression")
        result: Optional[float] = None
        calc_err: Optional[str] = None
        if expr:
            expr = _rename_expr(str(expr), obj.get("values") or [])
            c = calculate(expr, values)
            calcs.append(c)
            result = c.result
            calc_err = c.error
            calc_vals.append({
                "name": "rag_calc",
                "formula": expr,
                "operands": reported,
                "result": result,
            })
        elif len(values) == 1:
            result = next(iter(values.values()))
        decimals = obj.get("decimals", 2)
        decimals = decimals if isinstance(decimals, int) and 0 <= decimals <= 6 else 2
        text = template.replace("{result}", _fmt(result, decimals) if result is not None else "[calculation failed]")

        cites = _citations(obj.get("citations"), hits)
        ctx_pages = _pages(hits)
        exp = verify_explanation(str(obj.get("explanation", "")), cites, ctx_pages, self.store)

        # Deterministic abstention on period mismatch or calculation failure
        mismatch = detect_period_mismatch(q)
        refused = bool(REFUSAL_PAT.search(text))
        refusal_reason = None
        if mismatch:
            refused = True
            refusal_reason = mismatch
            text = f"Cannot answer: {mismatch}"
        elif calc_err:
            refused = True
            refusal_reason = f"Calculation failed: {calc_err}"

        return Answer(
            question=q,
            answer=text,
            calculations=calcs,
            citations=cites,
            context_pages=ctx_pages,
            reported_figures=reported,
            calculated_values=calc_vals,
            explanation=exp,
            refused=refused,
            refusal_reason=refusal_reason,
            basis=req_basis,
        )

    def _agent(self, q, doc_ids, usage):
        req_basis = detect_requested_basis(q)
        mismatch = detect_period_mismatch(q)
        if mismatch:
            return Answer(
                question=q,
                answer=f"Cannot answer: {mismatch}",
                explanation=DEFAULT_EXPLANATION,
                refused=True,
                refusal_reason=mismatch,
                basis=req_basis,
            )

        ctx = {
            "calcs": [],
            "pages": [],
            "usage": usage,
            "reported_figures": [],
            "calculated_values": [],
            "conflicts": [],
            "period_mismatches": [],
            "missing_operands": [],
            "requested_basis": req_basis,
            "basis": req_basis,
            "question": q,
        }
        graph = build_agent_graph(self, doc_ids, ctx)
        docs = self.store.list_documents()
        if doc_ids:
            docs = [d for d in docs if d.doc_id in set(doc_ids)]
        doc_list = ", ".join(f"{d.doc_id} ({d.company} {d.period})" for d in docs[:60]) or "none"
        state = graph.invoke(
            {
                "messages": [
                    {"role": "system", "content": P.AGENT.format(doc_list=doc_list)},
                    {"role": "user", "content": q},
                ],
                "steps": 0,
                "final": None,
            },
            {"recursion_limit": 2 * self.max_steps + 4},
        )
        final = state.get("final") or {}
        hits_pages = ctx["pages"]
        cites = [
            Citation(doc_id=c.get("doc_id", ""), page=int(c.get("page", 0)))
            for c in final.get("citations", [])
            if isinstance(c, dict) and str(c.get("page", "")).isdigit()
        ]
        if not cites:
            seen_first = list(dict.fromkeys((d, p) for d, p in hits_pages if p))
            cites = [Citation(doc_id=d, page=p) for d, p in seen_first[:3]]

        answer = final.get("answer") or "I could not complete the analysis within the step limit."
        seen = list(dict.fromkeys(hits_pages))
        ctx_pages = [Citation(doc_id=d, page=p) for d, p in seen]

        # Build structured three-part answer
        reported = list(ctx["reported_figures"])
        for rf in final.get("reported_figures") or []:
            if isinstance(rf, dict) and "field" in rf:
                reported.append(rf)
        calculated = list(ctx["calculated_values"])
        if not calculated:
            for c in ctx["calcs"]:
                calculated.append({
                    "name": "calculation",
                    "formula": c.expression,
                    "operands": [{"field": k, "value": v} for k, v in c.variables.items()],
                    "result": c.result,
                })
            for cv in final.get("calculated_values") or []:
                if isinstance(cv, dict) and cv not in calculated:
                    calculated.append(cv)

        raw_exp = str(final.get("explanation") or "")
        exp = verify_explanation(raw_exp, cites, ctx_pages, self.store)

        # Deterministic abstention guards before returning ----------------------
        refused = bool(final.get("refused")) or bool(REFUSAL_PAT.search(answer))
        refusal_reason = final.get("refusal_reason")

        if ctx["conflicts"]:
            refused = True
            msg = format_conflict_message(ctx["conflicts"])
            refusal_reason = msg
            answer = f"Cannot determine a single value due to conflicting facts. {msg}"
        elif ctx["period_mismatches"]:
            refused = True
            refusal_reason = ctx["period_mismatches"][0]
            answer = f"Cannot answer due to incompatible periods: {refusal_reason}"
        elif ctx["missing_operands"] and not ctx["calcs"] and not final.get("reported_figures") and not ctx["reported_figures"]:
            # compute_ratio couldn't find required facts AND agent produced no verified calc from PDFs
            if not refused:
                refused = True
                refusal_reason = ctx["missing_operands"][0]
                answer = f"Cannot answer: {refusal_reason}"
        elif ctx["calcs"] and all(c.result is None for c in ctx["calcs"]):
            refused = True
            refusal_reason = next((c.error for c in ctx["calcs"] if c.error), "Calculation failed.")

        # Requested basis guard against known facts
        if not refused and req_basis:
            facts_for_syms = []
            for d in docs:
                if d.symbol and (d.symbol.lower() in q.lower() or d.company.lower() in q.lower()):
                    facts_for_syms.extend(self.store.get_facts(symbol=d.symbol))
            if facts_for_syms:
                avail_bases = {f.basis for f in facts_for_syms}
                if req_basis not in avail_bases and not ctx["reported_figures"] and not ctx["calcs"]:
                    refused = True
                    refusal_reason = f"Requested {req_basis} basis is not available; only {', '.join(sorted(avail_bases))} figures are reported."
                    answer = f"Cannot answer: {refusal_reason}"

        basis = ctx.get("basis") or final.get("basis") or req_basis
        return Answer(
            question=q,
            answer=answer,
            citations=cites,
            calculations=ctx["calcs"],
            context_pages=ctx_pages,
            reported_figures=reported,
            calculated_values=calculated,
            explanation=exp,
            refused=refused,
            refusal_reason=refusal_reason,
            basis=basis,
            steps=state.get("steps", 0),
        )

    # ------------------------------------------------------------------ helpers
    def _json(self, messages) -> tuple[dict | None, Usage]:
        reply = self.llm.chat(messages, json_mode=True)
        try:
            obj = extract_json(reply.content)
            return (obj if isinstance(obj, dict) else {"answer": str(obj)}), reply.usage
        except ValueError:
            return {"answer": reply.content}, reply.usage

    # tools used by the agent -------------------------------------------------
    def tool(self, name: str, args: dict, doc_ids, ctx: dict) -> str:
        if name == "compute_ratio":
            return self._tool_compute_ratio(args, ctx)
        if name == "search_filings":
            scope = [args["doc_id"]] if args.get("doc_id") else doc_ids
            k = int(args.get("k") or self.k)
            hits = self.retriever.retrieve(str(args.get("query", "")), max(1, min(k, 10)), scope)
            ctx["pages"].extend((h.chunk.doc_id, h.chunk.page) for h in hits)
            return P.format_passages(hits) or "No passages found."
        if name == "read_page":
            text = self.store.get_page(str(args.get("doc_id")), int(args.get("page", 0)))
            if text is None:
                return "Page not found."
            ctx["pages"].append((str(args.get("doc_id")), int(args.get("page", 0))))
            return text[:6000]
        if name == "get_financials":
            fh = self.store.get_financials(str(args.get("doc_id")))
            if not fh:
                return "No extracted financials for this document."
            basis = "consolidated" if fh.consolidated else "unconsolidated"
            ctx["basis"] = ctx.get("basis") or basis
            return fh.model_dump_json()
        if name == "calculate":
            c = calculate(str(args.get("expression", "")), args.get("variables") or {})
            ctx["calcs"].append(c)
            return json.dumps({"result": c.result, "error": c.error})
        return f"Unknown tool {name}"

    def _tool_compute_ratio(self, args: dict, ctx: dict) -> str:
        ratio_name = str(args.get("name", ""))
        symbol = str(args.get("symbol", "")).upper().strip()
        period = str(args.get("period") or "").strip() or None
        req_basis = ctx.get("requested_basis")
        arg_basis = args.get("basis")
        basis = req_basis or resolve_basis_for_symbol(self.store, symbol, requested=arg_basis, period=period)

        canon = canonical_ratio_name(ratio_name)
        if canon is None:
            return json.dumps({"refused": True, "reason": f"Unknown ratio '{ratio_name}'."})

        all_facts = self.store.get_facts(symbol=symbol, basis=basis) if basis else self.store.get_facts(symbol=symbol)
        if not all_facts:
            reason = f"No verified facts found for {symbol}" + (f" ({basis} basis)" if basis else "") + "."
            ctx["missing_operands"].append(reason)
            return json.dumps({"refused": True, "missing": True, "reason": reason})

        # Period existence check if a specific period was requested
        if period:
            matched_period = _filter_period_facts(all_facts, period)
            if not matched_period:
                reason = f"Period '{period}' is not in verified facts for {symbol} ({basis})."
                ctx["missing_operands"].append(reason)
                return json.dumps({"refused": True, "missing": True, "period_missing": True, "reason": reason})
            target_end = max(f.period_end for f in matched_period)
            target_types = {f.period_type for f in matched_period}
            facts = [f for f in all_facts if f.period_end <= target_end and (len(target_types) > 1 or f.period_type in target_types)]
        else:
            facts = all_facts

        # Check conflicts on any required field for this ratio
        rel_fields = set(_fields_for_ratio(canon))
        conflicts = [
            c for c in self.store.fact_conflicts(symbol=symbol, basis=basis)
            if c["field"] in rel_fields and c["period_end"] in {f.period_end for f in facts}
        ]
        if conflicts:
            ctx["conflicts"].extend(conflicts)
            msg = format_conflict_message(conflicts)
            return json.dumps({"refused": True, "conflict": True, "reason": msg, "conflicts": conflicts})

        vbp = _facts_to_values_by_period(facts)
        res = compute_ratio_fn(canon, vbp)
        ctx["basis"] = basis
        if res.get("refused"):
            reason = res["reason"]
            if "incompatible period" in reason.lower() or "different numbers of months" in reason.lower():
                ctx["period_mismatches"].append(reason)
            elif "change_amount" in res:
                # Base <= 0 fallback: record change_amount in trace so agent can state it cleanly
                ops = res.get("operands", [])
                ctx["reported_figures"].extend([
                    {
                        "field": o["field"],
                        "value": o["value"],
                        "unit": next((f.unit for f in facts if f.field == o["field"] and f.period_end == o["period"]), ""),
                        "statement": _statement_for_field(o["field"], o.get("basis") or basis),
                        "period": o["period"],
                        "page": o.get("page"),
                    }
                    for o in ops
                ])
                ctx["calculated_values"].append({
                    "name": f"{canon}_change_amount",
                    "formula": res["formula"],
                    "operands": ops,
                    "result": res["change_amount"],
                    "note": reason,
                })
                ctx["calcs"].append(Calculation(
                    expression=res["formula"],
                    variables={f"{o['field']}_{o['period'].replace('-', '_')}": o["value"] for o in ops},
                    result=res["change_amount"],
                ))
                for o in ops:
                    if o.get("doc_id") and o.get("page"):
                        ctx["pages"].append((o["doc_id"], int(o["page"])))
            else:
                ctx["missing_operands"].append(reason)
            return json.dumps(res)

        ops = res["operands"]
        for o in ops:
            unit = next((f.unit for f in facts if f.field == o["field"] and f.period_end == o["period"]), "")
            ctx["reported_figures"].append({
                "field": o["field"],
                "value": o["value"],
                "unit": unit,
                "statement": _statement_for_field(o["field"], o.get("basis") or basis),
                "period": o["period"],
                "page": o.get("page"),
            })
            if o.get("doc_id") and o.get("page"):
                ctx["pages"].append((o["doc_id"], int(o["page"])))
        ctx["calculated_values"].append({
            "name": res["name"],
            "formula": res["formula"],
            "operands": ops,
            "result": res["value"],
        })
        ctx["calcs"].append(Calculation(
            expression=res["formula"],
            variables={f"{o['field']}_{o['period'].replace('-', '_')}": o["value"] for o in ops},
            result=res["value"],
        ))
        return json.dumps(res)


# --------------------------------------------------------------------- LangGraph
class AgentState(TypedDict):
    messages: list[dict]
    steps: int
    final: Optional[dict]


def build_agent_graph(engine: QAEngine, doc_ids, ctx: dict):
    """ctx holds side data (calculations, pages read, token usage) outside the graph state."""
    from langgraph.graph import END, StateGraph

    def agent_node(state: AgentState) -> dict:
        reply = engine.llm.chat(state["messages"], tools=P.TOOLS)
        ctx["usage"].add(reply.usage)
        msgs = state["messages"] + [reply.raw_message]
        final = state["final"]
        if not reply.tool_calls and reply.content:
            final = {"answer": reply.content, "citations": []}
        return {"messages": msgs, "steps": state["steps"] + 1, "final": final}

    def tools_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        msgs = list(state["messages"])
        final = state["final"]
        for tc in last.get("tool_calls", []):
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "final_answer":
                final = {
                    "answer": str(args.get("answer", "")),
                    "citations": args.get("citations", []),
                    "reported_figures": args.get("reported_figures", []),
                    "calculated_values": args.get("calculated_values", []),
                    "explanation": args.get("explanation", ""),
                    "refused": args.get("refused", False),
                    "refusal_reason": args.get("refusal_reason"),
                    "basis": args.get("basis"),
                }
                out = "ok"
            else:
                try:
                    out = engine.tool(name, args, doc_ids, ctx)
                except Exception as e:
                    out = f"Tool error: {e}"
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
        return {"messages": msgs, "final": final}

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if state["final"] is not None and not last.get("tool_calls"):
            return END
        if state["steps"] >= engine.max_steps:
            return END
        return "tools" if last.get("tool_calls") else END

    def route_after_tools(state: AgentState) -> str:
        return END if state["final"] is not None else "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", route_after_tools, {"agent": "agent", END: END})
    return g.compile()


# --------------------------------------------------------------------- utils
def _safe_name(name: str) -> str:
    n = re.sub(r"\W+", "_", str(name)).strip("_") or "v"
    return n if not n[0].isdigit() else f"v_{n}"


def _rename_expr(expr: str, values: list[dict]) -> str:
    for v in values:
        raw = str(v.get("name", ""))
        safe = _safe_name(raw)
        if raw and raw != safe:
            expr = re.sub(rf"(?<!\w){re.escape(raw)}(?!\w)", safe, expr)
    return expr


def _fmt(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}"


def _pages(hits: list[Hit]) -> list[Citation]:
    seen = dict.fromkeys((h.chunk.doc_id, h.chunk.page) for h in hits)
    return [Citation(doc_id=d, page=p) for d, p in seen]


def _citations(raw, hits: list[Hit]) -> list[Citation]:
    out = []
    for c in raw or []:
        try:
            out.append(Citation(doc_id=str(c["doc_id"]), page=int(c["page"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not out and hits:
        out = [Citation(doc_id=hits[0].chunk.doc_id, page=hits[0].chunk.page)]
    return out


def numbers_in(text: str) -> list[float]:
    vals = []
    for m in re.findall(r"\(?-?\$?\d[\d,]*\.?\d*\)?", text):
        s = m.replace("$", "").replace(",", "")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            v = float(s)
        except ValueError:
            continue
        vals.append(-v if neg else v)
    return vals


_NUM_RE = re.compile(r"\(?-?\$?\d(?:[\d,]*\d)?(?:\.\d+)?\)?")
_DOCID_RE = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Za-z0-9_]+")
_PAGEREF_RE = re.compile(r"\b(?:pp?\.|pages?)\s*\d+(?:\s*(?:[-–,]|and)\s*\d+)*", re.I)


def _parse_num(raw: str) -> float | None:
    s = raw.replace("$", "").replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


# "June 30, 2026", "30 June 2026", "Sep. 30": the day of a date is not a figure
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_RE = re.compile(rf"(?i)\b{_MON}\s+\d{{1,2}}(?:st|nd|rd|th)?\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MON}(?=\s|,|$)")


def answer_numbers(text: str) -> list[tuple[str, float]]:
    """Numbers an answer CLAIMS: (raw text, value). Skips years, values <= 1,
    dates, document ids and page references."""
    skip = [m.span() for r in (_DOCID_RE, _PAGEREF_RE) for m in r.finditer(text)]
    dates = [m.span() for m in _DATE_RE.finditer(text)]
    out = []
    for m in _NUM_RE.finditer(text):
        if any(a <= m.start() < b for a, b in skip) or any(a < m.end() and m.start() < b for a, b in dates):
            continue
        v = _parse_num(m.group())
        if v is None or abs(v) <= 1 or (1990 <= abs(v) <= 2035 and float(v).is_integer()):
            continue
        out.append((m.group(), v))
    return out


def _close(n: float, p: float) -> bool:
    return abs(n - p) <= 0.005 * max(abs(n), 1e-9) or abs(abs(n) - abs(p)) <= 0.005 * abs(n)


def number_evidence(ans: Answer, store: Store) -> list[dict]:
    """Where each claimed number in the answer comes from (deterministic, same rule
    as grounding_check):
      computed   - result (or input) of a calculator call
      found      - printed on a cited page (doc_id, page and the raw text matched)
      unverified - neither: the UI flags it for the reader to check"""
    calc_results = [(i, c.result) for i, c in enumerate(ans.calculations) if c.result is not None]
    calc_inputs = [(i, v) for i, c in enumerate(ans.calculations) for v in c.variables.values()]
    pages = []
    for cit in ans.citations:
        text = store.get_page(cit.doc_id, cit.page) or ""
        pages.append((cit, [(m.group(), _parse_num(m.group())) for m in _NUM_RE.finditer(text)]))
    out, seen = [], set()
    for raw, n in answer_numbers(ans.answer):
        if raw in seen:
            continue
        seen.add(raw)
        item = {"text": raw, "value": n, "status": "unverified"}
        hit = next((i for i, r in calc_results if _close(n, r)), None)
        if hit is not None:
            item.update(status="computed", calc=hit)
        else:
            loc = next(((cit, r) for cit, nums in pages for r, v in nums if v is not None and _close(n, v)), None)
            if loc:
                item.update(status="found", doc_id=loc[0].doc_id, page=loc[0].page, match=loc[1])
            else:
                hit = next((i for i, v in calc_inputs if _close(n, v)), None)
                if hit is not None:
                    item.update(status="computed", calc=hit)
        out.append(item)
    return out


def grounding_check(ans: Answer, store: Store) -> float:
    """Deterministic groundedness: share of numbers in the answer that appear on a
    cited page or are the result of a calculator call (tolerance 0.5%). Years, tiny
    integers, document ids and page references are ignored. Returns 1.0 when the
    answer has no numbers."""
    ev = number_evidence(ans, store)
    if not ev:
        return 1.0
    status = {e["text"]: e["status"] for e in ev}
    claims = [raw for raw, _ in answer_numbers(ans.answer)]
    return sum(status[r] != "unverified" for r in claims) / len(claims)
