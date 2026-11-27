# Component Error Analysis (Rubric D4: >= 10 Failures Per Component)

**Course**: AI-4009 Generative AI · Assignment 3 (Part 1) · R&D Product Track  
**Authors**: Usman Bari (23i-0680) & Syed Burhan Ahmad (23i-0757)  
**Model**: `gemini-3.5-flash-lite` (pricing: \$0.30 / \$2.50 per 1M tokens)  

---

## 1. Retrieval Component Error Analysis (FinanceBench, `bm25x` Scoped)

Under the scoped evaluation setting (searching within the 10-K/10-Q filing identified for the question), `bm25x` achieves **Recall@5 = 0.5095 (50.95%)** and **MRR@10 = 0.3576** across 140 test questions (62 misses at top-5). Note that upgrading to `hybridx` (BM25 + BGE-small + RRF + glossary + routing) raised Scoped Recall@5 to **0.6464** and Open Recall@5 to **0.5321**.

### 1.1 Failure Causes and Counts (`retrieval_failures_bm25x_scoped.json`)

| Primary Failure Cause | Count | % of Failures | Primary Root Cause Description | Planned Fix |
|---|---|---|---|---|
| **`vocabulary_mismatch`** | 35 | 56.5% | Question uses analyst terminology ("capex", "net AR", "inventory turnover") while filing uses formal GAAP titles ("Payments for property, plant and equipment", "Trade and other receivables"). | Dense vector embeddings (`bge-small-en-v1.5`) via RRF hybrid fusion (`hybridx`). |
| **`short_or_vague_question`** | 17 | 27.4% | Conceptual queries ("segment dragging down growth", "improving FCF conversion") lacking direct table anchors. | Multi-step agent reformulation + glossary definitions. |
| **`adjacent_page`** | 10 | 16.1% | Retrieved page $n \pm 1$ (continuation notes or balance-sheet/P&L split) instead of exact gold page. | Multi-page context windowing ($n \pm 1$). |
| **Total** | **62** | 100.0% | | |

### 1.2 Real Retrieval Failure Examples (`eval/results/retrieval_failures_bm25x_scoped.json`)

1. **`financebench_id_00499`** (`adjacent_page`, `3M_2022_10K`): Gold `[48, 50, 52]`; Top-5 `[37, 61, 47, 15, 62]`. Cash-flow discussion on p. 47 outranked numerical table on p. 48. *Fix*: Page-window expansion ($n \pm 1$).
2. **`financebench_id_01865`** (`short_or_vague_question`, `3M_2022_10K`): Gold `[25]`; Top-5 `[28, 121, 31, 32, 19]`. Informal *"dragged down"* missed executive segment summary table on p. 25. *Fix*: Query expansion mapping `"dragged down"` → `"segment performance organic sales"`.
3. **`financebench_id_00941`** (`vocabulary_mismatch`, `3M_2023Q2_10Q`): Gold `[1]` cover page; Top-5 `[27, 19, 73, 70, 5]`. Cover table uses `"Trading Symbol(s)"`, not `"debt securities"`. *Fix*: Dense retrieval (`bge-small-en-v1.5`).
4. **`financebench_id_02987`** (`vocabulary_mismatch`, `ACTIVISIONBLIZZARD_2019_10K`): Gold `[69, 70]`; Top-5 `[86, 66, 30, 55, 94]`. Definition prose diluted BM25 toward PP&E note p. 86. *Fix*: Primary-statement prior boost.
5. **`financebench_id_07966`** (`vocabulary_mismatch`, `ACTIVISIONBLIZZARD_2019_10K`): Gold `[70, 73]`; Top-5 `[94, 60, 30, 55, 120]`. Footnote mentions of `"capital expenditures"` outranked cash-flow table p. 73. *Fix*: Hybrid sparse+dense fusion.
6. **`financebench_id_00438`** (`vocabulary_mismatch`, `ADOBE_2022_10K`): Gold `[54]`; Top-5 `[87, 23, 64, 78, 37]`. Retrieved MD&A narrative instead of GAAP income statement p. 54. *Fix*: Statement-title boosting.
7. **`financebench_id_00591`** (`short_or_vague_question`, `ADOBE_2022_10K`): Gold `[57]`; Top-5 `[6, 10, 5, 24, 12]`. `"Free cashflow conversion"` matched marketing intro instead of cash-flow statement. *Fix*: Map FCF → `"operating activities" + "capital expenditures"`.
8. **`financebench_id_00540`** (`vocabulary_mismatch`, `AES_2022_10K`): Gold `[130, 132]`; Top-5 `[140, 149, 69, 142, 111]`. Utility `"fuel inventory"` notes ranked ahead of Balance Sheet. *Fix*: Dense semantic matching.
9. **`financebench_id_08135`** (`adjacent_page`, `AMAZON_2017_10K`): Gold `[38]`; Top-5 `[49, 26, 25, 53, 39]`. Retrieved Comprehensive Income on p. 39 next to Operations table on p. 38. *Fix*: Adjacent-page clustering.
10. **`financebench_id_03882`** (`vocabulary_mismatch`, `AMCOR_2020_10K`): Gold `[50]`; Top-5 `[89, 54, 41, 73, 116]`. Informal `"AR"` failed to match `"Trade receivables, net"`. *Fix*: Abbreviation glossary expansion.

