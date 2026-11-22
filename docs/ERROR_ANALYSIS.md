# Component Error Analysis (Rubric D4: >= 10 Failures Per Component)

**Course**: AI-4009 Generative AI · Assignment 3 (Part 1) · R&D Product Track  
**Authors**: Usman Bari (23i-0680) & Syed Burhan Ahmad (23i-0757)  
**Evaluation Dataset**: FinanceBench test split (held-out from prompt engineering)  
**Model**: `gemini-3.5-flash-lite` (pricing: $0.30 / $2.50 per 1M tokens)  
**Retrieval**: `bm25x` (BM25 + financial glossary synonym expansion + company/year routing)  

---

## 1. Retrieval Component Error Analysis (`bm25x`, Scoped Setting)

Under the scoped evaluation setting (searching within the 10-K/10-Q filing identified for the question), `bm25x` achieves **Recall@5 = 0.5095 (50.95%)** and **MRR@10 = 0.3576**. Out of 140 test questions, 78 had the gold evidence page in the top 5 results, while 62 questions missed the gold page in the top 5.

### 1.1 Failure Causes and Counts (`retrieval_failures_bm25x_scoped.json`)

| Primary Failure Cause | Count | % of Failures | Primary Root Cause Description | Planned Fix |
|---|---|---|---|---|
| **`vocabulary_mismatch`** | 35 | 56.5% | Question uses analyst terminology ("capex", "net AR", "inventory turnover") while filing uses formal GAAP/SEC statement titles ("Payments for property, plant and equipment", "Trade and other receivables", "Cost of goods sold"). | Dense vector embeddings (`bge-small-en-v1.5`) + Cross-Encoder reranker (`bge-reranker-base`) via RRF hybrid fusion. |
| **`short_or_vague_question`** | 17 | 27.4% | Question is high-level or conceptual ("Does Adobe have improving free cashflow conversion?", "segment dragging down growth") lacking specific table row anchors. | Hypothetical Document Embeddings (HyDE) or query expansion with standard financial ratio definitions. |
| **`adjacent_page`** | 10 | 16.1% | Retrieved pages 1 page before or after the gold page (e.g., retrieving footnote explanations or continuation statements rather than the primary statement table). | Multi-page sliding context windowing (linking page $n$ to $n \pm 1$). |
| **Total** | **62** | 100.0% | | |

---

### 1.2 Real Retrieval Failure Examples (Quoted from `eval/results/retrieval_failures_bm25x_scoped.json`)

#### Example 1: `adjacent_page` (Footnote / Continuation Split)
- **Question ID**: `financebench_id_00499`
- **Question**: *"Is 3M a capital-intensive business based on FY2022 data?"*
- **Gold Evidence Pages**: `['3M_2022_10K', 48]`, `['3M_2022_10K', 50]`, `['3M_2022_10K', 52]` (Balance sheet and cash flow statement)
- **Retrieved Top-5 Pages**: `[37, 61, 47, 15, 62]`
- **Cause Analysis**: Page 47 was retrieved (1 page before gold page 48). The cash flow statement footnote discussion was ranked higher than the numerical table on page 48 because query terms matched the textual narrative.
- **Planned Fix**: Page-window aggregation: when retrieving a table page, automatically include the immediate adjacent continuation page ($\pm 1$).

#### Example 2: `short_or_vague_question` (Conceptual Segment Query)
- **Question ID**: `financebench_id_01865`
- **Question**: *"If we exclude the impact of M&A, which segment has dragged down 3M's overall growth in 2022?"*
- **Gold Evidence Pages**: `['3M_2022_10K', 25]` (MD&A Segment overview)
- **Retrieved Top-5 Pages**: `[28, 121, 31, 32, 19]`
- **Cause Analysis**: The term "dragged down" is colloquial analyst commentary not present in formal 10-K filings. BM25 matched individual segment discussions (pages 31 and 32) rather than the executive segment summary table on page 25.
- **Planned Fix**: Query reformulation mapping "dragged down growth" to "segment performance decrease organic sales growth".

