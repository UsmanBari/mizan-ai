# Burhan's guide to Mizan AI

Hey Burhan, this is everything you need to understand the project and **your parts** well enough for the demo and viva. Read it top to bottom once (about 30 min), then open the code files it points to.

---

## 1. What are we building?
**Mizan AI**: an app where you ask a question about a PSX company's report (e.g. *"What was Lucky Cement's profit after tax in FY2025 and how much did it grow?"*) and get:
- an answer with a **page citation** (click it to see the actual page),
- the **maths done by Python**, not by the AI,
- a **warning** if any number in the answer can't be found in the report.

It can also **fetch reports from the PSX website** automatically and **send Telegram/email alerts** when a company posts new results.

**Why it's a good project:** the data is real and free (PSX PDFs + the FinanceBench dataset), it's a real problem (analysts read 200-page PDFs by hand), and it has a research angle (does a calculator reduce AI maths errors?).

## 2. The one rule to remember
> **AI proposes, code decides.**

The LLM (Gemini) *reads* and *finds* numbers. Python *calculates*, *compares* and *checks*. If the viva asks "why not let the AI do the maths?", the answer is: LLMs make arithmetic and unit mistakes, and the rubric takes marks off for "AI used for deterministic work".

## 3. How it works (the big picture)

```
Web app (Next.js)  ──►  FastAPI backend  ──►  AI layer
                                                ├─ Agent (LangGraph): search → read page → calculator → answer
                                                ├─ Retrieval: BM25 + embeddings → RRF → reranker
                                                └─ Extraction: find statement pages → LLM fills JSON → checks
                         │
                         ├─► Postgres + pgvector (reports, chunks, vectors, alerts)
                         └─► Celery worker (every 30 min): PSX → download → extract → compare → Telegram/email
```

Two user journeys:
1. **Ask:** question → route to the right company/year → agent searches and reads pages → calculator → cited answer + grounding check
2. **Alert:** PSX portal → ingest (parse + index) → extract figures → compare with last report (% change in code) → Telegram/email

## 4. Your parts (you must be able to explain these)

### a) PSX ingestion: `backend/mizan/ingest/`
| File | What it does |
|---|---|
| `psx.py` | Opens `dps.psx.com.pk/company/<SYMBOL>`, finds rows in the tables that have PDF links, guesses the type (annual/quarterly) and year from the title with simple rules (`classify()`), downloads the PDF |
| `parser.py` | Turns a PDF into text **page by page**. The key trick is `layout_text()`: it rebuilds each line from the word positions, so a table row stays together ("Net profit \| 5,363 \| 4,869") instead of every number landing on its own line. About 1 second per report (the table detector we tried first took 70 s). Then it chunks the text (~1500 chars) with a header `[company \| doc \| page N]` |
| `pipeline.py` | Glue: PDF → pages → chunks → saved in the store |

**Viva questions you'll get:**
- *Why rebuild lines from word positions?* The PDF text layer splits table cells. Keeping a row on one line lets search match "net profit" with its numbers.
- *What if PSX changes its website?* The parser just looks for `.pdf` links inside table rows, so it's defensive. Manual upload always works as a backup.
- *Scanned PDFs?* Pages with no text get OCR (Tesseract) if it's installed.

### b) Extraction: `backend/mizan/extraction/extractor.py`
Pulls 9 figures (revenue, gross profit, operating profit, profit before tax, net profit, EPS, total assets, total liabilities, total equity) into a **Pydantic schema** (`FinancialHighlights` in `models.py`).

Steps:
1. `locate_statement_pages()`: **no AI.** It scores every page: a statement title near the top ("Statement of Profit or Loss", "Balance Sheet") + line-item words + lots of numbers − long sentences. It picks the best income-statement and balance-sheet pages. Titles are matched with **spaces removed**, because PDFs sometimes split words ("Incom e").
2. Two extractors (this is your experiment):
   - `RuleExtractor`: **baseline, no AI.** Regex finds the label ("profit after taxation") and takes the next number.
   - `LLMExtractor`: sends those pages to Gemini in **JSON mode**, validates with Pydantic, and if the JSON is wrong it sends the error back and retries (up to 2 times).
   - *(Local model)* the same LLMExtractor pointed at Ollama + Qwen2.5-7B: "API vs local".
