# Demo plan and viva prep

Rubric reminder: every member must present a part and explain the architecture, the AI components, the evaluation and **their own code**. A member who misses the demo gets zero.

## Who owns what (each person has AI work + engineering work)

| | Usman Bari (23i-0680) | Syed Burhan Ahmad (23i-0757) |
|---|---|---|
| AI | agent + 4 answering modes (`agent/`), retrieval + glossary/routing (`retrieval/`), QA + retrieval eval | extraction (`extraction/`), alert summary, extraction eval + PSX labelling |
| Engineering | FastAPI (`api/`), store / pgvector, Docker, CI | PSX client + ingestion (`ingest/`), Celery + Telegram/email (`alerts/`, `worker.py`), Next.js frontend |

**Commits:** push your own parts from your own GitHub account (C6 checks "meaningful commits from every member"). Do not let one person push everything.

## 10-minute demo flow

1. **(Usman, 1 min) Problem.** PSX reports run to 100+ pages and analysts read them by hand. Chatbots make up numbers.
2. **(Burhan, 2 min) Get a report.** Reports → fetch `LUCK` from PSX (or upload a PDF) → open Financials and show the extracted table, the page numbers and the "⚠ checks".
3. **(Usman, 3 min) Ask.** Ask a growth question in **agent** mode. Show the citation chip, the source page, the calculator trace and the grounding tick. Ask the same question in **rag_direct** mode and point out that there the LLM did the maths itself.
4. **(Burhan, 1.5 min) Alert.** Watchlist → add the symbol with your Telegram chat id → *Check now* (or `POST /alerts/test/{doc_id}`) → show the message arriving on your phone.
5. **(Both, 2.5 min) Results.** Evaluation page: retrieval table, QA table with mean ± std, McNemar p-value, extraction table, latency and cost, 10+ failures grouped by cause, functional tests (38/38 passing).

Backup: if the internet or the API is down, run the scripted demo (`backend/tests`) and show the saved results JSON.

## Questions you should be able to answer

* **Why not let the LLM calculate?** LLMs make arithmetic and unit mistakes. The rubric also deducts marks for "AI used for deterministic work". Our calculator is an AST evaluator: no `eval`, only + − × ÷, powers and a few finance functions.
* **What is RRF?** Reciprocal Rank Fusion: score = Σ 1/(60 + rank) over the BM25 and dense lists. It ignores the raw score scales, so the two lists can be merged fairly.
* **Why a reranker?** A cross-encoder reads the question and the passage together, so it is more accurate than comparing two separate vectors. We only run it on the top 30 candidates because it is slow.
* **What does routing do?** It reads the company name and year from the question and searches only the matching filings. Open-setting Recall@5 went 0.12 → 0.28 with routing alone.
* **How is hallucination measured?** An answer counts as a hallucination if it is wrong AND contains a number that is not on any cited page and not produced by a calculation (`grounding_check`).
* **Why McNemar?** The same questions are answered by both modes, so the outcomes are paired. McNemar looks only at the questions where the two modes disagree.
* **Test-set leakage?** Prompts use only the 10 dev questions. Honest caveat: the glossary was written after seeing 8 test failures, so we re-check it on the unseen PSX set.
* **Why FinanceBench and PSX?** FinanceBench has expert gold answers and gold pages (we can compare with published numbers). PSX is our real target and a new contribution: no QA set for Pakistani filings exists.
* **What runs where?** Web on Vercel, API + worker on Render / a VPS (Docker), Postgres with pgvector, Gemini API for the LLM, BGE models on the CPU of the API server.
* **Cost?** Read it from `cost_per_request_usd` in the results. Tokens are counted on every call and multiplied by the configured price.
