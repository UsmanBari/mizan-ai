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

## Still to add
- 5+ more failures from notebook 03 (auto-tagged), with a manual note each.
