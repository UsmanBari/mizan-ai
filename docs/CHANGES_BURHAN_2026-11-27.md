# Burhan's changes, 27 Nov (ingest + extraction), for Usman and his agent

Supervisor points covered: 4 (tables / columns), 5 (consolidated vs unconsolidated),
6 (reporting period), 18 (fetching without duplicates). Nothing here calls an LLM
except `draft_labels.py` (one call per new report).

## 1. Document metadata (`backend/mizan/ingest/metadata.py`)

`Document` (models.py) has new fields, all filled by `ingest_pdf`:

| field | example | how |
|---|---|---|
| `period_type` | `annual` / `half-yearly` / `quarterly` / `nine-months` (store.py's names) | title, checked against statement headers |
| `period_end` | `2026-09-30` | "for the ... ended <date>" / "as at <date>" in statement headers |
| `months_covered` | `12`, `9`, `6`, `3`, or `null` | "nine months period ended" -> 9 |
| `period_warnings` | `["period type mismatch: title says annual, statements say quarterly"]` | statements win, mismatch kept |
| `statement_pages` | `{289: {"statement": "income", "basis": "consolidated"}}` | page title |
| `sha256`, `remote_id` | PDF hash, PSX document id | de-duplication |

For the compare / trends API: only compare documents with the same `period_type`
and `months_covered`, and take values from pages whose `basis` matches the question.
On our 9 labelled reports, the basis tag agrees with the hand label on 54/54 rows.

## 2. De-duplication (`ingest/dedupe.py`, `ingest/pipeline.py`)

* `ingest_pdf`: same PDF bytes already in the store -> returns the existing document.
* `ingest_psx_symbol`: skips known PSX ids before downloading, and identical PDFs
  posted under a second id after downloading. A JSON ledger (`data/ingested.json`)
  survives restarts; the watcher uses `only_unseen=True`, so a filing alerts once even
  after the in-memory store is wiped.
* `eval/fetch_psx_reports.py`: same id or same bytes -> kept once; warns on very
  short PDFs (the INDU "annual report" was a 2-page notice).

## 3. Column-safe extraction (`backend/mizan/extraction/columns.py`)

* Finds the header row ("Note | 2026 | 2025", "Sep 30, 2026 | June 30, 2026",
  "Nine months ended ... 2026 2025 2026 2025") from word x-positions; numbers are
  assigned to the nearest column; the note column is dropped; current = latest date.
* Handles landscape pages with two tables side by side (OGDC, PRL).
* `ColumnExtractor` ("columns" in run_extraction): rules + current-column values +
  pages from the statement tags + owners' share for consolidated profit +
  "total equity" computed as assets - liabilities when there is no such line.
* `ColumnCheckedLLM` ("api+columns"): reuses the API extractor's answer and re-reads
  each value from the current-year column of the row it came from. No extra API call.
* `run_extraction.py` now reports `prior_column_rate` and splits accuracy into dev
  (the 9 reports we studied while writing these rules) and held-out (new reports).
  **Only the held-out number is fair for the columns extractor.**

## 4. Labels

* `eval/draft_labels.py`: drafts 6 rows per new report (LLM picks the line, code reads
  current and prior columns), `labeller=claude-draft`.
* `build_psx_testset.py` now **skips `claude-draft` rows by default** (`--include-drafts`
  to override). So the PSX QA set only uses verified rows. HUBC / AGIL / GHNI / POWER
  (24 rows) are still drafts: Usman, please verify them.
* `verify_labels.py` works per report (`--doc ATRL_H1FY2026`), since one symbol can
  now have several reports; `--drafts` shows only unchecked rows.

## 5. Tests

`backend/tests/test_metadata_columns.py`: 24 tests (period from title / headers /
mismatch, basis tags, ledger, same-PDF-twice, PSX id + bytes dedupe across restart,
header columns, note column, blank current year, 9-month 4-column table, interim
balance sheet, LLM prior-column value corrected by code).

## 6. Small changes in Usman's `store.py` (so interim reports work)

* `load_psx_labels`: period type and months now come from `psx_reports.csv`
  (`doc_type` of the row's doc_id) instead of always `annual` / 12. Interim balance-sheet
  rows add no "prior" fact, because their comparative column is the last year-end, not
  the same date a year earlier. Empty draft rows are skipped.
* `_facts_from_highlights`: uses `doc.period_end` (checked at ingest) first.