3. `validate()`: **no AI.** Checks assets ≈ liabilities + equity (2% tolerance), net profit ≤ profit before tax, and that the EPS sign matches the profit sign.
4. `normalised()`: multiplies by the unit (Rs '000 → × 1000) **in code**. EPS is never scaled.

**Viva:** *Why not just ask the LLM for the whole report?* Too long (200 pages = expensive, and the "lost in the middle" problem). The deterministic locator sends only 2–4 pages, so it's cheaper and more accurate.

### c) Alerts + worker: `backend/mizan/alerts/`, `backend/mizan/worker.py`
- `watcher.py` → `process_new_document()`: extract → find the previous report → `compute_changes()` works out the **% change with the calculator** → the LLM writes a 3-sentence summary **using only those numbers** → sends.
- `notify.py`: Telegram Bot API (`sendMessage`) and email over SMTP (Gmail app password).
- `worker.py`: Celery + Redis; **beat** runs `poll` every 30 minutes (`MIZAN_POLL_MINUTES`).
- Demo shortcut: `POST /alerts/test/{doc_id}` sends an alert for any report already in the system.

### d) Frontend: `frontend/`
Next.js (App Router), plain CSS, 4 pages:
| Page | File | What it shows |
|---|---|---|
| Ask | `app/page.tsx` | question box, mode dropdown, answer + citation chips + calculator trace + grounding tick, source page on the right |
| Reports | `app/documents/page.tsx` | upload a PDF, fetch from PSX, library table, extracted financials |
| Watchlist | `app/watchlist/page.tsx` | add a symbol + Telegram chat id/email, "Check now", alert list |
| Evaluation | `app/eval/page.tsx` | tables from `eval/results/summary.json` + live latency/cost |

All API calls go through `lib/api.ts` (`NEXT_PUBLIC_API_URL`).

### e) Your experiment: extraction (`eval/run_extraction.py`, notebook 03)
- **Test set:** 10 PSX reports × 6 fields = 60 examples (we label them by hand). The same labels also create the PSX QA questions (`build_psx_testset.py`); growth answers are computed in code.
- **Compared:** rules vs Gemini vs local Qwen
- **Metrics:** field accuracy (within 0.5%), unit accuracy, coverage, schema-valid rate, whether the statement page was found, latency, cost per report
- **Error causes (auto-tagged):** `took_prior_period_column`, `unit_scale`, `page_not_located`, `missing_field`, `wrong_line_item_or_consolidation`

## 5. Usman's parts (know them roughly; the viva can ask)
- **Agent** (`agent/engine.py`): 4 modes. `rag_calc` = the LLM returns the values + an expression like `pct_change(pat_2025, pat_2024)` and Python computes it. `agent` = a LangGraph loop with tools `search_filings`, `read_page`, `get_financials`, `calculate`, `final_answer`, at most 8 steps.
- **Calculator** (`calculator.py`): parses the expression with Python's AST, only allows + − × ÷ and a few functions → safe (no `eval`).
- **Grounding check:** every number in the answer must appear on a cited page or come from the calculator; otherwise the UI shows a warning.
- **Retrieval:** BM25 (keywords) + BGE embeddings (meaning) merged with **RRF** (score = Σ 1/(60 + rank)), then a **cross-encoder reranker**. Plus a **finance glossary** (capex → "purchases of property, plant and equipment") and **routing** (it reads the company + year from the question and searches only that filing).

## 6. Words you should know
| Term | Simple meaning |
|---|---|
| RAG | Find relevant text first, then let the LLM answer from it |
| BM25 | Classic keyword search scoring |
| Embeddings / dense retrieval | Turn text into vectors; similar meaning = close vectors |
| RRF | Merge two ranked lists using ranks, not raw scores |
| Reranker (cross-encoder) | A small model that reads question + passage together and rescores the top 30 |
| pgvector | Postgres extension for storing vectors and searching them |
| LangGraph | Library for building the agent loop as a graph (agent node ↔ tools node) |
| Pydantic | Python schema validation, so the LLM's JSON must match our fields |
| Recall@5 | The share of questions where the right page is in the top 5 results |
| McNemar test | A significance test for two systems answering the **same** questions |
| Hallucination rate | Wrong answers that contain a number not found anywhere in the evidence |

## 7. Run it yourself
```bash
# backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env        # add the Gemini key + your Telegram token
pytest -q                      # should say 38 passed
uvicorn mizan.api.main:app --reload --port 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev                    # http://localhost:3000
```
Try it: Reports → upload any PSX annual report PDF → Financials → Ask a question about it → Watchlist → add the symbol + your chat id → `POST /alerts/test/<doc_id>` from http://localhost:8000/docs → check Telegram.

## 8. What you're doing this week
See `docs/TODO_A3_SUBMISSION.md`. Your main jobs: **push your folders from your account**, **Telegram bot**, **lead PSX labelling**, **run notebook 03**, **make the demo slides**.

Any doubt, message Usman. 🚀