---

## 2. FinanceBench QA Component Error Analysis (`bm25x`, n=60)

| Failure Cause | `rag_calc` (n=60) | `agent` (n=36 graded) | Root Cause | Fix |
|---|---:|---:|---|---|
| **`refusal_after_retrieval_miss`** | 23 | 0 | Top-k single-turn context lacked gold page. | Switch default deep analysis to `agent` + `hybridx`. |
| **`refusal_despite_evidence`** | 7 | 0 | Over-conservative refusal when ratio not pre-computed. | Deterministic `compute_ratio` tool + facts store. |
| **`agent_step_limit`** | 0 | 7 | Multi-year queries exceeded 8 steps. | `compute_ratio` 1-step facts lookup; raise max steps to 12. |
| **`wrong_value_or_reasoning`** | 2 | 1 | Selected wrong sub-row / omitted final %. | Explicit formula schemas in `ratios.py`. |
| **`calculation_tool_error`** | 1 | 0 | Malformed expression passed to AST calculator. | Pre-defined ratio formulas in `ratios.py`. |
| **`ungrounded_number`** | 0 | 1 | Unverified number emitted in `agent` prose. | `grounding_check` + `reported_figures` / `calculated_values` separation. |

*(Selected examples: `financebench_id_00499`, `01865`, `00807`, `02987`, `07966`, `00591`, `06655`, `00540`, `01936`, plus `retrieval_miss` in `eval/results/qa_failures_*.json`.)*

---

## 3. RQ1 Stage-Wise Error Analysis on PSX v2 (`rag_calc` & `agent` over `hybridx`)

In PSX v2 stage-wise attribution:
- `rag_calc | hybridx` ($n=243$): extraction **0.503**, operand selection **0.471**, formula selection **0.385**, arithmetic **0.385**, answerable accuracy **0.466** (overall **0.531**).
- `agent | hybridx` ($n=101$ completed): extraction **0.921**, operand selection **0.762**, formula selection **1.000**, arithmetic **1.000**, answerable accuracy **0.950** (0.0% hallucination; only 5 failures across 101 questions: 4 `agent_step_limit` on `OGDC`, `PRL`, `HUBC` + 1 `LUCK` total-PAT vs owners-PAT error).

### 3.1 Failure Breakdown & 12 Real Examples (`qa_psx_v2_failures_rag_calc.json` / `.jsonl`)

