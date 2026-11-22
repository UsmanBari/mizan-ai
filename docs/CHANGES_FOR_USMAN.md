# What changed in Mizan AI (Burhan's session, 21 Nov 2026)

Context for Usman and for any AI assistant helping him. Read this before touching the code.
Everything below is already in this zip. **Tests: 39 passed** (was 38; one new test, and one API test extended).

---

## 1. Things you must know first

| # | Change | Why it matters to you |
|---|---|---|
| 1 | **Model is now `gemini-3.5-flash`**, not `gemini-2.5-flash` | Google closed 2.5 Flash to new API users (HTTP 404 "no longer available to new users"). `.env.example` and `config.py` defaults are updated. Run **all** experiments on the same model, or results are not comparable. Backup if you hit 503/limits: `gemini-3.5-flash-lite`. Do not use `*-latest` names (not reproducible). |
| 2 | **`MIZAN_PRICE_IN_PER_M` / `OUT` still hold 2.5 Flash prices** | Update them from ai.google.dev/pricing before reporting `cost_per_request_usd`. |
| 3 | **`llm.py` fix: Gemini 3.x "thought signatures"** | Agent mode returned HTTP 400 on the second step. Gemini 3 attaches `extra_content` (thought signature) to each tool call and rejects the next request if it is not sent back. `chat()` used to rebuild `tool_calls` with only id/name/arguments; it now keeps every field (`tc.model_dump(exclude_none=True)`). Without this, notebook 02's `agent` mode fails. |
| 4 | **`grounding_check` changed (your `agent/engine.py`)** | It was counting digits inside document ids (`LUCK_Q2026_288146` -> 288146) and page references (`p. 33`, `pp. 12, 25`) as numbers the answer claims, so correct answers got lower grounding and the **hallucination rate was inflated**. New shared tokenizer `answer_numbers()` skips doc ids, page refs, years and values <= 1. Grounding is still "share of claimed numbers found on a cited page or produced by the calculator, 0.5% tolerance". Re-run QA after this change; numbers from before are not comparable. |
| 5 | **The PSX test set changed** | Was HBL/MCB/UBL/LUCK/ENGRO/FFC/OGDC/PPL/HUBC/SYS (placeholders, no links). Now 10 June-year-end companies with real FY2026 annual reports on PSX (see section 4). |
| 6 | **Draft gold labels exist, NOT verified yet** | `eval/data/psx_labels.csv` has 54 rows (9 reports x 6 fields), `labeller = claude-draft`. Each needs a human check against the cited PDF page before it counts as gold. **Your 4 to verify: HUBC, AGIL, GHNI, POWER.** Burhan verifies LUCK, PIOC, OGDC, POL, PRL. Change `labeller` to your name once checked. |

---

## 2. Backend changes, file by file

### Usman's files
- **`mizan/llm.py`**: thought-signature fix above (4 lines in `chat()`).
- **`mizan/agent/engine.py`**:
  - New `_NUM_RE` (no trailing comma or full stop captured: `14,617,657,` -> `14,617,657`), `_DOCID_RE`, `_PAGEREF_RE`, `_parse_num()`, `answer_numbers()`.
  - New `number_evidence(ans, store)`: for each number the answer claims, returns `{text, value, status}` where status is `computed` (matches a calculator result or input), `found` (printed on a cited page; adds `doc_id`, `page`, `match` = the exact text on the page) or `unverified`.
  - `grounding_check()` now uses `number_evidence()`, so the UI colours and the metric can never disagree.
- **`mizan/api/main.py`**:
  - `/ask` response has a new field **`evidence`** (list from `number_evidence`). Existing fields unchanged.
  - New endpoint **`GET /documents/{doc_id}/pages/{page}/image?highlight=<text>`**: renders the real PDF page to PNG with PyMuPDF and draws a box around every occurrence of `highlight`. Headers `X-Highlight-Hits` (count) and `X-Highlight-Y` (0-1 position of the first hit). CORS now exposes those headers. Scanned pages have no text layer, so 0 hits: the UI falls back to the OCR text.
- **`mizan/config.py`**: default `llm_model = "gemini-3.5-flash"`.
- **`tests/test_core.py`**: new `test_number_evidence_ignores_references_and_tags_sources`.
- **`tests/test_functional.py`**: `test_api_upload_and_ask` also checks the page-image endpoint (PNG returned, highlight found, 404 for a bad page).

### Burhan's files
- **`mizan/extraction/extractor.py`**:
  - `LLMExtractor(llm, name, fallback=True)`: if the LLM call raises (503 overloaded, 429, bad key, timeout) the app now falls back to `RuleExtractor` with a warning instead of crashing (the UI used to show "Failed to fetch").
  - `locate_statement_pages()` gives **consolidated** statement pages a +3 bonus. Before, it could pick the unconsolidated balance sheet next to a consolidated income statement, and the LLM rightly left the balance sheet empty.
- **`eval/run_extraction.py`**: API and local extractors use `fallback=False`, so an LLM failure counts as a failure in the experiment instead of silently showing rule-based results under the LLM's name.
- **`mizan/ingest/parser.py`**: OCR was never actually switched on (`parse_pdf` was always called with `ocr=False`). Now `ocr=None` means automatic: scanned pages are OCR'd whenever Tesseract is installed (`sudo apt install tesseract-ocr`). New `ocr_available()`. OCR dpi 200.
- **`mizan/ingest/pipeline.py`**: logs a clear warning when a report has scanned pages but Tesseract is missing.

