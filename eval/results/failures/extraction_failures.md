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