| Stage / Cause | Example ID | Gold | System Trace / Output | Root Cause | Implemented / Planned Fix |
|---|---|---|---|---|---|
| **Extraction (attributable vs total PAT)** | `psx2_LUCK_FY2026_net_profit_lookup` | `89,042,169.00` | Answered `96,456,241` | Took total profit after tax (`96.46B`) instead of profit attributable to equity holders of parent (`89.04B`). | Implemented in `psx_labels.csv` / verified facts store (`compute_ratio`); add parent-attributable prompt rule for RAG. |
| **Extraction (attributable vs total PAT)** | `psx2_HUBC_FY2026_net_profit_lookup` | `49,630,724.00` | Answered `56,257,178` | Same: took profit including NCI (`56.26B`) instead of attributable to owners (`49.63B`). | Same: verified facts store + explicit `"attributable to owners"` instruction. |
| **Extraction (wrong revenue sub-line)** | `psx2_POL_FY2026_revenue_lookup` | `64,248,245.00` | Answered `70,198,859` | Selected gross sales (`70.20B`, before duties/taxes) instead of `NET SALES` (`64.25B`). | Facts store + glossary mapping `"revenue"` → `"net sales / turnover - net"`. |
| **Extraction (retrieval miss → equity subtotal)** | `psx2_OGDC_FY2026_total_equity_lookup` | `1,519,547,299.00` | Answered `1,250,496,218` | Balance sheet p. 156 missed (unlabelled total equity); picked Unappropriated Profit subtotal instead. | Table-aware column extractor (Burhan) + verified facts lookup. |
| **Extraction (retrieval miss → wrong subtotal)** | `psx2_POL_FY2026_total_equity_lookup` | `94,392,570.00` | Answered `86,850,148` | Unlabelled `Total equity` on p. 158; model extracted Revenue Reserves instead of Total Equity. | Same: statement-page locator boost + verified facts store. |
| **Operand Selection (cascading PAT error)** | `psx2_HUBC_FY2026_earnings_growth` | `7.59%` | `pct_change(56257178, 51774561)` → `8.66%` | Correct formula `pct_change`, wrong operand scope (total profit incl. NCI across both years). | `agent` calls `compute_ratio("earnings_growth", "HUBC")` against verified facts. |
| **Operand Selection (cascading PAT error)** | `psx2_LUCK_FY2026_earnings_growth` | `15.71%` | `pct_change(96456241, 84498377)` → `14.15%` | Same: extracted total PAT pair instead of owners-attributable PAT pair. | `compute_ratio("earnings_growth", "LUCK")`. |
| **Operand Selection (cascading PAT margin)** | `psx2_HUBC_FY2026_net_margin` | `69.78%` | `56257178 / 71126352 * 100` → `79.09%` | Margin formula right, numerator operand was total profit incl. NCI instead of owners' PAT. | `compute_ratio("net_margin", "HUBC")`. |
| **Operand Selection (borrowings vs liabilities)** | `psx2_AGIL_FY2026_debt_to_equity` | `0.45x` | Borrowings `861,234` → `11.97%` | Question asked for debt-to-equity (`total_assets - total_equity / total_equity`), model read long-term gearing `11.97%` from KPI page. | Implemented `debt_to_equity` derivation `(total_assets - total_equity) / total_equity` in `ratios.py`. |
| **Operand Selection (printed summary ROE)** | `psx2_GHNI_FY2026_roe` | `38.58%` | Answered `30.98%` (no calc trace) | Copied FY2026 ending-equity ROE (`30.98%`) from summary highlights instead of computing `net_profit / avg(equity_2026, equity_2025)`. | `ratios.py` `roe` uses two-period average equity deterministically. |
| **Formula / Tool Execution (JSON syntax error)** | `psx2_LUCK_FY2026_revenue_growth` | `13.72%` | Raw malformed JSON (`values` closed with `}` instead of `]`) | LLM emitted invalid JSON; `extract_json` failed and `[calculation failed]` propagated. | Add JSON-repair retry in `QAEngine._json()` + prefer `agent` tool calls. |
| **Formula / Tool Execution (calc failure)** | `psx2_cross_GHNI_OGDC_roe` | `38.58% (GHNI)` | `"...achieved a higher return on equity of [calculation failed]%"` | Single-turn `rag_calc` failed to synthesize two-company 6-operand ROE expression in one shot. | `agent` mode calls `compute_ratio("roe", sym)` once per company. |

---

## 4. RQ3 Abstention Error Analysis on PSX v2