#### Example 3: `vocabulary_mismatch` (SEC Cover Page Registration)
- **Question ID**: `financebench_id_00941`
- **Question**: *"Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2023?"*
- **Gold Evidence Pages**: `['3M_2023Q2_10Q', 1]` (Form 10-Q cover page table)
- **Retrieved Top-5 Pages**: `[27, 19, 73, 70, 5]`
- **Cause Analysis**: The cover page table uses the statutory header *"Title of each class | Trading Symbol(s) | Name of each exchange on which registered"*. The phrase "debt securities" only appears in the notes on page 19 and 27, causing BM25 to completely bypass the cover page.
- **Planned Fix**: Dense semantic search (`bge-small-en`) which recognizes that listed notes on cover pages constitute registered debt securities.

#### Example 4: `vocabulary_mismatch` (Formula vs Reporting Terminology)
- **Question ID**: `financebench_id_02987`
- **Question**: *"What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined as: FY2019 revenue / (average PP&E between FY2018 and FY2019)..."*
- **Gold Evidence Pages**: `['ACTIVISIONBLIZZARD_2019_10K', 69]`, `['ACTIVISIONBLIZZARD_2019_10K', 70]` (Balance sheet & income statement)
- **Retrieved Top-5 Pages**: `[86, 66, 30, 55, 94]`
- **Cause Analysis**: The query definition contains explanatory words ("fixed asset turnover ratio", "defined as", "average PP&E") which heavily diluted BM25 scoring toward note 86 ("Property and Equipment, Net") instead of the primary income statement table.
- **Planned Fix**: Statement-page prior routing: boost canonical primary statement pages (Balance Sheet, Income Statement, Cash Flow) when ratio terms appear in queries.

#### Example 5: `vocabulary_mismatch` (Multi-Year Average Capex)
- **Question ID**: `financebench_id_07966`
- **Question**: *"What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard?"*
- **Gold Evidence Pages**: `['ACTIVISIONBLIZZARD_2019_10K', 70]`, `['ACTIVISIONBLIZZARD_2019_10K', 73]` (Statement of Cash Flows)
- **Retrieved Top-5 Pages**: `[94, 60, 30, 55, 120]`
- **Cause Analysis**: The Cash Flow statement lists capex as *"Capital expenditures"* under Investing Activities on page 73, but note 94 had repeated mentions of *"capital expenditures for software and hardware"*, leading BM25 to prefer the footnote.
- **Planned Fix**: Cross-encoder reranking (`bge-reranker-base`) trained to prioritize statement tables over descriptive text when quantitative answers are requested.

#### Example 6: `vocabulary_mismatch` (Qualitative Trend in Operating Margin)
- **Question ID**: `financebench_id_00438`
- **Question**: *"Does Adobe have an improving operating margin profile as of FY2022?"*
- **Gold Evidence Pages**: `['ADOBE_2022_10K', 54]` (Consolidated Statements of Income)
- **Retrieved Top-5 Pages**: `[87, 23, 64, 78, 37]`
- **Cause Analysis**: BM25 matched "operating margin" in the Item 7 MD&A narrative sections (pages 37, 64) rather than the primary GAAP income statement on page 54.
- **Planned Fix**: Financial glossary synonym expansion mapping "operating margin profile" to "operating income net income net revenue".

#### Example 7: `short_or_vague_question` (Non-GAAP Free Cash Flow)
- **Question ID**: `financebench_id_00591`
- **Question**: *"Does Adobe have an improving Free cashflow conversion as of FY2022?"*
- **Gold Evidence Pages**: `['ADOBE_2022_10K', 57]` (Consolidated Statements of Cash Flows)
- **Retrieved Top-5 Pages**: `[6, 10, 5, 24, 12]`
- **Cause Analysis**: Free cash flow is a non-GAAP metric not titled on page 57. The query matched Adobe's introductory highlights on pages 5, 6, and 10 where marketing commentary mentioned "strong free cash flow".
- **Planned Fix**: Synonym expansion converting "free cashflow" into `("operating cash flows" OR "operating activities") AND "capital expenditures"`.

