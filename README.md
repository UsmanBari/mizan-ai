# Mizan AI: an agentic analyst for Pakistan Stock Exchange filings

**AI-4009 Generative AI · Assignment 3 (Part 1) · R&D Product track**
Usman Bari (23i-0680) · Syed Burhan Ahmad (23i-0757) · Section A · FAST-NUCES Islamabad

Ask a question about a listed company's annual or quarterly report. You get an answer with **page citations**, and every number is **calculated by code, not by the language model**. Watch a company and get a **Telegram or email alert** when it publishes new results.

---

## What works in this version (Assignment 3)

| ID | Feature | Status |
|---|---|---|
| F1 | Get reports: upload a PDF, or fetch the latest reports for a PSX symbol from dps.psx.com.pk | ✅ |
| F2 | Parse PDFs: row-preserving text, OCR fallback, chunking | ✅ |
| F3 | Ask questions in 4 modes (closed-book, RAG, RAG + calculator, tool-calling agent), with citations, a calculator trace and a grounding check | ✅ |
| F4 | Extract financial highlights into a validated schema (LLM or rules), with deterministic checks | ✅ |
| F5 | Watchlist → scheduled PSX polling → extraction → change % computed in code → Telegram / email alert | ✅ |
| F6 | Evaluation dashboard + live latency / cost metrics | ✅ |
| X1–X4 | Urdu queries and voice, red-flag detector, multi-company comparison charts, QLoRA fine-tuning | Assignment 4 |

## Architecture

```
Next.js web app ──► FastAPI ──► QAEngine (LangGraph agent) ──► tools: search_filings · read_page · get_financials · calculate
                     │              │                                  │
                     │              └─► LLM: gemini-3.5-flash (Groq / Ollama also work, OpenAI-compatible)
                     │                                                 ▼
                     ├─► Retrieval: BM25 + BGE dense → RRF → cross-encoder rerank, glossary expansion, company/year routing
                     ├─► Extraction: statement-page locator → LLM JSON → Pydantic → deterministic checks
                     ├─► PostgreSQL + pgvector (documents, pages, chunks + vectors, financials, watchlist, alerts, logs)
                     └─► Celery + Redis beat ──► PSX poller ──► Telegram Bot API / SMTP email
```

**Rule we follow: AI proposes, code decides.**

| Job | AI | Deterministic code |
|---|---|---|
| Reading reports | LLM maps statement pages to the schema | PDF text, row rebuild, finding the statement pages |
| Finding evidence | dense embeddings, cross-encoder reranker | BM25, glossary expansion, company/year routing, RRF fusion |
| Answering | LLM chooses tools, picks numbers, writes the sentence | **all arithmetic** (AST calculator), grounding check, citation check |
| Alerts | 3-line summary written from already computed numbers | polling, diffing, % change, deciding to alert, sending |

## Run it

### Option A: quick local run (no Docker, in-memory store)
```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env      # put your free Gemini key in MIZAN_LLM_API_KEY
uvicorn mizan.api.main:app --reload --port 8000        # API docs: http://localhost:8000/docs

cd ../frontend
npm install && npm run dev                             # http://localhost:3000
```
Then open **Reports** and upload a PDF, or type a PSX symbol (e.g. `LUCK`) and press *Fetch latest reports*.

### Option B: full stack with Docker (Postgres + pgvector, Redis, Celery worker)
```bash
cp .env.example .env    # fill in the key
docker compose up --build
```

### Tests
```bash
cd backend && pytest -q          # 39 unit + functional tests, no network needed
```

## Evaluation

Everything is in `eval/`. The notebooks run on **Google Colab** (they clone this repo and install what they need).

| Notebook | Component | Test set | Alternatives compared |
|---|---|---|---|
| `01_retrieval_experiment` | Retrieval | FinanceBench: 140 test questions, 84 filings, gold pages | bm25 · +glossary · +routing · dense · hybrid · hybrid+rerank |
| `02_qa_experiment` | Answers (RQ1) | FinanceBench: 140 test questions | closed-book · RAG (LLM maths) · RAG + calculator · agent |
| `03_extraction_and_psx` | Extraction | PSX: 9 FY2026 annual reports × 6 fields = 54 (hand-verified labels) | rules · API LLM · local Qwen 7B |
| `04_demo_results_dashboard` | All results + functional tests | | |

Dev/test hygiene: 10 FinanceBench questions (`eval/data/financebench_split.json`) are the **only** ones used while writing prompts. The other 140 are the test set.

### Results so far (reproduce: `python eval/run_retrieval.py --retrievers bm25 bm25:expand bm25:route bm25x`)

| Retriever | Scoped R@5 | Scoped MRR | Open R@5 | Open MRR |
|---|---|---|---|---|
| bm25 (baseline) | 0.363 | 0.249 | 0.124 | 0.096 |
| + glossary expansion | 0.509 | 0.358 | 0.135 | 0.084 |
| + company/year routing | 0.363 | 0.249 | 0.284 | 0.192 |
| bm25x (both) | **0.509** | **0.358** | **0.409** | **0.281** |

*Scoped* = search inside the question's filing; *open* = search all 84 filings. Dense, hybrid and rerank rows and the QA and extraction results are filled in by running notebooks 01–03 with a model and an API key.
⚠ The glossary was written after reading 8 BM25 failures from the test split, so its FinanceBench gain may be optimistic. That is why it is re-checked on the PSX set.

## Repository map
```
backend/mizan/
  api/main.py            REST API
  agent/engine.py        4 answering modes + LangGraph agent + grounding check
  agent/prompts.py       versioned prompts + tool schemas
  calculator.py          safe AST calculator (the LLM never does maths)
  retrieval/             BM25, dense, hybrid RRF, reranker, glossary + routing
  extraction/            statement locator, LLM + rule extractors, validation
  ingest/                PDF parser, PSX portal client, pipeline
  alerts/                watcher (diff + summary) and notifiers (Telegram, email)
  store.py               MemoryStore / PgStore (pgvector)
  worker.py              Celery worker + 30-min beat schedule
backend/tests/           unit + functional tests (scripted fake LLM)
eval/                    experiment scripts, data, results, notebooks
frontend/                Next.js app (Ask · Reports · Watchlist · Evaluation)
docs/                    demo + viva guide, AI tool declaration
```

## Responsible use
* Research tool, **not investment advice**. Every answer links to the page it came from.
* Answers whose numbers are not found on a cited page or in a calculation are flagged in the UI (grounding < 1).
* Document text is passed to the model as data inside the user message, never as instructions. A test covers this.
* Alerts go only to channels the user registers. No personal data beyond the watchlist contact is stored.
