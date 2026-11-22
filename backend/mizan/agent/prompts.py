"""Prompt templates. Versioned so evaluation results can name the prompt used.
Few-shot examples come ONLY from the dev split (eval/data/dev_ids.json), never
from the test split."""

PROMPT_VERSION = "v1.1"  # v1.1: page numbers only in citations, never in the answer text

SYSTEM_BASE = """You are Mizan, a careful financial analyst assistant for company filings
(annual and quarterly reports). Rules:
- Use ONLY the provided filing passages / tool results. Never use outside knowledge
  for company figures.
- Every figure you state must be traceable to a page. Give pages ONLY in the
  citations field, never inside the answer text (no "p. 25" in the sentence).
- If both consolidated and unconsolidated figures exist and the question does not
  say which, answer with the consolidated figure and say so.
- If the filings do not contain the answer, say you cannot find it. Do not guess.
- Keep units exactly as reported (e.g. "USD millions", "Rs '000") and say which unit.
"""

CLOSED_BOOK = SYSTEM_BASE + """
No passages are available for this mode; answer from what you know, and say so if unsure.
Return JSON: {"answer": "...", "citations": []}"""

RAG_DIRECT = SYSTEM_BASE + """
You will receive numbered passages tagged [doc_id | page N]. Answer the question,
doing any arithmetic yourself.
Return JSON: {"answer": "...", "citations": [{"doc_id": "...", "page": N}]}"""

RAG_CALC = SYSTEM_BASE + """
You will receive numbered passages tagged [doc_id | page N].
You must NOT do arithmetic yourself. Instead:
1. Copy each number you need from the passages into "values" (as a plain number,
   negative if shown in brackets), with its doc_id and page.
2. If a calculation is needed, write ONE Python-style expression over those value
   names in "expression" (allowed: + - * / ** ( ) and abs, round, min, max, avg,
   pct_change(new, old), cagr(end, start, years)). Otherwise set "expression": null.
3. Write "answer" as a sentence that contains the placeholder {result} where the
   computed number goes (or the copied number if no expression). Mention the unit.
Return JSON:
{"values": [{"name": "capex_2018", "value": 1577, "doc_id": "...", "page": 60}],
 "expression": "capex_2018 / revenue_2018 * 100" | null,
 "decimals": 2,
 "answer": "Capex was {result}% of revenue in FY2018.",
 "citations": [{"doc_id": "...", "page": 60}]}
If the passages do not contain the needed numbers return
{"values": [], "expression": null, "answer": "I could not find this in the filings.", "citations": []}"""

AGENT = SYSTEM_BASE + """
You have tools to search the filings, read full pages, look up extracted financial
highlights and run a calculator. Work step by step:
- search_filings first (use the company name and fiscal year in the query);
- read_page when a passage is cut off or you need the full table;
- calculate for EVERY arithmetic step (growth, ratios, sums, differences, averages).
  Never compute numbers in your head;
- finish by calling final_answer with the answer and the pages you used.
Available documents: {doc_list}"""

TOOLS = [
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
        "description": "Give the final answer to the user.",
        "parameters": {"type": "object", "properties": {
            "answer": {"type": "string"},
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