#### Example 8: `vocabulary_mismatch` (Inventory Turnover Definition)
- **Question ID**: `financebench_id_00540`
- **Question**: *"Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio..."*
- **Gold Evidence Pages**: `['AES_2022_10K', 130]`, `['AES_2022_10K', 132]` (Statement of Financial Position)
- **Retrieved Top-5 Pages**: `[140, 149, 69, 142, 111]`
- **Cause Analysis**: AES is a utility power corporation with negligible merchandise inventory (primarily fuel inventory in note 140). BM25 returned fuel inventory note pages rather than the primary balance sheet.
- **Planned Fix**: Hybrid dense retrieval which learns company-sector terminology (utilities inventory vs retail inventory).

#### Example 9: `adjacent_page` (Income Statement Table vs Footnote)
- **Question ID**: `financebench_id_08135`
- **Question**: *"What is Amazon's year-over-year change in revenue from FY2016 to FY2017 (in units of percents and round to one decimal place)?"*
- **Gold Evidence Pages**: `['AMAZON_2017_10K', 38]` (Consolidated Statements of Operations)
- **Retrieved Top-5 Pages**: `[49, 26, 25, 53, 39]`
- **Cause Analysis**: Top-5 included page 39 (immediately following gold page 38, containing the Comprehensive Income statement).
- **Planned Fix**: Co-occurrence chunk clustering to ensure multi-statement blocks are treated as coherent retrieval units.

#### Example 10: `vocabulary_mismatch` (Abbreviation vs Formal GAAP Title)
- **Question ID**: `financebench_id_03882`
- **Question**: *"What is Amcor's year end FY2020 net AR (in USD millions)?"*
- **Gold Evidence Pages**: `['AMCOR_2020_10K', 50]` (Consolidated Balance Sheets)
- **Retrieved Top-5 Pages**: `[89, 54, 41, 73, 116]`
- **Cause Analysis**: "AR" is an informal abbreviation for Accounts Receivable. Amcor's balance sheet lists *"Trade receivables, net"*. BM25 exact matching on "AR" failed to match "Trade receivables".
- **Planned Fix**: Expanded financial abbreviation dictionary mapping `AR` -> `"accounts receivable" OR "trade receivables"`.

---

## 2. QA Component Error Analysis (RQ1: `rag_calc` and `agent`)

The QA evaluation benchmark was run across 60 test questions using `gemini-3.5-flash-lite` with retriever `bm25x`. 

### 2.1 Failure Causes and Counts (`qa_failures_rag_calc.json` & `qa_failures_agent.json`)

| Primary Failure Cause | `rag_calc` Count | `agent` Count | Total | Root Cause Description | Planned Fix |
|---|---|---|---|---|---|
| **`refusal_after_retrieval_miss`** | 23 | 0 | 23 | Single-turn RAG received chunks missing the gold figure; model correctly refused instead of hallucinating. | Autonomous tool-calling agent that detects miss and re-searches with alternative terms. |
| **`refusal_despite_evidence`** | 7 | 0 | 7 | Evidence was present in retrieved context, but conservative prompt instruction caused model to refuse. | Few-shot dev examples showing how to parse non-standard financial statement rows. |
| **`agent_step_limit`** | 0 | 7 | 7 | Multi-step ratio calculations (e.g. DPO, 3-year averages) exceeded the 8-step budget. | Increase `agent_max_steps` from 8 to 12; implement batched multi-page retrieval tool (`get_financial_statement`). |
| **`wrong_value_or_reasoning`** | 2 | 1 | 3 | Model retrieved evidence but selected incorrect sub-row or missed final ratio percentage. | Schema-guided prompt requiring explicit formula structure prior to response generation. |
| **`calculation_tool_error`** | 1 | 0 | 1 | Syntactically malformed mathematical expression generated by LLM for the Python AST calculator. | Pydantic regex validator on expression string with automated retry on syntax errors. |
| **`ungrounded_number`** | 0 | 1 | 1 | Agent stated a numerical figure not verified against retrieved context pages. | Deterministic post-generation grounding validator (`grounding_check < 1.0` flags in UI). |
| **`retrieval_miss`** | 1 | 0 | 1 | Standard RAG failed to retrieve any relevant evidence page and failed to answer. | Dense-sparse hybrid fusion (`hybridx`). |
| **Total** | **34** | **9** | **43** | | |

