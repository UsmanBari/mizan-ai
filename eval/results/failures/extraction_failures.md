# Extraction failures: manual log (Burhan)

Found while testing the app on 2026-11-21 with LUCK quarterly reports fetched live from PSX
(model: gemini-3.5-flash / gemini-3.5-flash-lite, OCR: Tesseract).

| # | Report | Page | Field(s) | What happened | Cause tag | Fix | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | LUCK_Q2026_288146 | 21 | total assets, liabilities, equity | Locator picked the UNconsolidated balance sheet (p21) while income figures came from the consolidated statement (p33), so the LLM left the balance sheet empty | wrong_line_item_or_consolidation | `locate_statement_pages()` now gives consolidated statement pages a +3 bonus (fixed) | `LUCK_Q2026_288146_extraction_before_fix.png`, `LUCK_Q2026_288146_p21_raw.png` |
| 2 | LUCK_Q2026_288146 | 21 | (long-term investments line) | OCR read `59,272,376` as `$9,272,376`; also typos like "Unelaimed dividend" | ocr_noise | Prefer text-layer PDFs for the test set; strip stray symbols before parsing numbers | `LUCK_Q2026_288146_p21_raw.png` |
| 3 | LUCK_Q2026_288146 | 21 | total_liabilities, total_equity | No "Total liabilities" line is printed; liabilities and equity totals appear only as unlabelled subtotals (99,445,391 / 226,447,192) | missing_field | Compute in code: non-current + current liabilities; equity = share capital + reserves subtotal | `LUCK_Q2026_288146_p21_raw.png` |
| 4 | LUCK_Q2026_288146 | – | all | Gemini returned 503 (overloaded) on every retry; the request crashed and the UI showed "Failed to fetch" | api_failure | App: `LLMExtractor` falls back to `RuleExtractor` with a warning. Experiment: fallback disabled so failures are counted honestly (fixed) | `LUCK_ingest_log_scanned_503.txt` |
| 5 | LUCK_Q2026_288146, LUCK_Q2026_287455 | all | all | 38/42 and 27/27 pages are scanned images; OCR code existed but `parse_pdf` was always called with `ocr=False`, so pages had no text (4 and 0 chunks) | page_not_located (scanned PDF) | OCR now runs automatically when Tesseract is installed; a warning is logged when it is missing (fixed) | `LUCK_ingest_log_scanned_503.txt` |
| 6 | LUCK_Q2026_288146 | 32 | total_liabilities | After the consolidation fix all balance-sheet fields filled and A = L + E holds exactly, but the cited line item for liabilities is "TOTAL EQUITY AND LIABILITIES" and the value (328,699,699) is not printed on that line: the LLM appears to have computed it (total minus equity) | llm_did_arithmetic | Ask the LLM for printed values only (null if not printed); compute total_liabilities in code as total assets − total equity and mark it "derived" | `LUCK_Q2026_288146_extraction_after_fix.png` |

## Risks spotted while labelling (to check in notebook 03)
- AGIL: PDF text uses the "ﬁ" ligature ("Proﬁt"), so the regex rules for "profit" will not match -> expect RuleExtractor misses (fix: normalise ligatures with unicodedata NFKC before matching).
- PIOC, OGDC, POL, PRL, HUBC, AGIL: no line labelled "Total equity" and/or "Total assets"; values only appear as unlabelled column subtotals -> missing_field for rules; LLM must infer.
- OGDC, PRL: two printed pages per PDF page (side-by-side spreads); PRL puts balance sheet AND P&L on one PDF page.
- PRL: prior year is a LOSS (-4,659,666) -> growth % on a negative base; check the calculator and the gold growth answer.
- "Profit before tax" wording varies (before/after final tax & levy): labels use the line literally titled profit before (income) tax(ation).
- INDU file on PSX is only the 7-page AGM notice, no statements -> excluded (find full report or replace).

---

# Experiment results: rules vs Gemini (run on 2026-11-22)