Across all `243` questions (189 answerable, 54 unanswerable) on `hybridx`:
- `rag_direct`: Abstention **Precision = 0.423**, **Recall = 0.759**, Selective Accuracy = **0.719**, Coverage = **0.601** (13 false answers on unanswerables, 56 false refusals on answerables).
- `rag_calc`: Abstention **Precision = 0.342**, **Recall = 0.759**, Selective Accuracy = **0.715**, Coverage = **0.506** (13 false answers on unanswerables, 79 false refusals on answerables).

### 4.1 False Answers on Unanswerable Questions (`false_answer_on_unanswerable`) — Key Finding

1. **`psx2_AGIL_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs. 15,397,684 thousand"` for FY2022! **Root cause**: PSX annual reports include a *"Six Years at a Glance"* summary table spanning FY2021–FY2026 inside the FY2026 PDF, causing RAG to leak un-audited historical summary rows for out-of-scope periods.
2. **`psx2_LUCK_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"PKR 81,093,525 ('000)"` from Six-Year Summary.
3. **`psx2_OGDC_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs 317,443 million"` / `"Rs 333.1 billion"` from multi-year summary highlights (also mismatched consolidated vs unconsolidated scale!).
4. **`psx2_POL_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs 51,945 million"` from Six-Year Summary.
5. **`psx2_GHNI_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs. 24,265,107 thousand"` from Six-Year Summary.
6. **`psx2_POWER_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs. 21.08 billion"` (`rag_direct`) vs `"Rs. 31.08 billion"` (`rag_calc` — OCR/table column misread on Six-Year summary!).
7. **`psx2_PRL_unans_period_FY2022`** (`rag_direct` & `rag_calc`): Answered `"Rs. 191.3 billion"` from multi-year table.
8. **`psx2_GHNI_unans_basis_consolidated_revenue`** (`rag_direct`): Answered `"Rs. 60,658,134 thousand"` claiming consolidated basis even though GHNI publishes **unconsolidated statements only**!
9. **`psx2_PIOC_unans_basis_consolidated_net_profit_margin`** (`rag_direct`): Answered `"17.1%"` ignoring that `"consolidated"` statements do not exist for PIOC.
10. **`psx2_POWER_unans_basis_consolidated_revenue`** & **`psx2_POWER_unans_basis_consolidated_net_profit_margin`** (`rag_direct`): Answered with unconsolidated values labeled as consolidated!

*Fix implemented in Agent v2*: `QAEngine._agent()` checks `store.get_facts()` + `compute_ratio(period=...)` and refuses both missing audited periods (`FY2022` not in `facts`) and missing requested basis (`consolidated` requested when only `unconsolidated` exists), while `detect_period_mismatch()` blocks quarterly-vs-annual comparisons **with 100% deterministic recall** (`psx2_*_unans_qtr_vs_ann_*` and `*_half_vs_ann_*` scored 100% abstention accuracy in `rag_calc`).

### 4.2 False Refusals on Answerable Questions (`refusal_despite_evidence`)

11. **`psx2_POWER_FY2026_revenue_lookup`** (`rag_calc`): Gold page retrieved (`gold_page_retrieved=True`), refused citing *"provided passages do not contain unconsolidated (standalone) statements"* even though POWER's financial statements *are* unconsolidated (basis word omitted on summary/snippet chunk).
12. **`psx2_GHNI_FY2026_total_assets_lookup`**, **`psx2_GHNI_FY2026_roe`**, **`psx2_HUBC_FY2026_roe`**: Over-strict RAG refusal when top-6 chunks lacked explicit basis headers or two-year equity columns on the same chunk. *Fix*: Agent v2 `compute_ratio` resolves multi-page operands directly from `FinancialFact` rows and knows company basis from document metadata.

---

## 5. Structured Extraction Component Error Analysis (`extraction_errors.json` & Manual Log, ≥ 10 Examples)

Evaluation on 9 PSX reports × 6 fields = 54 examples: `rules` **46.3%** accuracy vs `api:gemini-3.5-flash-lite` **75.9%** accuracy (all 13 Gemini errors came from `PIOC`, `PRL`, `POWER`; 7/13 caused by `locate_statement_pages()`).

