# Label Check Evidence for Usman (HUBC, AGIL, GHNI, POWER)

This document provides line-by-line evidence from the downloaded PSX FY2026 Annual Reports for the 4 assigned companies (`HUBC`, `AGIL`, `GHNI`, `POWER`), corresponding to the 24 rows in `eval/data/psx_labels.csv`.

**Status**: Verified via `python eval/verify_labels.py --who usman`.
**Result**: 24/24 rows matched. **0 row(s) need a closer look.**

> Note: Per Hard Rule 2, `eval/data/psx_labels.csv` is NOT edited. This evidence is provided for final human sign-off before changing the `labeller` column.

---

## 1. Summary of Checked Rows

| Symbol | Company | Field | Page | Current (FY2026) | Prior (FY2025) | Match Status | Notes |
|---|---|---|---|---|---|---|---|
| **HUBC** | Hub Power Co | `revenue` | 275 | 71,126,352 | 83,351,492 | [ok] | Consolidated net revenue from contracts |
| **HUBC** | Hub Power Co | `profit_before_tax` | 275 | 69,600,910 | 64,115,150 | [ok] | Continuing operations after levy |
| **HUBC** | Hub Power Co | `net_profit` | 275 | 49,630,724 | 46,131,156 | [ok] | Attributable to owners of holding company |
| **HUBC** | Hub Power Co | `eps_basic` | 275 | 38.26 | 35.56 | [ok] | Basic EPS (holding co) |
| **HUBC** | Hub Power Co | `total_assets` | 277 | 422,563,444 | 414,722,187 | [ok] | Consolidated balance sheet total assets |
| **HUBC** | Hub Power Co | `total_equity` | 277 | 258,007,509 | 243,921,905 | [ok] | Consolidated total equity |
| **AGIL** | Agriauto Industries | `revenue` | 151 | 17,383,149 | 11,863,435 | [ok] | Consolidated turnover – net |
| **AGIL** | Agriauto Industries | `profit_before_tax` | 151 | 1,685,924 | 206,236 | [ok] | Consolidated profit before tax (note 'fi' ligature) |
| **AGIL** | Agriauto Industries | `net_profit` | 151 | 1,203,408 | 238,324 | [ok] | Consolidated profit after taxation |
| **AGIL** | Agriauto Industries | `eps_basic` | 151 | 33.43 | 6.62 | [ok] | Basic and diluted EPS |
| **AGIL** | Agriauto Industries | `total_assets` | 150 | 10,416,925 | 9,654,576 | [ok] | Consolidated balance sheet total assets |
| **AGIL** | Agriauto Industries | `total_equity` | 150 | 7,192,975 | 6,052,567 | [ok] | Consolidated total equity |
| **GHNI** | Ghandhara Industries | `revenue` | 112 | 60,658,134 | 37,462,866 | [ok] | Sales – net |
| **GHNI** | Ghandhara Industries | `profit_before_tax` | 112 | 11,412,478 | 6,453,181 | [ok] | Profit before income taxation |
| **GHNI** | Ghandhara Industries | `net_profit` | 112 | 6,926,718 | 4,583,655 | [ok] | Profit for the year |
| **GHNI** | Ghandhara Industries | `eps_basic` | 112 | 162.57 | 107.58 | [ok] | Basic and diluted EPS |
| **GHNI** | Ghandhara Industries | `total_assets` | 110 | 46,268,569 | 29,275,270 | [ok] | Balance sheet total assets |
| **GHNI** | Ghandhara Industries | `total_equity` | 111 | 22,355,334 | 13,551,899 | [ok] | Total equity |
| **POWER** | Power Cement | `revenue` | 168 | 33,978,969 | 29,520,136 | [ok] | Revenue from contracts with customers |
| **POWER** | Power Cement | `profit_before_tax` | 168 | 5,595,964 | 1,572,313 | [ok] | Profit before taxation |
| **POWER** | Power Cement | `net_profit` | 168 | 3,784,470 | 814,996 | [ok] | Profit after taxation |
| **POWER** | Power Cement | `eps_basic` | 168 | 2.86 | 0.44 | [ok] | Basic EPS |
| **POWER** | Power Cement | `total_assets` | 166 | 47,400,245 | 47,680,009 | [ok] | Statement of financial position total assets |
| **POWER** | Power Cement | `total_equity` | 167 | 24,014,746 | 23,529,257 | [ok] | Total equity |

