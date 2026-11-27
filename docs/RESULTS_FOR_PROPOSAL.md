# Evaluation Results for Proposal & Report (v2)

**Course**: AI-4009 Generative AI · Assignment 3 (Part 1) · R&D Product Track  
**Authors**: Usman Bari (23i-0680) & Syed Burhan Ahmad (23i-0757) · FAST-NUCES Islamabad  
**Source of Truth**: All numbers match [eval/results/summary.json](file:///c:/Users/usmanbari/Downloads/mizan-ai%20(1)/mizan-ai/eval/results/summary.json) verbatim. Zero numbers are invented or extrapolated.  

> **Evaluation Setup**:  
> - **Model**: `gemini-3.5-flash-lite` (list prices **\$0.30 / 1M in**, **\$2.50 / 1M out**, checked 22 Nov 2026; temperature `0.0`), chosen because the free tier limits `gemini-3.5-flash` to 20 requests/day.  
> - **Prompt Version**: `v1.1` on initial FinanceBench 60-question baseline; `v2.0` (with `compute_ratio`, basis rule, three-part answer, deterministic abstention) on PSX v2.  
> - **Quota Status (27 Nov 2026)**: PSX v2 completed **243/243** (`rag_direct | hybridx`), **243/243** (`rag_calc | hybridx`), and **101/243** (`agent | hybridx`: all `54` lookup, all `27` growth, `20` ratio) across two free-tier API keys before hitting the daily 429 limit. Remaining `142` `agent | hybridx` (34 ratio, 54 cross_company, 54 unanswerable), `agent | bm25` (`3/243`), and `agent | dense` (`0/243`) runs are queued to resume upon quota reset.

---

## 1. Retrieval Evaluation (FinanceBench Test Split, n=140, 84 Filings)

| Retriever Strategy | Scoped R@1 | Scoped R@5 | Scoped R@10 | Scoped MRR@10 | Open R@1 | Open R@5 | Open R@10 | Open MRR@10 | Latency p50 (Scoped / Open) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `bm25` | 0.1536 | 0.3631 | 0.4488 | 0.2487 | 0.0714 | 0.1238 | 0.1631 | 0.0956 | 33.7 ms / 272.2 ms |
| `bm25:expand` (+ glossary) | 0.1929 | 0.5095 | 0.6702 | 0.3576 | 0.0500 | 0.1345 | 0.1810 | 0.0836 | 43.0 ms / 405.6 ms |
| `bm25:route` (+ metadata route) | 0.1536 | 0.3631 | 0.4488 | 0.2487 | 0.1107 | 0.2845 | 0.3631 | 0.1916 | 38.6 ms / 6.9 ms |
| `bm25x` (glossary + routing) | 0.1929 | 0.5095 | 0.6702 | 0.3576 | 0.1464 | 0.4095 | 0.5417 | 0.2805 | 47.1 ms / 10.2 ms |
| `dense` (`bge-small-en-v1.5`) | **0.3036** | 0.5381 | 0.6976 | 0.4581 | 0.1571 | 0.4143 | 0.5071 | 0.2945 | 13.1 ms / 48.5 ms |
| `hybrid` (BM25 + Dense RRF) | 0.2393 | 0.5107 | 0.6881 | 0.3874 | 0.1214 | 0.3321 | 0.4536 | 0.2218 | 23.9 ms / 190.6 ms |
| **`hybridx` (Hybrid + glossary + route)** | 0.2821 | **0.6464** | **0.7988** | **0.4732** | **0.2357** | **0.5321** | **0.6952** | **0.4024** | **26.7 ms / 17.1 ms** |
| `hybridx+rerank` (`bge-reranker-base`) | 0.1679 | 0.5631 | 0.7738 | 0.3541 | 0.1107 | 0.5238 | 0.6917 | 0.3009 | 817.8 ms / 807.8 ms |

*Design takeaway*: `hybridx` is set as our production default (`use_reranker = False` in `config.py`), because adding the cross-encoder lowered Scoped R@5 (`0.6464` → `0.5631`) and added ~800 ms latency overhead.

---

## 2. QA Evaluation Per Mode (FinanceBench n=60 + PSX v2 n=243)

### 2A. FinanceBench (`bm25x`, n=60 test questions)

| Mode | n | Accuracy | Numeric Acc | Hallucination Rate | Refusal Rate | Grounding | Citation Correct | Latency p50 / p95 | Cost / Req |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `rag_direct` | 60 | 0.483 | 0.483 | 0.028 | 0.400 | 0.887 | 0.333 | 3.03s / 10.20s | \$0.00105 |
| `rag_calc` | 60 | 0.433 | 0.483 | **0.000** | 0.500 | **0.988** | 0.267 | **2.12s / 6.75s** | \$0.00120 |
| **`agent`** | 36 | **0.750** | **0.688** | 0.028 | **0.000** | 0.809 | **0.500** | 12.31s / 23.98s | \$0.01155 |

- Paired McNemar tests: `rag_direct` vs `agent` **$p = 0.0042$** ($n=36$); `rag_calc` vs `agent` **$p = 0.0013$** ($n=36$); `rag_direct` vs `rag_calc` $p = 0.250$ ($n=60$).

### 2B. PSX v2 Benchmark (`hybridx`, 243 total: 189 answerable + 54 unanswerable)

| Mode | n Graded | Overall Acc | Numeric Acc | Hallucination Rate | Refusal Rate | Grounding | Citation Correct | Latency p50 / p95 | Cost / Req |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `rag_direct` | 243 | 0.601 | 0.696 | 0.151 | 0.399 | 0.828 | 0.587 | 1.38s / 2.83s | \$0.00164 |
| `rag_calc` | 243 | 0.531 | 0.642 | 0.057 | 0.494 | **0.947** | 0.460 | **1.24s** / 5.26s | **\$0.00159** |
| **`agent`** *(101 graded so far)* | 101 | **0.950** | **0.950** | **0.000** | **0.000** | 0.903 | **0.921** | 4.36s / 7.46s | \$0.00661 |

- Paired McNemar tests: `rag_direct` vs `rag_calc` **$p = 0.0023$** ($n=243$); `rag_direct` vs `agent` **$p = 0.0000$** ($n=101$, 21 vs 1 discordant); `rag_calc` vs `agent` **$p = 0.0000$** ($n=101$, 25 vs 1 discordant).

---

## 3. RQ1 Stage-Wise Error Attribution (`psx_v2_stages`)

| Condition | n Total | Extraction Acc | Operand Selection | Formula Selection | Arithmetic Acc | Answerable Acc | Overall Acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| `rag_direct \| hybridx` | 243 | 0.894* | N/A | N/A | N/A | 0.556 | 0.601 |
| `rag_calc \| hybridx` | 243 | 0.503 | 0.471 | 0.385 | 0.385 | 0.466 | 0.531 |
| **`agent \| hybridx`** *(in progress)* | 101 | **0.921** | **0.762** | **1.000** | **1.000** | **0.950** | **0.950** |
| `agent \| bm25` *(smoke)* | 3 | 1.000 | 0.667 | N/A | N/A | 1.000 | 1.000 |

*\*`rag_direct` has no tool trace; extraction reflects single lookup numeric match coverage only.*

**PSX v2 Accuracy by Question Type**:
- `rag_direct \| hybridx` (`n=243`): `lookup` 0.778 · `growth` 0.815 · `ratio` 0.481 · `cross_company` 0.278 · `unanswerable` 0.759
- `rag_calc \| hybridx` (`n=243`): `lookup` 0.741 · `growth` 0.778 · `ratio` 0.463 · `cross_company` 0.037 · `unanswerable` 0.759
- **`agent \| hybridx`** (`n=101`): `lookup` **0.944** (`n=54`) · `growth` **1.000** (`n=27`) · `ratio` **0.900** (`n=20`) · `cross_company` & `unanswerable` pending quota reset

---

## 4. RQ3 Evidence-Aware Abstention (`psx_v2_abstention`)

| Condition | n | TP | FP | FN | TN | Precision | Recall | F1 | Selective Acc | Coverage | Answerable Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rag_direct \| hybridx` | 243 | 41 | 56 | 13 | 133 | **0.423** | **0.759** | **0.543** | 0.719 | 0.601 | 0.704 |
| `rag_calc \| hybridx` | 243 | 41 | 79 | 13 | 110 | 0.342 | **0.759** | 0.471 | 0.715 | 0.506 | 0.582 |
| `agent \| hybridx` *(101 answerable so far)* | 101 | 0 | 0 | 0 | 101 | — | — | — | **0.950** | 1.000 | **1.000** |

*(Abstention P/R/F1 for `agent` will populate once the 54 unanswerable questions complete.)*

---

## 5. Retrieval → Answer Accuracy (`psx_v2_retrieval_qa`)

| Retriever (`open`, PSX 9 filings) | PSX Retrieval R@5 | Agent Answerable Acc | Agent Overall Acc |
|---|---:|---:|---:|
| `bm25` | 0.053 | 1.000 *(n=3 smoke; full pending)* | 1.000 *(n=3)* |
| `dense` (`bge-small-en-v1.5`) | 0.507 | *Pending quota* | *Pending quota* |
| **`hybridx`** | **0.629** | **0.950** *(n=101 so far)* | **0.950** *(n=101)* |

---

## 6. RQ2 Controlled Cross-Market Transfer (`rq2_transfer`, Open `hybridx`)

| Template | FinanceBench R@5 | PSX R@5 | FinanceBench Agent Acc (n) | PSX Agent Acc (n) |
|---|---:|---:|---:|---:|
| `lookup` | 0.559 | **0.741** | 0.857 (14) | **0.944** (54) |
| `growth` | 0.556 | 0.556 | 0.667 (3) | **1.000** (27) |
| `margin` | 0.200 | **0.722** | 0.800 (5) | **1.000** (8) |

PSX `agent | hybridx` failure tags so far (`n=5` total across 101): `basis`: 5 (including `LUCK` total PAT vs attributable-to-owners `89,042,169`, and 4 step-limit timeouts on `OGDC`, `PRL`, and `HUBC`).

---

## 7. Structured Extraction Evaluation (`extraction`, Burhan's Results)

Setup: 9 verified PSX FY2026 annual reports × 6 fields = **54 examples**.

| Extractor | Field Accuracy | Coverage | Schema-Valid | Unit Accuracy | Statement Page Located | Latency p50 / p95 | Cost / Report |
|---|---:|---:|---:|---:|---:|---|---|
| `rules` (regex baseline) | 0.463 | 0.722 | **1.000** | 0.556 | 0.778 | **0.05s / 0.11s** | \$0.00 |
| **`api:gemini-3.5-flash-lite`** | **0.759** | **0.852** | 0.889 | **0.778** | 0.778 | 3.07s / 7.59s | **\$0.00372** |

---

## 8. Latency & Cost Summary Across All Components

| Component / Condition | Latency p50 | Latency p95 | Cost / Request (or Report) | Monthly Pilot Cost (30,000 req/mo) |
|---|---:|---:|---:|---:|
| Retrieval: `bm25x` (Scoped / Open) | 47.1 ms / 10.2 ms | 288.9 ms / 913.4 ms | \$0.00 | \$0.00 |
| Retrieval: `hybridx` (Scoped / Open) | 26.7 ms / 17.1 ms | 81.5 ms / 251.7 ms | \$0.00 | \$0.00 |
| QA (`rag_direct`, FinanceBench / PSX v2) | 3.03s / 1.38s | 10.20s / 2.83s | \$0.00105 / \$0.00164 | \$31.50 / \$49.20 |
| QA (`rag_calc`, FinanceBench / PSX v2) | 2.12s / 1.24s | 6.75s / 5.26s | \$0.00120 / \$0.00160 | \$36.00 / \$48.00 |
| QA (`agent`, FinanceBench `bm25x` / PSX v2 `hybridx`) | 12.31s / 4.36s | 23.98s / 7.46s | \$0.01155 / \$0.00661 | \$346.50 / \$198.30 |
| Extraction (`rules` vs `gemini-3.5-flash-lite`) | 0.05s vs 3.07s | 0.11s vs 7.59s | \$0.00 vs \$0.00372 / report | — |