1. **Basis / Locator Mix-up (`LUCK_Q2026_288146`, p. 21 vs p. 33)**: Locator originally picked unconsolidated balance sheet (p. 21) alongside consolidated P&L (p. 33). *Fix*: +3 consolidated bonus added to `locate_statement_pages()`.
2. **Wrong Summary Page Selected (`PIOC_FY2026`, `profit_before_tax`)**: Gold `10,087,307` (p. 149) vs Pred `10,191.54` (Gemini & rules). Locator picked pp. 118–120 (*"Analysis of Statement of Profit or Loss"* in Rs million) instead of audited statements pp. 147–149. *Fix*: Penalize `"Analysis of"` / 6-year columns.
3. **Unit Scale Mismatch (`PIOC_FY2026`, `revenue`)**: Gold `38,578,528` (`'000`) vs Pred `38,578.53` (Rs million from analysis page p. 118, off by 1,000×). *Fix*: Extract unit per page & cross-check scale ratio.
4. **Unit Scale Mismatch (`PIOC_FY2026`, `net_profit` & `total_assets`)**: Gold `6,594,152` vs Pred `6,594.15`; Gold `79,437,602` vs Pred `79,437.60`. *Fix*: Same page-level unit check.
5. **Wrong Equity Subtotal (`PIOC_FY2026`, `total_equity`)**: Gold `49,522,014` vs Pred `31,909.21` (Gemini took share capital + reserves excluding revaluation surplus) / `79,437.6` (rules took total equity & liabilities). *Fix*: Require 2-column statement header match.
6. **Locator Missed Statements (`POWER_FY2026`, `eps_basic`)**: Gold `2.86` (p. 168) vs Pred `null`. Locator picked pp. 109–111 (*"Six years at a glance"*, which omits EPS). *Fix*: Penalize *"six years at a glance"* / *"horizontal"*.
7. **Side-by-Side Dual Statements Schema Failure (`PRL_FY2026`, all 6 fields — Gemini)**: Gold e.g. revenue `350,838,916` (p. 67) vs Pred `null` (`invalid_or_no_output`). Side-by-side P&L and Balance Sheet on one PDF page broke JSON schema output across retries. *Fix*: Column-aware parser using word x-coordinates + fallback retry.
8. **Total PAT vs Attributable-to-Owners (`LUCK_FY2026`, `HUBC_FY2026`, `net_profit` — Rules)**: Rules picked `96,456,241` vs `89,042,169` (LUCK) and `56,257,178` vs `49,630,724` (HUBC). *Fix*: Prefer `"attributable to owners"` sub-row.
9. **Wrong Revenue Substring Match (`POL_FY2026`, `AGIL_FY2026`, `revenue` — Rules)**: Rules matched `"Revenue reserves"` on balance sheet (`89,353,222` vs `64,248,245` for POL; `9,221` vs `17,383,149` for AGIL). *Fix*: Restrict income-statement fields to P&L pages; exclude `"reserves"`.
10. **Unicode Ligature `ﬁ` Failure (`AGIL_FY2026`, `profit_before_tax` & `net_profit` — Rules)**: `"Proﬁt"` (`U+FB01`) caused regex miss (`null`). *Fix*: Apply `unicodedata.normalize("NFKC", text)` before matching.
11. **Unlabelled Balance Sheet Totals (`OGDC_FY2026`, `POL_FY2026`, `total_assets` & `total_equity` — Rules)**: Totals printed as unlabelled ruled subtotals caused `null` in rules (`Gemini` extracted accurately from layout). *Fix*: Derive unlabelled totals from sum of components / x-coordinate table parser.
12. **Derived Liabilities Hallucinated by LLM (`LUCK_Q2026_288146`, p. 32)**: When `"Total liabilities"` line was absent, LLM subtracted equity from assets inline. *Fix*: Store printed figures only; derive `total_liabilities = total_assets - total_equity` deterministically in [ratios.py](file:///c:/Users/usmanbari/Downloads/mizan-ai%20(1)/mizan-ai/backend/mizan/ratios.py).
