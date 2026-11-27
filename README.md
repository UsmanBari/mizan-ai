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
Next.js web app ──► FastAPI ──► QAEngine (LangGraph agent) ──► tools: compute_ratio · search_filings · read_page · get_financials · calculate
                     │              │                                  │
                     │              └─► LLM: gemini-3.5-flash-lite (Groq / Ollama also work, OpenAI-compatible)
                     │                                                 ▼
                     ├─► Retrieval: BM25 + BGE dense → RRF, glossary expansion, company/year routing (reranker off by default)
                     ├─► Deterministic Ratios & Facts Store: mizan/ratios.py + verified PSX facts (data/store.pkl / Postgres)
                     ├─► Extraction: statement-page locator → LLM JSON → Pydantic → deterministic checks
                     ├─► Endpoints: /ask (3-part answer + abstention) · /facts/{symbol} · /compare · /trends/{symbol}
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
cd backend && pytest -q          # 70 unit + functional tests, no network needed
```

## Evaluation

Everything is in `eval/`.

| Script / Notebook | Component | Test set | Alternatives compared |
|---|---|---|---|
| `01_retrieval_experiment` | Retrieval | FinanceBench: 140 test questions, 84 filings, gold pages | bm25 · +glossary · +routing · dense · hybrid · hybridx · +rerank |
| `02_qa_experiment` | Answers (RQ1) | FinanceBench: 60 test questions (`gemini-3.5-flash-lite`) | rag_direct · rag_calc · agent |
| `03_extraction_and_psx` | Extraction | PSX: 9 FY2026 annual reports × 6 fields = 54 (verified labels) | rules · API LLM (`gemini-3.5-flash-lite`) |
| `build_psx_qa_v2.py` + `score_stages.py` | Stage attribution, RQ2 transfer, RQ3 abstention | PSX v2: 243 questions (189 answerable + 54 unanswerable) | rag_direct · rag_calc · agent across bm25 / dense / hybridx |

Dev/test hygiene: 10 FinanceBench questions (`eval/data/financebench_split.json`) are the **only** ones used while writing prompts. The other 140 are the test set.

### Measured Results (`eval/results/summary.json`, `gemini-3.5-flash-lite`)

#### Retrieval (FinanceBench, n=140)

| Retriever | Scoped R@5 | Scoped MRR@10 | Open R@5 | Open MRR@10 | p50 Latency |
|---|---|---|---|---|---|
| `bm25` (baseline) | 0.3631 | 0.2487 | 0.1238 | 0.0956 | 33.7 ms / 272.2 ms |
| `bm25:expand` (+ glossary) | 0.5095 | 0.3576 | 0.1345 | 0.0836 | 43.0 ms / 405.6 ms |
| `bm25:route` (+ routing) | 0.3631 | 0.2487 | 0.2845 | 0.1916 | 38.6 ms / 6.9 ms |
| `bm25x` (glossary + routing) | 0.5095 | 0.3576 | 0.4095 | 0.2805 | 47.1 ms / 10.2 ms |
| `dense` (`bge-small-en-v1.5`) | 0.5381 | 0.4581 | 0.4143 | 0.2945 | 13.1 ms / 48.5 ms |
| `hybrid` (BM25 + Dense RRF) | 0.5107 | 0.3874 | 0.3321 | 0.2218 | 23.9 ms / 190.6 ms |
| **`hybridx` (default)** | **0.6464** | **0.4732** | **0.5321** | **0.4024** | 26.7 ms / 17.1 ms |
| `hybridx+rerank` | 0.5631 | 0.3541 | 0.5238 | 0.3009 | 817.8 ms / 807.8 ms |

#### QA & Extraction (`gemini-3.5-flash-lite`)

- **FinanceBench QA (`bm25x`, n=60)**: `rag_direct` **0.483** (halluc 0.028) · `rag_calc` **0.433** (halluc **0.000**, grounding **0.988**) · `agent` **0.750** ($n=36$, $p=0.0042$ vs `rag_direct`, $p=0.0013$ vs `rag_calc`).
- **PSX v2 Open Retrieval R@5 (`9 filings`)**: `bm25` **0.053** · `dense` **0.507** · `hybridx` **0.629**.
- **PSX v2 QA (`hybridx`)**: `rag_direct` **0.601** ($n=243$, halluc 0.151, RQ3 sel_acc 0.719) · `rag_calc` **0.520** ($n=225$, halluc **0.051**, RQ3 sel_acc **0.752**; `agent` pending daily quota reset).
- **PSX Structured Extraction (`n=54`)**: `rules` **0.463** ($0.00) · `gemini-3.5-flash-lite` **0.759** (\$0.00372/report).

⚠ The FinanceBench glossary was written after reading 8 BM25 failures from the test split, so its FinanceBench gain is re-checked independently on the unseen PSX corpus.

## Repository map
```
backend/mizan/
  api/main.py            REST API (/ask, /facts, /compare, /trends, /documents, /watchlist, /alerts)
  agent/engine.py        4 answering modes + LangGraph agent + compute_ratio + 3-part answer + abstention
  agent/prompts.py       versioned prompts (v2.0) + tool schemas
  ratios.py              deterministic financial ratios + period/basis/missing/base<=0 refusals
  calculator.py          safe AST calculator (the LLM never does maths)
  retrieval/             BM25, dense, hybrid RRF, reranker, glossary + routing
  extraction/            statement locator, LLM + rule extractors, validation
  ingest/                PDF parser, PSX portal client, pipeline
  alerts/                watcher (diff + summary) and notifiers (Telegram, email)
  store.py               MemoryStore (disk persistence + facts table + conflict detection) / PgStore
  worker.py              Celery worker + 30-min beat schedule
backend/tests/           70 unit + functional tests (scripted fake LLM)
eval/                    experiment scripts, data, results, notebooks
frontend/                Next.js app (Ask · Reports · Watchlist · Evaluation)
docs/                    error analysis, proposal results, demo + viva guide, AI tool declaration
```

## Responsible use
* Research tool, **not investment advice**. Every answer links to the page it came from.
* Answers whose numbers are not found on a cited page or in a calculation are flagged in the UI (grounding < 1).
* Document text is passed to the model as data inside the user message, never as instructions. A test covers this.
* Alerts go only to channels the user registers. No personal data beyond the watchlist contact is stored.