---

### 2.2 Real QA Failure Examples (Quoted from `eval/results/qa_failures_*.json`)

#### Example 1: `refusal_after_retrieval_miss` (`rag_calc`)
- **Question ID**: `financebench_id_00499`
- **Question**: *"Is 3M a capital-intensive business based on FY2022 data?"*
- **Gold Answer**: *"No, the company is managing its CAPEX and Fixed Assets pretty efficiently, which is evident from below key metrics: CAPEX/Revenue Ratio: 5.1%, Fixed assets/Total Assets: 20%, Return on Assets= 12.4%"*
- **Model Answer (`rag_calc`)**: *"I could not find this in the filings."*
- **Cause Analysis**: `bm25x` retrieved footnote discussions rather than the balance sheet. In `rag_calc`, the model is limited to single-turn retrieved context; adhering strictly to grounding instructions, it refused to answer.
- **Planned Fix**: Transition to `agent` mode, where the model issues follow-up queries (`search_filings("3M capital expenditures PP&E 2022")`) when initial retrieval lacks sufficient evidence.

#### Example 2: `refusal_after_retrieval_miss` (`rag_calc`)
- **Question ID**: `financebench_id_01865`
- **Question**: *"If we exclude the impact of M&A, which segment has dragged down 3M's overall growth in 2022?"*
- **Gold Answer**: *"The consumer segment shrunk by 0.9% organically."*
- **Model Answer (`rag_calc`)**: *"I could not find a complete organic growth comparison for all segments to determine which dragged down overall growth."*
- **Cause Analysis**: Single-turn retrieval returned details for only two of four business segments. Because evidence was incomplete, `rag_calc` correctly refused rather than guessing.
- **Planned Fix**: Hierarchical retrieval that retrieves the top-level segment breakdown table before searching individual operational segments.

#### Example 3: `refusal_despite_evidence` (`rag_calc`)
- **Question ID**: `financebench_id_00807`
- **Question**: *"Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick ratio is not relevant to measure liquidity, please state that and explain why."*
- **Gold Answer**: *"No. The quick ratio for 3M was 0.96 by Jun'23 close, which needs a bit of an improvement to touch the 1x mark"*
- **Model Answer (`rag_calc`)**: *"I could not find this in the filings."*
- **Cause Analysis**: Balance sheet page 71 was in the retrieved context, but the prompt's negative penalty for ungrounded numbers led `rag_calc` to refuse because "quick ratio" is not explicitly named as a pre-computed line item on the balance sheet.
- **Planned Fix**: Prompt v1.2 instructions clarifying that financial ratios must be computed from component balance sheet line items (cash + marketable securities + receivables) / current liabilities.

#### Example 4: `refusal_after_retrieval_miss` (`rag_calc`)
- **Question ID**: `financebench_id_02987`
- **Question**: *"What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined as: FY2019 revenue / (average PP&E between FY2018 and FY2019)..."*
- **Gold Answer**: *"24.26"*
- **Model Answer (`rag_calc`)**: *"I could not find this in the filings."*
- **Cause Analysis**: `bm25x` retrieved Note 86 on property and equipment, but missed the consolidated income statement on page 70, depriving the model of the FY2019 revenue figure.
- **Planned Fix**: Multi-document entity routing ensuring both balance sheet and income statement chunks are co-retrieved for ratio queries.

#### Example 5: `refusal_after_retrieval_miss` (`rag_calc`)
- **Question ID**: `financebench_id_07966`
- **Question**: *"What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard? Answer in units of percents and round to one decimal place."*
- **Gold Answer**: *"1.9%"*
- **Model Answer (`rag_calc`)**: *"I could not find this in the filings."*
- **Cause Analysis**: The query requires 6 numbers across 3 fiscal years (FY2017, FY2018, FY2019 capex and revenue). Top-6 passages only contained FY2019 values.
- **Planned Fix**: Multi-year table alignment tool (`get_financials(symbol, "capex", years=[2017, 2018, 2019])`).