Setup: 9 verified FY2026 PSX annual reports x 6 fields = 54 examples. `python eval/run_extraction.py --extractors rules api`,
model `gemini-3.5-flash-lite`, OCR off (all 9 reports have a text layer; checked while labelling). Raw data: `eval/results/extraction_errors.json`.

| | Rules (no AI) | Gemini 3.5 Flash-Lite |
|---|---|---|
| Field accuracy (within 0.5%) | 46.3% | **75.9%** |
| Coverage | 72.2% | 85.2% |
| Unit correct | 55.6% | 77.8% |
| Statement page located | 77.8% | 77.8% |
| Schema-valid output | 100% | 88.9% |
| Latency p50 / p95 | 0.05 s / 0.11 s | 3.1 s / 7.6 s |
| Cost per report | $0 | $0.0037 |

Errors: rules 29/54, Gemini 13/54. **Every Gemini error comes from 3 reports (PIOC, PRL, POWER)**, and 7 of the 13 trace back to the page locator, which is shared by both extractors.

## Failures grouped by cause (14 examples, with the fix)

### A. Page locator picked a summary page, not the statements (both extractors)
| # | Report | Field | Gold | Predicted | What happened |
|---|---|---|---|---|---|
| 7 | PIOC | profit_before_tax | 10,087,307 | 10,191.54 | Locator chose pp. 118-120, titled **"Analysis of Statement of Profit or Loss"**: a six-year table in **Rupees in million**, instead of the statements on pp. 147-149. The heading contains the real statement title, which is why it scored high. 10,191.54 is the analysis table's own figure (before the final-tax levy) |
| 8 | PIOC | total_equity | 49,522,014 | 31,909.21 (Gemini) / 79,437.6 (rules) | Same analysis page: Gemini took "Share capital and reserves" (31,909.21 m), which excludes the revaluation surplus; rules took "Total equity and liabilities" |
| 9 | POWER | eps_basic | 2.86 | none | Locator chose pp. 109-111, **"Six years at a glance / Vertical and horizontal analysis"** (Rs '000), instead of the statements on pp. 166-168. Revenue, profits and totals appear there with the same values, so those came out right, but EPS does not, so both extractors miss it |

**Fix:** penalise headings containing "analysis of", "at a glance", "six years", "horizontal" or "vertical", and pages with more than two year columns, require the statement title *and* a current/prior column header, and give a bonus when the balance-sheet and profit-or-loss pages are adjacent. Expected gain: up to 7 Gemini errors (13% of examples).

### B. Unit scale: right number, wrong unit (both extractors; a consequence of A)
| # | Report | Field | Gold (Rs '000) | Predicted | What happened |
|---|---|---|---|---|---|
| 10 | PIOC | revenue | 38,578,528 | 38,578.53 | Read "Net turnover 38,578.53" from the Rs-million analysis page, but the unit was reported as thousands: off by 1,000x |
| 11 | PIOC | net_profit | 6,594,152 | 6,594.15 | Same |
| 12 | PIOC | total_assets | 79,437,602 | 79,437.6 | Same |

**Fix:** take the unit from the *same page* as each value, and add a code check: if a value is about 1/1000 of the same line on another candidate page, flag it as a unit error. (A deterministic check: "code decides".)

### C. LLM returned no valid JSON for a whole report (Gemini only)
| # | Report | Field | Gold | Predicted | What happened |
|---|---|---|---|---|---|
| 13 | PRL | all 6 fields | e.g. revenue 350,838,916 | none | PRL prints the balance sheet AND profit or loss side by side on one PDF page (p. 67). The long, two-column text made Flash-Lite return output that failed the Pydantic schema even after 2 repair retries, so all 6 fields were lost (this is the whole 88.9% schema-valid rate) |

**Fix:** (1) log the raw model output for failed reports (currently not saved); (2) use JSON-schema structured output instead of plain JSON mode; (3) on failure, retry once with the full `gemini-3.5-flash` before giving up; (4) split two-statement pages into separate prompts.

### D. Rules matched the wrong line (rules only)
| # | Report | Field | Gold | Predicted | What happened |
|---|---|---|---|---|---|
| 1 | LUCK | net_profit | 89,042,169 | 96,456,241 | Took total profit after tax; the label convention is profit attributable to owners (the same for HUBC: 56,257,178 vs 49,630,724) |
| 2 | POL | revenue | 64,248,245 | 89,353,222 | The regex for "revenue" matched **"Revenue reserves"** on the balance sheet |
| 3 | HUBC | total_equity | 258,007,509 | 422,563,444 | Matched **"Total equity and liabilities"**, which is the balance-sheet total (same for AGIL and POWER) |

**Fix:** prefer the "attributable to owners" line when present; exclude "reserves" and "equity and liabilities"; only search for income-statement fields on the profit-or-loss page.

### E. Label not matched at all (rules only)
| # | Report | Field | Gold | What happened |
|---|---|---|---|---|
| 4 | AGIL | profit_before_tax, net_profit | 1,685,924 / 1,203,408 | The PDF writes "Proﬁt" with the **ﬁ ligature** (one Unicode character), so the regex for "profit" never matches (predicted while labelling) |
| 5 | PRL | profit_before_tax, net_profit, eps_basic | 24,146,650 / 15,779,957 / 25.05 | Labels read **"Profit / (loss) before taxation"** and "Earnings / (loss) per share", which the regex does not allow |

**Fix:** normalise text with `unicodedata.normalize("NFKC", ...)` (turns ﬁ into fi), and allow an optional "/ (loss)" in the label patterns.

### F. Unlabelled totals (rules only)
| # | Report | Field | Gold | What happened |
|---|---|---|---|---|
| 6 | OGDC, POL, PRL | total_assets, total_equity | e.g. OGDC 1,852,826,589 / 1,519,547,299 | These reports print the totals with **no label** on the line (just a ruled subtotal), so a label-then-number rule cannot find them. Gemini gets them right from the layout for OGDC and POL (PRL failed for another reason, see C) |

**Fix:** compute them in code from labelled lines: total equity = the subtotal line just above "Non-current liabilities"; total assets = total equity and liabilities (the balance sheet balances).

## Takeaways for the report
1. The LLM wins clearly on language variation (ligatures, "/ (loss)", unlabelled totals, "attributable to owners"): it makes 0 errors of types D, E and F.
2. The **page locator is now the main bottleneck for both**: 77.8% page-located caps what any extractor can reach. It is deterministic code, so fixing it is cheap and benefits the rules and the LLM equally.
3. The LLM's remaining failure mode is **format, not reading**: one report lost entirely to invalid JSON. A fallback to the bigger model would cost about $0.02 for that one report.

# Extraction experiment, all verified reports (run on 2026-11-27)

15 reports, 90 verified examples.

| Extractor | Field accuracy | Dev (9 old reports) | Held-out (new reports) | Prior-year column taken | Unit acc. | Page located |
|---|---|---|---|---|---|---|
| rules | 0.378 | 0.463 | 0.25 (n=36) | 0.0 | 0.533 | 0.867 |
| rules+columns | 0.744 | 0.852 | 0.583 (n=36) | 0.0 | 0.933 | 0.933 |
| api:gemini-3.5-flash-lite | 0.867 | 0.87 | 0.861 (n=36) | 0.0 | 0.933 | 0.867 |
| api:gemini-3.5-flash-lite+columns | 0.867 | 0.87 | 0.861 (n=36) | 0.0 | 0.933 | 0.867 |

103 failures in total (api+columns failed on exactly the same 12 examples as api: code had to correct 0 values, so its groups are not repeated).


## api: Field missing - the right page was not found (5)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | eps_basic | 29.03 | none | 149 | 118, 119, 120 |
| POWER_FY2026 | eps_basic | 2.86 | none | 168 | 109, 110, 111 |
| KOHC_FY2026 | total_assets | 80,009,239,225.00 | none | 147 | 55, 58, 74, 148 |
| KOHC_FY2026 | total_equity | 58,646,462,536.00 | none | 146 | 55, 58, 74, 148 |
| MTL_FY2026 | total_assets | 34,135,647.00 | none | 193 | 90, 91, 194, 195 |

**Why:** The keyword page finder (`locate_statement_pages`) sent Gemini summary pages instead of the statements: POWER pp. 109-111 and PIOC pp. 118-120 are the multi-year analysis pages, KOHC pp. 55/58/74 are 'Key financial data for the last six years' and 'Horizontal & vertical analysis', MTL pp. 90-91 sit next to the vertical analysis (p. 92). Gemini correctly returned null instead of guessing.


## api: Wrong statement page found (4)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | profit_before_tax | 10,087,307.00 | 10,191.54 | 149 | 118, 119, 120 |
| PIOC_FY2026 | total_equity | 49,522,014.00 | 31,909.21 | 148 | 118, 119, 120 |
| ATRL_FY2026 | total_assets | 293,173,169.00 | 277,786,810.00 | 235 | 148, 149, 168, 236 |
| ATRL_FY2026 | total_equity | 186,398,731.00 | 172,804,030.00 | 234 | 148, 149, 168, 236 |

**Why:** Same page finder. PIOC: the Rs-million analysis pages again. ATRL: the finder mixed a balance sheet from outside the consolidated statements (pp. 148-149) with the consolidated income statement (p. 236), so assets/equity are from a different set than the gold (consolidated, pp. 234-235).


## api: Unit off by 1000x (Rs '000 vs Rs million) (3)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | revenue | 38,578,528.00 | 38,578.53 | 149 | 118, 119, 120 |
| PIOC_FY2026 | net_profit | 6,594,152.00 | 6,594.15 | 149 | 118, 119, 120 |
| PIOC_FY2026 | total_assets | 79,437,602.00 | 79,437.60 | 147 | 118, 119, 120 |

**Why:** Not a reading error: PIOC's analysis pages print the same figures in Rs million (38,578.53 vs 38,578,528 thousand). Caused by the page finder, not by Gemini.


## columns: Field missing on the right page (label not matched / unlabelled total) (14)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | total_equity | 49,522,014.00 | none | 148 | 147, 148, 149 |
| OGDC_FY2026 | total_assets | 1,852,826,589.00 | none | 156 | 156, 157 |
| OGDC_FY2026 | total_equity | 1,519,547,299.00 | none | 156 | 156, 157 |
| POL_FY2026 | total_assets | 202,224,026.00 | none | 159 | 158, 159, 160 |
| POL_FY2026 | total_equity | 94,392,570.00 | none | 158 | 158, 159, 160 |
| PRL_FY2026 | total_assets | 130,748,549.00 | none | 67 | 67, 70, 71 |
| PRL_FY2026 | total_equity | 42,769,992.00 | none | 67 | 67, 70, 71 |
| HUBC_FY2026 | total_equity | 258,007,509.00 | none | 277 | 275, 277 |
| KOHC_FY2026 | total_assets | 80,009,239,225.00 | none | 147 | 146, 147, 148 |
| KOHC_FY2026 | total_equity | 58,646,462,536.00 | none | 146 | 146, 147, 148 |
| MTL_FY2026 | total_assets | 34,135,647.00 | none | 193 | 192, 193, 194 |
| MLCF_Q1FY2027 | total_assets | 245,332,202.00 | none | 28 | 27, 28, 29 |
| ATRL_9MFY2026 | eps_basic | 178.93 | none | 36 | 34, 35, 36 |
| ATRL_9MFY2026 | total_equity | 171,579,444.00 | none | 34 | 34, 35, 36 |

**Why:** Unlabelled totals: the balance-sheet total is a bare number under a rule with no 'Total assets' / 'Total equity' text (seen by hand in MLCF p. 28, KOHC pp. 146-147, ATRL p. 234). OGDC/PRL put two tables side by side on one landscape page. ATRL 9M's EPS sits in a 4-column block under a heading row. The equity-from-assets-minus-liabilities fallback only fires when 'Total liabilities' is printed.


## columns: Field missing - the right page was not found (6)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| ATRL_FY2026 | revenue | 341,794,386.00 | none | 236 | 243, 244, 245, 246 |
| ATRL_FY2026 | profit_before_tax | 35,945,788.00 | none | 236 | 243, 244, 245, 246 |
| ATRL_FY2026 | net_profit | 26,062,169.00 | none | 236 | 243, 244, 245, 246 |
| ATRL_FY2026 | eps_basic | 244.45 | none | 236 | 243, 244, 245, 246 |
| ATRL_FY2026 | total_assets | 293,173,169.00 | none | 235 | 243, 244, 245, 246 |
| ATRL_FY2026 | total_equity | 186,398,731.00 | none | 234 | 243, 244, 245, 246 |

**Why:** ATRL FY: the title-tag page finder chose pp. 243-246 (after the consolidated statements) instead of pp. 234-236, so all 6 fields were missed. One report, one wrong page choice, 6 failures.


## columns: Wrong line item, or consolidated vs unconsolidated mixed (3)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| MTL_FY2026 | net_profit | 7,945,058.00 | 8,071,378.00 | 194 | 192, 193, 194 |
| ATRL_9MFY2026 | profit_before_tax | 25,608,859.00 | 25,761,069.00 | 36 | 34, 35, 36 |
| ATRL_9MFY2026 | net_profit | 19,076,760.00 | 15,766,688.00 | 36 | 34, 35, 36 |

**Why:** MTL: the owners' share (7,945,058) is printed under a separate 'Attributable to:' block more than 4 rows below the total, so the rule kept the total (8,071,378). ATRL 9M: the profit lines wrap over three text lines; the rule matched the pre-levy line (25,761,069) and 'profit after taxation from refinery operations' (15,766,688) instead of the total profit for the period.


## rules: Wrong line item, or consolidated vs unconsolidated mixed (22)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| LUCK_FY2026 | net_profit | 89,042,169.00 | 96,456,241.00 | 289 | 288, 289, 290 |
| POL_FY2026 | revenue | 64,248,245.00 | 89,353,222.00 | 160 | 158, 159, 160, 161 |
| POL_FY2026 | profit_before_tax | 43,706,018.00 | 44,060,928.00 | 160 | 158, 159, 160, 161 |
| HUBC_FY2026 | net_profit | 49,630,724.00 | 56,257,178.00 | 275 | 275, 276, 277, 278 |
| HUBC_FY2026 | total_equity | 258,007,509.00 | 422,563,444.00 | 277 | 275, 276, 277, 278 |
| AGIL_FY2026 | revenue | 17,383,149.00 | 9,221.00 | 151 | 103, 150, 151 |
| AGIL_FY2026 | total_equity | 7,192,975.00 | 10,416,925.00 | 150 | 103, 150, 151 |
| GHNI_FY2026 | revenue | 60,658,134.00 | 202,253.00 | 112 | 96, 97, 112, 113 |
| ATRL_FY2026 | net_profit | 26,062,169.00 | 21,447.68 | 236 | 148, 149, 168, 236 |
| ATRL_FY2026 | eps_basic | 244.45 | 201.17 | 236 | 148, 149, 168, 236 |
| MTL_FY2026 | revenue | 64,238,354.00 | 63,755,236.00 | 194 | 90, 91, 194, 195 |
| MTL_FY2026 | profit_before_tax | 14,638,779.00 | 14,433,876.00 | 194 | 90, 91, 194, 195 |
| MTL_FY2026 | net_profit | 7,945,058.00 | 7,840,789.00 | 194 | 90, 91, 194, 195 |
| MLCF_Q1FY2027 | revenue | 30,917,726.00 | 20,070,987.00 | 29 | 9, 27, 28, 29 |
| MLCF_Q1FY2027 | profit_before_tax | 6,854,372.00 | 3,448,681.00 | 29 | 9, 27, 28, 29 |
| MLCF_Q1FY2027 | net_profit | 3,706,974.00 | 2,135,750.00 | 29 | 9, 27, 28, 29 |
| MLCF_Q1FY2027 | eps_basic | 3.54 | 2.04 | 29 | 9, 27, 28, 29 |
| ATRL_9MFY2026 | revenue | 224,942,750.00 | 87,726,400.00 | 36 | 12, 34, 35, 36 |
| ATRL_9MFY2026 | profit_before_tax | 25,608,859.00 | 17,911,107.00 | 36 | 12, 34, 35, 36 |
| ATRL_9MFY2026 | net_profit | 19,076,760.00 | 10,947,570.00 | 36 | 12, 34, 35, 36 |
| ATRL_9MFY2026 | eps_basic | 178.93 | 102.68 | 36 | 12, 34, 35, 36 |
| ATRL_9MFY2026 | total_equity | 171,579,444.00 | 265,858,014.00 | 34 | 12, 34, 35, 36 |

**Why:** The baseline takes the first label match and the first number after it: total profit instead of the owners' share (LUCK, HUBC), gross sales instead of net sales (POL), pre-levy PBT (POL), 'Total equity and liabilities' as equity (HUBC, AGIL), and in interim reports the three-month or unconsolidated figure instead of the period's consolidated one (MLCF Q1, ATRL 9M).


## rules: Field missing on the right page (label not matched / unlabelled total) (12)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| OGDC_FY2026 | total_assets | 1,852,826,589.00 | none | 156 | 156, 157, 158 |
| OGDC_FY2026 | total_equity | 1,519,547,299.00 | none | 156 | 156, 157, 158 |
| POL_FY2026 | total_assets | 202,224,026.00 | none | 159 | 158, 159, 160, 161 |
| POL_FY2026 | total_equity | 94,392,570.00 | none | 158 | 158, 159, 160, 161 |
| PRL_FY2026 | profit_before_tax | 24,146,650.00 | none | 67 | 67, 68 |
| PRL_FY2026 | net_profit | 15,779,957.00 | none | 67 | 67, 68 |
| PRL_FY2026 | eps_basic | 25.05 | none | 67 | 67, 68 |
| PRL_FY2026 | total_assets | 130,748,549.00 | none | 67 | 67, 68 |
| PRL_FY2026 | total_equity | 42,769,992.00 | none | 67 | 67, 68 |
| AGIL_FY2026 | profit_before_tax | 1,685,924.00 | none | 151 | 103, 150, 151 |
| AGIL_FY2026 | net_profit | 1,203,408.00 | none | 151 | 103, 150, 151 |
| MLCF_Q1FY2027 | total_assets | 245,332,202.00 | none | 28 | 9, 27, 28, 29 |

**Why:** Labels the regexes do not cover ('Profit / (loss) before taxation' in PRL, the 'ﬁ' ligature in AGIL's 'Proﬁt') and unlabelled totals (OGDC, POL, MLCF).


## rules: Unit off by 1000x (Rs '000 vs Rs million) (8)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | revenue | 38,578,528.00 | 38,578.53 | 149 | 118, 119, 120 |
| PIOC_FY2026 | net_profit | 6,594,152.00 | 6,594.15 | 149 | 118, 119, 120 |
| PIOC_FY2026 | total_assets | 79,437,602.00 | 79,437.60 | 147 | 118, 119, 120 |
| ATRL_FY2026 | revenue | 341,794,386.00 | 341,588.52 | 236 | 148, 149, 168, 236 |
| ATRL_FY2026 | profit_before_tax | 35,945,788.00 | 35,841.76 | 236 | 148, 149, 168, 236 |
| KOHC_FY2026 | revenue | 38,530,653,234.00 | 38,530,653.00 | 148 | 55, 58, 74, 148 |
| KOHC_FY2026 | profit_before_tax | 15,927,964,099.00 | 15,967,898.00 | 148 | 55, 58, 74, 148 |
| KOHC_FY2026 | net_profit | 10,697,459,177.00 | 10,696,851.00 | 148 | 55, 58, 74, 148 |

**Why:** PIOC and ATRL: values read from Rs-million summary pages. KOHC reports in plain Rupees; the baseline guessed thousands from another page and read a rounded summary figure.


## rules: Wrong statement page found (8)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | profit_before_tax | 10,087,307.00 | 10,191.54 | 149 | 118, 119, 120 |
| PIOC_FY2026 | total_equity | 49,522,014.00 | 79,437.60 | 148 | 118, 119, 120 |
| POWER_FY2026 | total_equity | 24,014,746.00 | 47,400,245.00 | 167 | 109, 110, 111 |
| ATRL_FY2026 | total_assets | 293,173,169.00 | 277,786.81 | 235 | 148, 149, 168, 236 |
| ATRL_FY2026 | total_equity | 186,398,731.00 | 277,786.81 | 234 | 148, 149, 168, 236 |
| KOHC_FY2026 | total_assets | 80,009,239,225.00 | 0.48 | 147 | 55, 58, 74, 148 |
| MTL_FY2026 | total_assets | 34,135,647.00 | 32,214,643.00 | 193 | 90, 91, 194, 195 |
| SURC_FY2026 | total_equity | 15,582,173.00 | 25,506,589.00 | 46 | 35, 37, 38, 48 |

**Why:** Multi-year summaries chosen over statements: SURC's equity came from p. 35-38 ('Key operating and financial data', 'Six years at a glance'), POWER from 'Six years at a glance'; KOHC 'total assets' = 0.48 is a ratio from an analysis page.


## rules: Field missing - the right page was not found (6)

| Report | Field | Gold | Predicted | Gold page | Pages used |
|---|---|---|---|---|---|
| PIOC_FY2026 | eps_basic | 29.03 | none | 149 | 118, 119, 120 |
| GHNI_FY2026 | total_assets | 46,268,569.00 | none | 110 | 96, 97, 112, 113 |
| GHNI_FY2026 | total_equity | 22,355,334.00 | none | 111 | 96, 97, 112, 113 |
| POWER_FY2026 | eps_basic | 2.86 | none | 168 | 109, 110, 111 |
| KOHC_FY2026 | total_equity | 58,646,462,536.00 | none | 146 | 55, 58, 74, 148 |
| MTL_FY2026 | total_equity | 10,881,050.00 | none | 192 | 90, 91, 194, 195 |

**Why:** Statement pages not among the 4 pages the keyword finder picked (GHNI balance sheet pp. 110-111, PIOC/POWER EPS).


## Reports we had to drop or correct while labelling (data failures, not model failures)

* **PPL Q1 FY2027**: the financial statements (pp. 20-54) are scanned images with no text layer; without OCR neither the extractor nor the labelling can read them. Dropped.
* **FZCM FY2026**: Gemini returned nothing for all six fields during drafting. Dropped.
* **"BCL" FY2026** (PSX document 284695) is the annual report of **Millat Tractors** (Bolan Castings is its subsidiary). Renamed to MTL.
* **SURC**: the draft took total assets/equity from the six-year summary (p. 35); corrected by hand to the balance sheet (pp. 46-47).
* **ATRL 9M**: the interim profit-or-loss has 'Three months ended | Nine months ended'; our first column rule assumed the cumulative period is on the left and missed the prior values. Fixed: columns are now chosen by their period heading (test added).

## Takeaways

1. **Gemini Flash-Lite generalises: 87.0% on the 9 reports we studied, 86.1% on 6 new ones.** All 12 of its failures start at the keyword page finder (9 wrong/missing page, 3 unit errors from Rs-million summary pages), none from misreading a correct page.
2. **Column-aware rules double the baseline for free (37.8% -> 74.4%) but overfit**: 85.2% on the dev reports, 58.3% held-out. Their main weakness is unlabelled totals.
3. **The prior-year column was never taken** (0% for all four extractors) and the column check corrected 0 Gemini values: on PSX statements it is a safeguard, not a measured gain.
4. **Next step**: use the statement-title tags (93.3% page located vs 86.7% for the keyword finder) to choose Gemini's pages.
5. **Caveat**: the 36 held-out labels were drafted by Gemini and then checked by hand, which may favour Gemini's line choices slightly.
