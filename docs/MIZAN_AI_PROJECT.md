# Mizan AI

**An Agentic Analyst for Pakistan Stock Exchange Filings**

> Ask any PSX company report a question and get a cited answer, with every number calculated by code.

| | |
|---|---|
| Course | AI-4009 Generative AI · Assignment 3 (Part 1), continues into Assignment 4 |
| Track | **R&D Product** |
| Team | Usman Bari (23i-0680) · Syed Burhan Ahmad (23i-0757) · Section A |
| Supervisor | Dr. Akhtar Jamil |
| Repo | github.com/usmanbari-ub/mizan-ai |

---

## The problem (in one breath)
PSX company reports are 100–200+ page PDFs. Analysts and investors read them by hand to find one number, compare it with last year and work out growth or a margin. Chatbots like ChatGPT make up numbers and get the maths wrong. On FinanceBench, GPT-4-Turbo with retrieval was wrong or refused on 81% of questions.

## What Mizan does
1. **Gets reports.** Upload a PDF, or type a PSX symbol (e.g. `LUCK`) and it downloads the latest reports from dps.psx.com.pk.
2. **Answers questions with proof.** Every answer has a page citation and shows the source page. The AI finds the numbers; **Python does all the maths**. Any number that can't be found on a cited page gets a warning.
3. **Pulls out the key figures.** Revenue, profit, EPS, assets and equity go into a table, each with its page number, plus automatic checks (does assets = liabilities + equity?).
4. **Sends alerts.** Watch a company; when it posts new results, you get a Telegram or email message with the changes (the % changes are computed by code).

## Main idea: "AI proposes, code decides"
The language model reads and finds. Deterministic code counts, calculates, compares and decides. This avoids wrong maths, and it also avoids the rubric deduction for "AI used for deterministic work".

## Research question (R&D track)
**RQ1:** Does giving arithmetic to a calculator (instead of letting the LLM compute) reduce numerical errors in QA over long financial filings?
We compare 4 answer modes on the same questions: `closed_book` · `rag_direct` (the LLM does the maths) · `rag_calc` (a calculator does the maths) · `agent` (tool calling + calculator).

**RQ2:** Do our retrieval tricks (finance glossary, company/year routing, hybrid + rerank) work as well on Pakistani filings as on US filings?

## Tech in one line
Next.js · FastAPI · LangGraph agent · BM25 + BGE embeddings + RRF + reranker · Gemini 3.5 Flash (Groq / Ollama Qwen as alternatives) · Pydantic · PostgreSQL + pgvector · Celery + Redis · Telegram Bot API · Docker · GitHub Actions

## Results so far (real, reproducible)
FinanceBench, 140 test questions. Recall@5 = the share of questions where the right page is in the top 5 results.

| Retriever | Inside the right filing | Across all 84 filings |
|---|---|---|
| BM25 (baseline) | 0.363 | 0.124 |
| + finance glossary + routing (`bm25x`) | **0.509** | **0.409** |

Still to run: the dense/rerank retrievers, the QA modes (RQ1) and extraction. See `TODO_A3_SUBMISSION.md`.
