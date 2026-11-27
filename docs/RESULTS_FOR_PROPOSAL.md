# Evaluation Results for Proposal & Report (v2)

**Course**: AI-4009 Generative AI · Assignment 3 (Part 1) · R&D Product Track  
**Authors**: Usman Bari (23i-0680) & Syed Burhan Ahmad (23i-0757) · FAST-NUCES Islamabad  
**Source of Truth**: All numbers match [eval/results/summary.json](file:///c:/Users/usmanbari/Downloads/mizan-ai%20(1)/mizan-ai/eval/results/summary.json) verbatim. Zero numbers are invented or extrapolated.  

> **Evaluation Setup**:  
> - **Model**: `gemini-3.5-flash-lite` (list prices **\$0.30 / 1M in**, **\$2.50 / 1M out**, checked 22 Nov 2026; temperature `0.0`), chosen because the free tier limits `gemini-3.5-flash` to 20 requests/day.  
> - **Prompt Version**: `v1.1` on initial FinanceBench 60-question baseline; `v2.0` (with `compute_ratio`, basis rule, three-part answer, deterministic abstention) on PSX v2.  
> - **PSX v2 Completion (27 Nov 2026)**: **243/243 COMPLETE** across all three core conditions (`rag_direct | hybridx`, `rag_calc | hybridx`, `agent | hybridx`). For the Retrieval→QA comparison, `agent | bm25` completed **60/243** before hitting free-tier RPD limit (`agent | dense` pending quota reset).

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

*Design takeaway*: `hybridx` is our production default (`use_reranker = False` in `config.py`), because cross-encoder reranking lowered Scoped R@5 (`0.6464` → `0.5631`) and increased latency by ~800 ms.

---

## 2. QA Evaluation Per Mode (FinanceBench n=60 + PSX v2 n=243)

### 2A. FinanceBench (`bm25x`, n=60 test questions)

| Mode | n | Accuracy | Numeric Acc | Hallucination Rate | Refusal Rate | Grounding | Citation Correct | Latency p50 / p95 | Cost / Req |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `rag_direct` | 60 | 0.483 | 0.483 | 0.028 | 0.400 | 0.887 | 0.333 | 3.03s / 10.20s | \$0.00105 |
| `rag_calc` | 60 | 0.433 | 0.483 | **0.000** | 0.500 | **0.988** | 0.267 | **2.12s / 6.75s** | \$0.00120 |
| **`agent`** | 36 | **0.750** | **0.688** | 0.028 | **0.000** | 0.809 | **0.500** | 12.31s / 23.98s | \$0.01155 |

- Paired McNemar tests: `rag_direct` vs `agent` **$p = 0.0042$** ($n=36$); `rag_calc` vs `agent` **$p = 0.0013$** ($n=36$); `rag_direct` vs `rag_calc` $p = 0.250$ ($n=60$).

### 2B. PSX v2 Benchmark (`hybridx`, ALL 243/243 COMPLETE: 189 answerable + 54 unanswerable)

| Mode | n Graded | Overall Acc | Numeric Acc | Hallucination Rate | Refusal Rate | Grounding | Citation Correct | Latency p50 / p95 | Cost / Req |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `rag_direct` | 243 | 0.601 | 0.696 | 0.151 | 0.399 | 0.828 | 0.587 | 1.38s / 2.83s | \$0.00164 |
| `rag_calc` | 243 | 0.531 | 0.642 | 0.057 | 0.494 | **0.947** | 0.460 | **1.24s** / 5.26s | **\$0.00159** |
| **`agent`** | **243** | **0.881** | **0.973** | **0.024** | 0.140 | 0.910 | **0.958** | 4.65s / 8.46s | \$0.00759 |

- **Paired McNemar tests (`n=243` across ALL questions)**:
  - `rag_direct` vs `rag_calc`: **$p = 0.0023$** (`a_only=23`, `b_only=6`) — deterministic calculator cut hallucinations from **15.1%** → **5.7%**, while single-turn strictness increased conservative refusals (39.9% → 49.4%).
  - `rag_direct` vs `agent`: **$p = 0.0000$** (`a_only=12`, **`b_only=80`**) — tool-calling agent + verified `compute_ratio` lifted overall accuracy by **+28.0 points** (60.1% → **88.1%**) and answerable accuracy by **+39.6 points** (55.6% → **95.2%**)!
  - `rag_calc` vs `agent`: **$p = 0.0000$** (`a_only=11`, **`b_only=96`**).

---

## 3. RQ1 Stage-Wise Error Attribution (`psx_v2_stages`)

| Condition | n Total | Extraction Acc | Operand Selection | Formula Selection | Arithmetic Acc | Answerable Acc | Overall Acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| `rag_direct \| hybridx` | 243 | 0.894* | N/A | N/A | N/A | 0.556 | 0.601 |
| `rag_calc \| hybridx` | 243 | 0.503 | 0.471 | 0.385 | 0.385 | 0.466 | 0.531 |
| **`agent \| hybridx`** | **243** | **0.958** | **0.873** | **1.000** | **1.000** | **0.952** | **0.881** |
| `agent \| bm25` *(60 graded)* | 60 | 0.783 | 0.550 | 1.000 | 1.000 | 0.917 | 0.917 |

*\*`rag_direct` has no tool trace; extraction reflects single lookup numeric match coverage only.*

**PSX v2 Accuracy by Question Type**:
- `rag_direct \| hybridx` (`n=243`): `lookup` 0.778 · `growth` 0.815 · `ratio` 0.481 · `cross_company` 0.278 · `unanswerable` **0.759**
- `rag_calc \| hybridx` (`n=243`): `lookup` 0.741 · `growth` 0.778 · `ratio` 0.463 · `cross_company` 0.037 · `unanswerable` **0.759**
- **`agent \| hybridx`** (`n=243`): `lookup` **0.944** (`n=54`) · `growth` **1.000** (`n=27`) · `ratio` **0.963** (`n=54`) · `cross_company` **0.926** (`n=54`) · `unanswerable` 0.630 (`n=54`)

---

## 4. RQ3 Evidence-Aware Abstention (`psx_v2_abstention`, n=243)

| Condition | n | TP | FP | FN | TN | Precision | Recall | F1 | Selective Acc | Coverage | Answerable Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rag_direct \| hybridx` | 243 | 41 | 56 | 13 | 133 | 0.423 | **0.759** | 0.543 | 0.719 | 0.601 | 0.704 |
| `rag_calc \| hybridx` | 243 | 41 | 79 | 13 | 110 | 0.342 | **0.759** | 0.471 | 0.715 | 0.506 | 0.582 |
| **`agent \| hybridx`** | **243** | 34 | **0** | 20 | **189** | **1.000** | 0.630 | **0.773** | **0.861** | **0.860** | **1.000** |

*Key finding*: `agent | hybridx` eliminated all **false refusals** (`FP = 0`, 100% abstention precision and 100% answerable coverage vs 58.2% for `rag_calc`), boosting Abstention F1 from `0.471` → **0.773** and Selective Accuracy to **86.1%**.

---

## 5. Retrieval → Answer Accuracy (`psx_v2_retrieval_qa`)

| Retriever (`open`, PSX 9 filings) | PSX Retrieval R@5 | Agent Answerable Acc | Agent Overall Acc |
|---|---:|---:|---:|
| `bm25` | 0.053 | 0.917 *(n=60 so far)* | 0.917 *(n=60)* |
| `dense` (`bge-small-en-v1.5`) | 0.507 | *Pending quota* | *Pending quota* |
| **`hybridx`** | **0.629** | **0.952** (`n=189`) | **0.881** (`n=243`) |

---

## 6. RQ2 Controlled Cross-Market Transfer (`rq2_transfer`, Open `hybridx`)

| Template | FinanceBench R@5 | PSX R@5 | FinanceBench Agent Acc (n) | PSX Agent Acc (n) |
|---|---:|---:|---:|---:|
| `lookup` | 0.559 | **0.741** | 0.857 (14) | **0.944** (54) |
| `growth` | 0.556 | 0.556 | 0.667 (3) | **1.000** (27) |
| `margin` | 0.200 | **0.722** | 0.800 (5) | **0.981** (54) |

**PSX Failure Difference Tags (`n=29` total failures across 243 `agent | hybridx` questions)**:
- `basis`: **13** (`LUCK` PAT owners vs total; 8 `step_limit` timeouts; 4 unconsolidated basis substituted for missing consolidated statements)
- `period_not_in_corpus`: **9** (FY2022 figures leaked from *"Six Years at a Glance"* summary tables)
- `terminology`: **7** (`REFUSAL_PAT` regex misses when agent truthfully wrote *"do not report"* / *"does not mention"* on unreported cloud ARR / AI capex questions)

---

## 7. Structured Extraction Evaluation (`extraction`, Burhan's Results)

Setup: 15 PSX reports × 6 fields = **90 examples** (dev = 54, held-out = 36).

| Extractor | Overall Acc | Dev / Held-out Acc | Coverage | Schema-Valid | Unit Acc | Statement Page Located | Latency p50 / p95 | Cost / Report |
|---|---:|---|---|---|---|---|---|---|
| `rules` | 0.378 | 0.463 / 0.250 | 0.800 | 1.000 | 0.533 | 0.867 | 0.05s / 0.11s | \$0.00 |
| `rules+columns` | 0.744 | 0.852 / 0.583 | 0.778 | 1.000 | 0.933 | **0.933** | 0.26s / 0.58s | \$0.00 |
| **`api:gemini-3.5-flash-lite`** | **0.867** | **0.870 / 0.861** | **0.944** | **1.000** | **0.933** | 0.867 | 1.99s / 4.81s | **\$0.00423** |

---

## 8. Latency & Cost Summary Across All Components

| Component / Condition | Latency p50 | Latency p95 | Cost / Request (or Report) | Monthly Pilot Cost (30,000 req/mo) |
|---|---:|---:|---:|---:|
| Retrieval: `bm25x` (Scoped / Open) | 47.1 ms / 10.2 ms | 288.9 ms / 913.4 ms | \$0.00 | \$0.00 |
| Retrieval: `hybridx` (Scoped / Open) | 26.7 ms / 17.1 ms | 81.5 ms / 251.7 ms | \$0.00 | \$0.00 |
| QA (`rag_direct`, FinanceBench / PSX v2) | 3.03s / 1.38s | 10.20s / 2.83s | \$0.00105 / \$0.00164 | \$31.50 / \$49.20 |
| QA (`rag_calc`, FinanceBench / PSX v2) | 2.12s / 1.24s | 6.75s / 5.26s | \$0.00120 / \$0.00159 | \$36.00 / \$47.70 |
| QA (`agent`, FinanceBench `bm25x` / PSX v2 `hybridx`) | 12.31s / 4.65s | 23.98s / 8.46s | \$0.01155 / \$0.00759 | \$346.50 / \$227.70 |
| Extraction (`rules+columns` vs `gemini-3.5-flash-lite`) | 0.26s vs 1.99s | 0.58s vs 4.81s | \$0.00 vs \$0.00423 / report | — |