---

## 3. Frontend (redesigned, Burhan's part)

Design idea: **the evidence trail.** Every number in an answer is a clickable token. Colour is reserved for provenance and never used for anything else:
- **green, solid underline** = printed in the report (click: the real page opens with the number boxed)
- **blue, dotted underline + ƒ** = computed by code (click: formula, inputs with page links, result)
- **amber, dashed underline + ?** = not found on the cited pages (flag for the reader)

New and changed files: `app/layout.tsx` (fonts Public Sans + Source Serif 4 via next/font/google), `app/globals.css` (full design system), `app/page.tsx` (Ask: first-run "Load a report", answer + legend + tally, sticky evidence panel / bottom sheet on phones), `app/documents/page.tsx` (Reports: PSX fetch or upload, library, income statement / balance sheet with page links, code checks with both sides shown), `app/watchlist/page.tsx`, `app/eval/page.tsx` (readable system names and column headers, identical rows flagged, three hand-written SVG charts with takeaway headings, tooltips and "Show table"), `components/` (Nav, EvidenceToken, EvidencePanel, PageText, charts/), `lib/api.ts` (`Evidence` type, `docLabel()`, readable network errors), `lib/labels.ts`, `lib/markdown.tsx` (safe Markdown renderer, no innerHTML).

No new npm packages. **WSL note:** when the project lives on `/mnt/c`, start the frontend with `WATCHPACK_POLLING=true npm run dev`, or file changes are not picked up.

---

## 4. Evaluation data

- **`eval/data/psx_reports.csv`**: 10 FY2026 annual reports with direct PSX links: LUCK, PIOC, OGDC, POL, PRL, HUBC, INDU, AGIL, GHNI, POWER. All have text layers (no OCR needed).
- **INDU is broken**: its PSX file is only the 7-page AGM notice, with no statements. Excluded from the labels, so there are 54 examples; the rubric needs >= 50, the TODO says 60. Replace INDU with another June-year-end company's full report.
- **Label conventions used** (agree or change before verifying): consolidated statements where they exist; `net_profit` = attributable to owners when shown; `total_equity` includes non-controlling interests; `profit_before_tax` = the line literally titled profit before (income) tax(ation) (after levies for most companies; PRL's is before final tax). Page = PDF page number (1-based), not the printed number. All units are thousands.
- `build_psx_testset.py` on the draft labels gives **54 extraction examples, 81 QA questions (27 growth)**.
- **PRL had a loss in FY2025**: its growth questions have a negative base. Check `pct_change` and the gold growth answer for it.

---

## 5. Failure evidence already collected

`eval/results/failures/` has `extraction_failures.md` (6 logged failures with cause, fix and evidence, plus risks spotted while labelling: the "ﬁ" ligature in AGIL breaks the regex rules, unlabelled totals, two printed pages per PDF page, etc.) and screenshots.

**QA issues for your error analysis (D4):**
1. The agent sometimes writes page numbers in the answer text (p.25, p.33) that differ from the citations it returns (p.20, p.34): citation precision.
2. With no consolidated/unconsolidated hint, the agent returns both. That's good behaviour, but the PSX QA gold must say which one it expects.
3. Agent mode 400 on Gemini 3.x (fixed in `llm.py`); 503 "overloaded" happens often on `gemini-3.5-flash`, so add retries/backoff in `run_qa.py` or use `-lite` for long runs.

---

## 6. Known limitations (unchanged, worth knowing)

- In-memory store: every backend restart (including `--reload` when a file changes) wipes all reports. The UI now says so. Docker + Postgres is the fix.
- `psx.classify()` labels quarterlies as `Q2026` (no quarter number). Cosmetic; the UI shows "quarterly 2026".
- Docs and proposal still say "Gemini 2.5 Flash" in places (README "Tech in one line", proposal): update to the model actually used.

---

## 7. To do before submission

- [ ] Both: verify your draft labels, then run `python eval/build_psx_testset.py`
- [ ] Replace INDU (Burhan)
- [ ] Update prices in `.env` and the model name in README/proposal (Usman)
- [ ] Re-run notebook 02 with the new grounding and the `llm.py` fix (Usman)
- [ ] Run notebook 03 (Burhan)
- [ ] `AI_TOOLS_DECLARATION.md`: add "Draft gold labels prepared with Claude from the PDF text; every value verified by hand against the cited page" and "UI redesign and several fixes developed with Claude"

## 8. Future idea (Assignment 4, not started)

PSX market data from `dps.psx.com.pk/timeseries/eod/SYMBOL` (daily `[unix_ts, close, volume, open]`, no high/low; needs an `X-Req-Id` header that works for all symbols, obtainable automatically with a headless browser once a day and then cached). Planned: EMA 20/50 + RSI 14 computed in code, report dates on the price chart, price reaction 1/3/5 days after each report, P/E from our extracted EPS vs PSX's P/E, an agent tool `get_market_data`. No candlesticks or smart-money concepts, because there is no daily high/low.
