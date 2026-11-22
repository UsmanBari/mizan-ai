"""Question answering engine with four modes (the R&D comparison):

  closed_book : LLM only, no retrieval                     (lower bound)
  rag_direct  : retrieve top-k, LLM answers AND does math  (standard RAG baseline)
  rag_calc    : retrieve top-k, LLM extracts numbers + writes an expression,
                Python computes the result                 (program-of-thought)
  agent       : LangGraph tool-calling agent (search / read_page / get_financials /
                calculate / final_answer)                  (full product)

Every mode returns the same `Answer` object (answer text, citations, calculations,
tokens, cost, latency) so they can be compared on the same test set.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional, TypedDict

from ..calculator import calculate
from ..config import get_settings
from ..llm import LLM, Usage, extract_json
from ..models import Answer, Calculation, Citation, Hit
from ..store import Store
from . import prompts as P

MODES = ("closed_book", "rag_direct", "rag_calc", "agent")
REFUSAL_PAT = re.compile(r"(could not find|cannot find|can't find|not (?:available|provided|disclosed) in|"
                         r"unable to (?:find|determine|answer)|do not contain|does not contain)", re.I)


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
        ans.refused = bool(REFUSAL_PAT.search(ans.answer))
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
        return Answer(question=q, answer=str(obj.get("answer", "")) if obj else "")

    def _retrieve(self, q, doc_ids) -> list[Hit]:
        return self.retriever.retrieve(q, self.k, doc_ids)

    def _rag_direct(self, q, doc_ids, usage):
        hits = self._retrieve(q, doc_ids)
        obj, u = self._json([{"role": "system", "content": P.RAG_DIRECT},
                             {"role": "user", "content": f"Passages:\n{P.format_passages(hits)}\n\nQuestion: {q}"}])
        usage.add(u)
        obj = obj or {}
        return Answer(question=q, answer=str(obj.get("answer", "")),
                      citations=_citations(obj.get("citations"), hits), context_pages=_pages(hits))

    def _rag_calc(self, q, doc_ids, usage):
        hits = self._retrieve(q, doc_ids)
        obj, u = self._json([{"role": "system", "content": P.RAG_CALC},
                             {"role": "user", "content": f"Passages:\n{P.format_passages(hits)}\n\nQuestion: {q}"}])
        usage.add(u)
        obj = obj or {}
        values = {}
        for v in obj.get("values") or []:
            try:
                values[_safe_name(v["name"])] = float(v["value"])
            except (KeyError, TypeError, ValueError):
                continue
        calcs: list[Calculation] = []
        template = str(obj.get("answer", ""))
        expr = obj.get("expression")
        result: Optional[float] = None
        if expr:
            expr = _rename_expr(str(expr), obj.get("values") or [])
            c = calculate(expr, values)
            calcs.append(c)
            result = c.result
        elif len(values) == 1:
            result = next(iter(values.values()))
        decimals = obj.get("decimals", 2)
        decimals = decimals if isinstance(decimals, int) and 0 <= decimals <= 6 else 2
        text = template.replace("{result}", _fmt(result, decimals) if result is not None else "[calculation failed]")
        return Answer(question=q, answer=text, calculations=calcs,
                      citations=_citations(obj.get("citations"), hits), context_pages=_pages(hits))

    def _agent(self, q, doc_ids, usage):
        ctx = {"calcs": [], "pages": [], "usage": usage}
        graph = build_agent_graph(self, doc_ids, ctx)
        docs = self.store.list_documents()
        if doc_ids:
            docs = [d for d in docs if d.doc_id in set(doc_ids)]
        doc_list = ", ".join(f"{d.doc_id} ({d.company} {d.period})" for d in docs[:60]) or "none"
        state = graph.invoke({"messages": [{"role": "system", "content": P.AGENT.format(doc_list=doc_list)},
                                           {"role": "user", "content": q}],
                              "steps": 0, "final": None},
                             {"recursion_limit": 2 * self.max_steps + 4})
        final = state.get("final") or {}
        hits_pages = ctx["pages"]
        cites = [Citation(doc_id=c.get("doc_id", ""), page=int(c.get("page", 0)))
                 for c in final.get("citations", []) if isinstance(c, dict) and str(c.get("page", "")).isdigit()]
        if not cites:
            cites = [Citation(doc_id=d, page=p) for d, p in hits_pages[:3]]
        answer = final.get("answer") or "I could not complete the analysis within the step limit."
        seen = list(dict.fromkeys(hits_pages))
        return Answer(question=q, answer=answer, citations=cites, calculations=ctx["calcs"],
                      steps=state.get("steps", 0),
                      context_pages=[Citation(doc_id=d, page=p) for d, p in seen])

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
            return fh.model_dump_json() if fh else "No extracted financials for this document."
        if name == "calculate":
            c = calculate(str(args.get("expression", "")), args.get("variables") or {})
            ctx["calcs"].append(c)
            return json.dumps({"result": c.result, "error": c.error})
        return f"Unknown tool {name}"


# --------------------------------------------------------------------- LangGraph
class AgentState(TypedDict):
    messages: list[dict]
    steps: int
    final: Optional[dict]


def build_agent_graph(engine: QAEngine, doc_ids, ctx: dict):
    """ctx holds side data (calculations, pages read, token usage) outside the graph state."""
    """agent --(tool calls)--> tools --> agent ... --(final_answer / limit)--> END"""
    from langgraph.graph import END, StateGraph

    def agent_node(state: AgentState) -> dict:
        reply = engine.llm.chat(state["messages"], tools=P.TOOLS)
        ctx["usage"].add(reply.usage)
        msgs = state["messages"] + [reply.raw_message]
        final = state["final"]
        if not reply.tool_calls and reply.content:
            final = {"answer": reply.content, "citations": []}   # model answered in plain text
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
                final = {"answer": str(args.get("answer", "")), "citations": args.get("citations", [])}
                out = "ok"
            else:
                try:
                    out = engine.tool(name, args, doc_ids, ctx)
                except Exception as e:  # tool errors go back to the model, not the user
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
# Digits that are references, not claims: document ids (LUCK_Q2026_288146) and
# page references (p. 33, pp. 12, 25, page 4). They must not count as numbers.
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


def answer_numbers(text: str) -> list[tuple[str, float]]:
    """Numbers an answer CLAIMS: (raw text, value). Skips years, values <= 1,
    document ids and page references."""
    skip = [m.span() for r in (_DOCID_RE, _PAGEREF_RE) for m in r.finditer(text)]
    out = []
    for m in _NUM_RE.finditer(text):
        if any(a <= m.start() < b for a, b in skip):
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
    # count every occurrence, as before, not just distinct numbers
    status = {e["text"]: e["status"] for e in ev}
    claims = [raw for raw, _ in answer_numbers(ans.answer)]
    return sum(status[r] != "unverified" for r in claims) / len(claims)