---

## 2. Detailed Line Matches from Source PDFs

### HUBC (The Hub Power Company Limited) - FY2026 Annual Report
- **PDF File**: `eval/data/psx_pdfs/HUBC_FY2026.pdf`
- **Page 275** (Consolidated Statement of Profit or Loss):
  - `revenue`:
    * Current: `71,126,352.00` -> Matched line: `Revenue from contracts with customers - net | 5 | 71,126,352 | 83,351,492`
    * Prior: `83,351,492.00` -> Matched line: `Revenue from contracts with customers - net | 5 | 71,126,352 | 83,351,492`
  - `profit_before_tax`:
    * Current: `69,600,910.00` -> Matched line: `PROFIT BEFORE TAXATION FROM CONTINUING OPERATIONS | 69,600,910 | 64,115,150`
    * Prior: `64,115,150.00` -> Matched line: `PROFIT BEFORE LEVY AND TAXATION FROM CONTINUING OPERATIONS | 70,248,006 | 64,115,150`
  - `net_profit`:
    * Current: `49,630,724.00` -> Matched line: `- Owners of the holding company | 49,630,724 | 46,131,156`
    * Prior: `46,131,156.00` -> Matched line: `- Owners of the holding company | 49,630,724 | 46,131,156`
  - `eps_basic`:
    * Current: `38.26` -> Matched line: `- Continuing operations | 38.26 | 35.44`
    * Prior: `35.56` -> Matched line: `of the holding company | 43 | 38.26 | 35.56`
- **Page 277** (Consolidated Statement of Financial Position):
  - `total_assets`:
    * Current: `422,563,444.00` -> Matched line: `TOTAL ASSETS | 422,563,444 | 414,722,187`
    * Prior: `414,722,187.00` -> Matched line: `TOTAL ASSETS | 422,563,444 | 414,722,187`
  - `total_equity`:
    * Current: `258,007,509.00` -> Matched line: `258,007,509 | 243,921,905`
    * Prior: `243,921,905.00` -> Matched line: `258,007,509 | 243,921,905`

---

### AGIL (Agriauto Industries Limited) - FY2026 Annual Report
- **PDF File**: `eval/data/psx_pdfs/AGIL_FY2026.pdf`
- **Page 151** (Consolidated Statement of Profit or Loss):
  - `revenue`:
    * Current: `17,383,149.00` -> Matched line: `Turnover – net | 25 | 17,383,149 | 11,863,435`
    * Prior: `11,863,435.00` -> Matched line: `Turnover – net | 25 | 17,383,149 | 11,863,435`
  - `profit_before_tax`:
    * Current: `1,685,924.00` -> Matched line: `Proﬁt before levy and taxation | 1,685,924 | 353,918`
    * Prior: `206,236.00` -> Matched line: `Proﬁt before taxation | 1,685,924 | 206,236`
  - `net_profit`:
    * Current: `1,203,408.00` -> Matched line: `Proﬁt after taxation | 1,203,408 | 238,324`
    * Prior: `238,324.00` -> Matched line: `Proﬁt after taxation | 1,203,408 | 238,324`
  - `eps_basic`:
    * Current: `33.43` -> Matched line: `Earnings per share – basic and diluted | 34 | 33.43 | 6.62`
    * Prior: `6.62` -> Matched line: `Earnings per share – basic and diluted | 34 | 33.43 | 6.62`