#### Example 6: `agent_step_limit` (`agent`)
- **Question ID**: `financebench_id_07966`
- **Question**: *"What is the FY2017 - FY2019 3 year average of capex as a % of revenue for Activision Blizzard?"*
- **Gold Answer**: *"1.9%"*
- **Model Answer (`agent`)**: *"I could not complete the analysis within the step limit."*
- **Cause Analysis**: The agent used 8 steps searching separately for each annual report and cash flow statement, exceeding `agent_max_steps=8` before it could execute the final calculator call.
- **Planned Fix**: Provide a dedicated multi-year statement retrieval tool (`get_multi_year_statement`), reducing 6 individual search calls into 1 tool call.

#### Example 7: `agent_step_limit` (`agent`)
- **Question ID**: `financebench_id_00591`
- **Question**: *"Does Adobe have an improving Free cashflow conversion as of FY2022?"*
- **Gold Answer**: *"Yes, the FCF conversion (using net income as the denominator) for Adobe has improved by ~13% from 143% in 2021 to 156% in 2022"*
- **Model Answer (`agent`)**: *"I could not complete the analysis within the step limit."*
- **Cause Analysis**: The agent searched for operating cash flow, net income, and capex across FY2021 and FY2022. It exhausted its 8 steps reading intermediate pages.
- **Planned Fix**: Expand agent step budget to 12 steps for complex multi-year ratio inquiries.

#### Example 8: `agent_step_limit` (`agent`)
- **Question ID**: `financebench_id_06655`
- **Question**: *"What is Amazon's FY2017 days payable outstanding (DPO)? DPO is defined as: 365 * (average accounts payable between FY2016 and FY2017) / (FY2017 COGS + change in inventory between FY2016 and FY2017)..."*
- **Gold Answer**: *"93.86"*
- **Model Answer (`agent`)**: *"I could not complete the analysis within the step limit."*
- **Cause Analysis**: Four distinct data points from three different statements were required: FY16 AP, FY17 AP, FY17 COGS, and FY16/17 Inventory. Individual search and read calls exceeded the 8-step limit.
- **Planned Fix**: Batch retrieval allowing the agent to request multiple pages in a single `read_pages([38, 40])` call.

#### Example 9: `ungrounded_number` (`agent`)
- **Question ID**: `financebench_id_00540`
- **Question**: *"Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio for the FY2022..."*
- **Gold Answer**: *"AES has converted inventory 9.5 times in FY 2022."*
- **Model Answer (`agent`)**: *"For FY2022, conventional inventory management is meaningful for AES Corporation... Total Cost of Sales: $10,069 million, Average Inventory: $829.5 million, Inventory Turnover Ratio: 12.14 times."*
- **Cause Analysis**: The agent computed 12.14x using total cost of sales ($10,069M) and average inventory ($829.5M). Gold benchmark utilized a non-consolidated inventory sub-item yielding 9.5x.
- **Planned Fix**: Grounding check correctly flagged this answer (grounding score recorded), alerting users to discrepancies between non-consolidated line items and total consolidated cost of sales.

#### Example 10: `wrong_value_or_reasoning_with_evidence` (`agent`)
- **Question ID**: `financebench_id_01936`
- **Question**: *"What is the nature & purpose of AMCOR's restructuring liability as oF Q2 of FY2023 close?"*
- **Gold Answer**: *"87% of the total restructuring liability is related Employee liabilities."*
- **Model Answer (`agent`)**: Detailed breakdown quoting exact figures: Employee Costs USD 81 million, Total Restructuring Liability USD 93 million, nature: Russia-Ukraine conflict and Bemis integration.
- **Cause Analysis**: The agent retrieved all numbers with 100% precision ($81M employee costs out of $93M total liability = 87.1%), but presented the raw dollar breakdown instead of dividing to compute the single percentage 87%.
- **Planned Fix**: Financial analyst question prompt asking the model to explicitly summarize key constituent shares as percentages when analyzing liability composition.
