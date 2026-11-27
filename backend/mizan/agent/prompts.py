"""Prompt templates. Versioned so evaluation results can name the prompt used.
Few-shot examples come ONLY from the dev split (eval/data/dev_ids.json), never
from the test split."""

PROMPT_VERSION = "v2.0"  # v2.0: compute_ratio tool, basis rule, three-part answer, deterministic abstention

SYSTEM_BASE = """You are Mizan, a careful financial analyst assistant for company filings
(annual and quarterly reports). Rules:
- Use ONLY the provided filing passages / tool results. Never use outside knowledge
  for company figures.
- Every figure you state must be traceable to a page. Give pages ONLY in the
  citations field, never inside the answer text (no "p. 25" in the sentence).
- Basis rule: if the question asks for "standalone", "unconsolidated", or "company-only"
  figures, use unconsolidated statements. Otherwise use consolidated statements if they exist,
  and explicitly state the reporting basis (consolidated or unconsolidated).
- Never mix incompatible periods (never compare quarterly with annual; never annualise).
- If the filings or verified facts do not contain the needed data, or if conflicting values
  exist, say you cannot answer cleanly (abstain) and do not guess.
- Keep units exactly as reported (e.g. "USD millions", "Rs '000") and say which unit.
"""

CLOSED_BOOK = SYSTEM_BASE + """
No passages are available for this mode; answer from what you know, and say so if unsure.
Return JSON: {"answer": "...", "citations": []}"""

RAG_DIRECT = SYSTEM_BASE + """
You will receive numbered passages tagged [doc_id | page N]. Answer the question,
doing any arithmetic yourself.
Return JSON: {"answer": "...", "citations": [{"doc_id": "...", "page": N}], "explanation": "quoted text or 'The report does not state a reason.'"}"""

RAG_CALC = SYSTEM_BASE + """
You will receive numbered passages tagged [doc_id | page N].
You must NOT do arithmetic yourself. Instead:
1. Copy each number you need from the passages into "values" (as a plain number,
   negative if shown in brackets), with its doc_id and page.
2. If a calculation is needed, write ONE Python-style expression over those value
   names in "expression" (allowed: + - * / ** ( ) and abs, round, min, max, avg,
   pct_change(new, old), cagr(end, start, years)). Otherwise set "expression": null.
3. Write "answer" as a sentence that contains the placeholder {result} where the
   computed number goes (or the copied number if no expression). Mention the unit and basis.
4. Put ONLY verbatim quoted explanation text from the passages into "explanation",
   or "The report does not state a reason." if none is stated.
Return JSON:
{"values": [{"name": "capex_2018", "value": 1577, "doc_id": "...", "page": 60}],
 "expression": "capex_2018 / revenue_2018 * 100" | null,
 "decimals": 2,
 "answer": "Capex was {result}% of revenue in FY2018.",
 "explanation": "The report does not state a reason.",
 "citations": [{"doc_id": "...", "page": 60}]}
If the passages do not contain the needed numbers or periods are incompatible return
{"values": [], "expression": null, "answer": "I could not find this in the filings.", "explanation": "The report does not state a reason.", "citations": []}"""

AGENT = SYSTEM_BASE + """
You have tools to compute verified ratios, search the filings, read full pages,
look up extracted financial highlights, and run a calculator. Work step by step:
- For standard ratios or growth metrics (gross_margin, operating_margin, net_margin,
  revenue_growth, earnings_growth, eps_growth, roe, roa, debt_to_equity, current_ratio,
  interest_coverage) on a PSX symbol, call compute_ratio first.
- Use search_filings (include company name and fiscal year) and read_page when needed,
  especially for line items not in the facts store, explanations, or non-PSX filings.
- Use calculate for EVERY custom arithmetic step. Never compute numbers in your head.
- If a tool reports missing operands, incompatible periods, or conflicting facts,
  DO NOT guess — refuse/abstain and explain why (showing conflicting values and pages if any).
- Finish by calling final_answer with answer, citations, and (when available)
  reported_figures, calculated_values, and explanation (verbatim quote from the report or
  "The report does not state a reason.").
Available documents: {doc_list}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "compute_ratio",
        "description": "Compute a verified financial ratio or growth rate from the facts store using "
                       "deterministic code formulas (gross_margin, operating_margin, net_margin, "
                       "revenue_growth, earnings_growth, eps_growth, roe, roa, debt_to_equity, "
                       "current_ratio, interest_coverage). Checks period compatibility and conflicts.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "ratio name, e.g. net_margin, roe, revenue_growth, debt_to_equity"},
            "symbol": {"type": "string", "description": "PSX ticker symbol, e.g. LUCK, HUBC, PIOC"},
            "period": {"type": "string", "description": "optional period_end YYYY-MM-DD or fiscal year e.g. FY2026"},
            "basis": {"type": "string", "enum": ["consolidated", "unconsolidated"],
                      "description": "consolidated unless standalone/unconsolidated/company-only is asked"}},
            "required": ["name", "symbol"]}}},
    {"type": "function", "function": {
        "name": "search_filings",
        "description": "Search company filings. Returns passages tagged with doc_id and page.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "what to look for, include company and year"},
            "doc_id": {"type": "string", "description": "optional: restrict to one document"},
            "k": {"type": "integer", "description": "number of passages (default 6)"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_page",
        "description": "Return the full text of one page of a filing.",
        "parameters": {"type": "object", "properties": {
            "doc_id": {"type": "string"}, "page": {"type": "integer"}},
            "required": ["doc_id", "page"]}}},
    {"type": "function", "function": {
        "name": "get_financials",
        "description": "Return the pre-extracted financial highlights (revenue, net profit, EPS, "
                       "total assets ...) of a document, with the page each value came from.",
        "parameters": {"type": "object", "properties": {"doc_id": {"type": "string"}},
                       "required": ["doc_id"]}}},
    {"type": "function", "function": {
        "name": "calculate",
        "description": "Evaluate an arithmetic expression exactly. Put every number in "
                       "`variables`; the expression may use + - * / ** ( ) abs round min max avg "
                       "pct_change(new, old) cagr(end, start, years).",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string"},
            "variables": {"type": "object", "additionalProperties": {"type": "number"}}},
            "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "final_answer",
        "description": "Give the final structured answer to the user.",
        "parameters": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "basis": {"type": "string"},
            "reported_figures": {"type": "array", "items": {"type": "object", "properties": {
                "field": {"type": "string"}, "value": {"type": "number"},
                "unit": {"type": "string"}, "statement": {"type": "string"},
                "period": {"type": "string"}, "page": {"type": "integer"}}}},
            "calculated_values": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "formula": {"type": "string"},
                "operands": {"type": "array", "items": {"type": "object"}},
                "result": {"type": "number"}}}},
            "explanation": {"type": "string",
                            "description": "Verbatim quoted report text with citations, or 'The report does not state a reason.'"},
            "refused": {"type": "boolean"},
            "refusal_reason": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "doc_id": {"type": "string"}, "page": {"type": "integer"}},
                "required": ["doc_id", "page"]}}},
            "required": ["answer", "citations"]}}},
]


def format_passages(hits) -> str:
    out = []
    for i, h in enumerate(hits, start=1):
        body = h.chunk.text.split("\n", 1)[-1]  # drop the header line, we re-tag it
        out.append(f"[{i}] [{h.chunk.doc_id} | page {h.chunk.page}]\n{body}")
    return "\n\n".join(out)