- **Page 150** (Consolidated Statement of Financial Position):
  - `total_assets`:
    * Current: `10,416,925.00` -> Matched line: `Total assets | 10,416,925 | 9,654,576`
    * Prior: `9,654,576.00` -> Matched line: `Total assets | 10,416,925 | 9,654,576`
  - `total_equity`:
    * Current: `7,192,975.00` -> Matched line: `7,192,975 | 6,052,567`
    * Prior: `6,052,567.00` -> Matched line: `7,192,975 | 6,052,567`

---

### GHNI (Ghandhara Industries Limited) - FY2026 Annual Report
- **PDF File**: `eval/data/psx_pdfs/GHNI_FY2026.pdf`
- **Page 112** (Statement of Profit or Loss):
  - `revenue`:
    * Current: `60,658,134.00` -> Matched line: `Sales - net | 29 | 60,658,134 | 37,462,866`
    * Prior: `37,462,866.00` -> Matched line: `Sales - net | 29 | 60,658,134 | 37,462,866`
  - `profit_before_tax`:
    * Current: `11,412,478.00` -> Matched line: `Profit before income taxation | 11,412,478 | 6,453,181`
    * Prior: `6,453,181.00` -> Matched line: `Profit before income taxation | 11,412,478 | 6,453,181`
  - `net_profit`:
    * Current: `6,926,718.00` -> Matched line: `Profit for the year | 6,926,718 | 4,583,655`
    * Prior: `4,583,655.00` -> Matched line: `Profit for the year | 6,926,718 | 4,583,655`
  - `eps_basic`:
    * Current: `162.57` -> Matched line: `Basic and diluted earnings per share | 37 | 162.57 | 107.58`
    * Prior: `107.58` -> Matched line: `Basic and diluted earnings per share | 37 | 162.57 | 107.58`
- **Page 110 & 111** (Statement of Financial Position):
  - `total_assets` (p. 110):
    * Current: `46,268,569.00` -> Matched line: `Total assets | 46,268,569 | 29,275,270`
    * Prior: `29,275,270.00` -> Matched line: `Total assets | 46,268,569 | 29,275,270`
  - `total_equity` (p. 111):
    * Current: `22,355,334.00` -> Matched line: `Total equity | 22,355,334 | 13,551,899`
    * Prior: `13,551,899.00` -> Matched line: `Total equity | 22,355,334 | 13,551,899`

---

### POWER (Power Cement Limited) - FY2026 Annual Report
- **PDF File**: `eval/data/psx_pdfs/POWER_FY2026.pdf`
- **Page 168** (Statement of Profit or Loss):
  - `revenue`:
    * Current: `33,978,969.00` -> Matched line: `Revenue from contracts with customers | 26 | 33,978,969 | 29,520,136`
    * Prior: `29,520,136.00` -> Matched line: `Revenue from contracts with customers | 26 | 33,978,969 | 29,520,136`
  - `profit_before_tax`:
    * Current: `5,595,964.00` -> Matched line: `Profit before taxation | 5,595,964 | 1,572,313`
    * Prior: `1,572,313.00` -> Matched line: `Profit before taxation | 5,595,964 | 1,572,313`
  - `net_profit`:
    * Current: `3,784,470.00` -> Matched line: `Profit after taxation | 3,784,470 | 814,996`
    * Prior: `814,996.00` -> Matched line: `Profit after taxation | 3,784,470 | 814,996`
  - `eps_basic`:
    * Current: `2.86` -> Matched line: `-Basic | 2.86 | 0.44`
    * Prior: `0.44` -> Matched line: `-Basic | 2.86 | 0.44`
- **Page 166 & 167** (Statement of Financial Position):
  - `total_assets` (p. 166):
    * Current: `47,400,245.00` -> Matched line: `TOTAL ASSETS | 47,400,245 | 47,680,009`
    * Prior: `47,680,009.00` -> Matched line: `TOTAL ASSETS | 47,400,245 | 47,680,009`
  - `total_equity` (p. 167):
    * Current: `24,014,746.00` -> Matched line: `TOTAL EQUITY | 24,014,746 | 23,529,257`
    * Prior: `23,529,257.00` -> Matched line: `TOTAL EQUITY | 24,014,746 | 23,529,257`
