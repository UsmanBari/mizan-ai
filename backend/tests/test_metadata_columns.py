"""Tests for reporting-period metadata, statement-basis tags, de-duplication and
column-safe extraction (supervisor feedback points 4, 5, 6 and 18)."""
import pymupdf
import pytest

from mizan.extraction.columns import (ColumnCheckedLLM, ColumnExtractor, current_prior, label_of,
                                      prior_for_value, read_page_rows)
from mizan.extraction.extractor import ExtractionResult
from mizan.ingest.dedupe import Ledger, sha256_file
from mizan.ingest.metadata import (Period, document_metadata, period_from_statements, period_from_title,
                                   reconcile, statement_basis, statement_kind, tag_statement_pages)
from mizan.llm import Usage
from mizan.models import FieldValue, FinancialHighlights
from mizan.store import MemoryStore


# ---------- helpers ----------------------------------------------------------
def table_pdf(path, pages):
    """pages: list of lists of (x, y, text) - text placed at exact positions."""
    doc = pymupdf.open()
    for items in pages:
        pg = doc.new_page()
        for x, y, t in items:
            pg.insert_text((x, y), t, fontsize=9)
    doc.save(str(path))
    return path


def statement(title, header, rows, y0=60):
    """A statement page: title lines, a header row {x: text}, then rows
    (label, {x: number})."""
    items = [(50, y0 + 12 * i, t) for i, t in enumerate(title)]
    y = y0 + 12 * len(title) + 14
    items += [(x, y, t) for x, t in header.items()]
    for label, nums in rows:
        y += 14
        items.append((50, y, label))
        items += [(x, y, t) for x, t in nums.items()]
    return items


# ---------- period metadata ---------------------------------------------------
@pytest.mark.parametrize("title,ptype,end,months", [
    ("Financial Results for the year ended June 30, 2026", "annual", "2026-06-30", 12),
    ("Transmission of Annual Report for the Year Ended 30.06.2026", "annual", "2026-06-30", 12),
    ("Transmission of Quarterly Financial Statements for the Period Ended 30.09.2026", "quarterly",
     "2026-09-30", None),
    ("Financial Results for the quarter ended September 30, 2026", "quarterly", "2026-09-30", 3),
    ("Condensed Interim Financial Statements For the Six Months Period Ended December 31, 2025",
     "half-yearly", "2025-12-31", 6),
    ("Third Quarter and Nine Months Period Ended March 31, 2026", "nine-months", "2026-03-31", 9),
    ("Half yearly report", "half-yearly", "", 6),
])
def test_period_from_title(title, ptype, end, months):
    p = period_from_title(title)
    assert (p.period_type, p.period_end, p.months_covered) == (ptype, end, months)


def test_statement_headers_win_and_mismatch_is_flagged():
    pages = {5: "Condensed Interim Statement of Profit or Loss (Un-audited)\n"
                "For the nine months period ended March 31, 2026\nNote | 2026 | 2025\nSales | 1,000 | 900",
             6: "Condensed Interim Statement of Financial Position\nAs at March 31, 2026\nTotal assets | 5,000 | 4,000"}
    stmt = period_from_statements(pages)
    assert (stmt.period_type, stmt.period_end, stmt.months_covered) == ("nine-months", "2026-03-31", 9)
    final, warnings = reconcile(period_from_title("Annual Report 2026"), stmt)
    assert final.period_type == "nine-months" and final.months_covered == 9
    assert any("period type mismatch" in w for w in warnings)
    md = document_metadata(pages, "Transmission of Quarterly Financial Statements for the Period Ended 31.03.2026")
    assert md.period.period_end == "2026-03-31" and not [w for w in md.warnings if "end mismatch" in w]
    assert md.period.period_type == "nine-months"   # "quarterly" title, but the statements cover 9 months


def test_period_end_mismatch_is_flagged():
    _, w = reconcile(Period("annual", "2026-06-30", 12, "title"), Period("annual", "2025-06-30", 12, "statements"))
    assert any("period end mismatch" in x for x in w)


@pytest.mark.parametrize("head,basis", [
    ("Consolidated Statement of Financial Position As at June 30, 2026", "consolidated"),
    ("Unconsolidated Statement of Profit or Loss", "unconsolidated"),
    ("Un-consolidated Statement of Profit or Loss", "unconsolidated"),
    ("Condensed Interim Unconsolidated Statement of Financial Position", "unconsolidated"),
    ("Statement of Profit or Loss For the year ended June 30, 2026", "unconsolidated"),  # single set
])
def test_statement_basis(head, basis):
    assert statement_basis(head) == basis


def test_statement_tags_skip_notes_and_auditor_pages():
    pages = {1: "Notes to the Consolidated Financial Statements\n1. Status and operations",
             2: "Independent Auditor's Report to the members on the Statement of Financial Position",
             3: "Consolidated Statement of Profit or Loss\nFor the year ended June 30, 2026",
             4: "Statement of Cash Flows\nFor the year ended June 30, 2026"}
    tags = tag_statement_pages(pages)
    assert set(tags) == {3, 4}
    assert tags[3].statement == "income" and tags[3].basis == "consolidated"
    assert statement_kind(pages[4]) == "cash_flow"


# ---------- de-duplication ----------------------------------------------------
def test_ledger_persists(tmp_path):
    led = Ledger(tmp_path / "ingested.json")
    led.record("LUCK_FY2026", "abc", "282262")
    again = Ledger(tmp_path / "ingested.json")          # e.g. after a restart
    assert again.seen_remote("282262") == "LUCK_FY2026" and again.seen_sha("abc") == "LUCK_FY2026"
    assert again.seen_remote("999") is None


def test_same_pdf_is_ingested_once(sample_pdf, tmp_path):
    from mizan.ingest.pipeline import ingest_pdf
    copy = tmp_path / "copy.pdf"
    copy.write_bytes(sample_pdf.read_bytes())
    assert sha256_file(copy) == sha256_file(sample_pdf)
    s = MemoryStore()
    d1 = ingest_pdf(s, sample_pdf, "HDB_FY2025", "Habib Demo Bank", "HDB", "annual", "FY2025")
    d2 = ingest_pdf(s, copy, "HDB_FY2025_again", "Habib Demo Bank", "HDB", "annual", "FY2025")
    assert d2.doc_id == "HDB_FY2025" and len(s.list_documents()) == 1
    assert d1.period_type == "annual" and d1.period_end == "2025-12-31" and d1.months_covered == 12
    assert {v["basis"] for v in d1.statement_pages.values()} == {"unconsolidated"}


def test_psx_fetch_dedupes_by_id_and_bytes(sample_pdf, tmp_path, monkeypatch):
    from mizan.ingest import pipeline, psx
    links = [psx.ReportLink("HDB", "Annual Report for the year ended December 31, 2025",
                            "https://dps.psx.com.pk/download/document/1001.pdf", doc_type="annual", period="A2025"),
             psx.ReportLink("HDB", "Transmission of Annual Report for the Year Ended 31.12.2025",
                            "https://dps.psx.com.pk/download/document/1002.pdf", doc_type="annual", period="A2025")]
    downloads = []

    def fake_download(link, dest_dir, client=None):
        downloads.append(link.remote_id)
        p = tmp_path / f"{link.remote_id}.pdf"
        p.write_bytes(sample_pdf.read_bytes())                 # PSX posts the same PDF twice
        return p
    monkeypatch.setattr(psx, "fetch_company_reports", lambda symbol, client=None: links)
    monkeypatch.setattr(psx, "download", fake_download)
    led = Ledger(tmp_path / "ingested.json")
    store = MemoryStore()
    new = pipeline.ingest_psx_symbol(store, "HDB", ledger=led)
    assert [d.remote_id for d in new] == ["1001"] and len(store.list_documents()) == 1
    assert led.seen_remote("1002") == new[0].doc_id            # second id remembered as the same filing
    downloads.clear()
    assert pipeline.ingest_psx_symbol(store, "HDB", ledger=led) == []
    assert downloads == []                                     # known PSX ids are not even downloaded
    # restart: empty store, same ledger -> re-ingested, but no second alert
    store2 = MemoryStore()
    assert pipeline.ingest_psx_symbol(store2, "HDB", ledger=led, only_unseen=True) == []
    assert len(store2.list_documents()) == 1


# ---------- column-safe extraction --------------------------------------------
HEADER = {370: "Note", 430: "2026", 505: "2025"}


@pytest.fixture
def stmt_pdf(tmp_path):
    income = statement(["Statement of Profit or Loss", "For the year ended June 30, 2026", "(Rupees in '000)"],
                       HEADER,
                       [("Revenue from contracts with customers", {372: "24", 414: "1,250,000", 489: "1,100,000"}),
                        ("Cost of sales", {372: "25", 414: "(900,000)", 489: "(800,000)"}),
                        ("Profit before taxation", {414: "300,000", 489: "250,000"}),
                        ("Taxation", {372: "36", 414: "(90,000)", 489: "(75,000)"}),
                        ("Profit after taxation", {414: "210,000", 489: "175,000"}),
                        ("Earnings per share - basic", {372: "37", 425: "21.00", 500: "17.50"})])
    balance = statement(["Statement of Financial Position", "As at June 30, 2026", "(Rupees in '000)"],
                        HEADER,
                        [("Total assets", {414: "5,000,000", 489: "4,500,000"}),
                         ("Total equity and liabilities", {414: "5,000,000", 489: "4,500,000"}),
                         ("Total liabilities", {414: "3,000,000", 489: "2,900,000"})])
    return table_pdf(tmp_path / "stmt.pdf", [[(50, 60, "Annual Report 2026")], income, balance])


def test_header_columns_and_note_column_dropped(stmt_pdf):
    pr = read_page_rows(stmt_pdf, 2)
    assert pr.tables and [c.year for c in pr.tables[0].columns if not c.is_note] == [2026, 2025]
    row = next(r for r in pr.rows if r.text.startswith("Revenue"))
    assert label_of(pr, row) == "Revenue from contracts with customers"
    assert current_prior(pr, row) == (1250000.0, 1100000.0)                    # note "24" dropped
    assert prior_for_value(pr, 210000) == 175000


def test_column_extractor_reads_current_year(stmt_pdf):
    pages = {p.page: p.text for p in __import__("mizan.ingest.parser", fromlist=["x"]).parse_pdf(stmt_pdf)}
    res = ColumnExtractor().extract(pages, "Demo", pdf_path=stmt_pdf)
    fh = res.highlights
    assert fh.revenue.value == 1250000 and fh.profit_before_tax.value == 300000
    assert fh.net_profit.value == 210000 and fh.eps_basic.value == 21.0
    assert fh.total_assets.value == 5000000
    # no "Total equity" line: computed in code as assets - liabilities
    assert fh.total_equity.value == 2000000 and fh.total_equity.label.startswith("computed")
    assert fh.unit == "thousands"


def test_blank_current_year_is_not_filled_from_prior_year(tmp_path):
    page = statement(["Statement of Profit or Loss", "For the year ended June 30, 2026"], HEADER,
                     [("Other income", {420: "-", 489: "55,000"}),
                      ("Profit after taxation", {414: "80,000", 489: "70,000"})])
    pdf = table_pdf(tmp_path / "blank.pdf", [page])
    pr = read_page_rows(pdf, 1)
    row = next(r for r in pr.rows if r.text.startswith("Other income"))
    cur, prior = current_prior(pr, row)
    assert cur == 0.0 and prior == 55000         # the dash is the current year, never 55,000


def test_nine_month_report_takes_cumulative_current_column(tmp_path):
    hdr = {300: "Nine months ended", 430: "Quarter ended"}
    years = {300: "2026", 360: "2025", 430: "2026", 490: "2025"}
    items = statement(["Condensed Interim Statement of Profit or Loss",
                       "For the nine months period ended March 31, 2026"], hdr, [])
    y = items[-1][1] + 14
    items += [(x, y, t) for x, t in years.items()]
    items += [(50, y + 14, "Sales - net"), (290, y + 14, "9,000"), (350, y + 14, "8,000"),
              (420, y + 14, "3,100"), (480, y + 14, "2,900")]
    pdf = table_pdf(tmp_path / "9m.pdf", [items])
    pr = read_page_rows(pdf, 1)
    row = next(r for r in pr.rows if r.text.startswith("Sales"))
    assert current_prior(pr, row) == (9000.0, 8000.0)


def test_interim_balance_sheet_current_is_latest_date(tmp_path):
    hdr = {400: "Sep 30, 2026", 490: "June 30, 2026"}
    page = statement(["Condensed Interim Statement of Financial Position", "As at September 30, 2026"], hdr,
                     [("Total assets", {400: "7,700", 490: "7,000"})])
    pr = read_page_rows(table_pdf(tmp_path / "q1.pdf", [page]), 1)
    row = next(r for r in pr.rows if r.text.startswith("Total assets"))
    assert current_prior(pr, row) == (7700.0, 7000.0)


def test_llm_value_from_prior_column_is_corrected_by_code(stmt_pdf):
    fh = FinancialHighlights(company="Demo", net_profit=FieldValue(value=175000, page=2, label="Profit after taxation"),
                             revenue=FieldValue(value=1250000, page=2, label="Revenue"))
    checker = ColumnCheckedLLM()
    out = checker.correct(ExtractionResult(fh, [2, 3], Usage()), stmt_pdf)
    assert out.highlights.net_profit.value == 210000          # LLM took 2025; code reads 2026
    assert out.highlights.revenue.value == 1250000            # already right: unchanged
    assert checker.corrections == [{"field": "net_profit", "page": 2, "llm": 175000, "code": 210000.0}]


def test_three_months_first_layout_takes_nine_month_columns(tmp_path):
    """ATRL's 9M report: "Three months ended | Nine months ended" - the cumulative
    period is on the RIGHT, so 'left-most' would read the quarter."""
    items = [(50, 60, "Condensed Interim Consolidated Statement of Profit or Loss"),
             (50, 72, "For The Nine Months Period Ended March 31, 2026"),
             (290, 100, "Three months ended"), (420, 100, "Nine months ended")]
    years = {290: "2026", 350: "2025", 420: "2026", 480: "2025"}
    items += [(x, 126, t) for x, t in years.items()]
    items += [(50, 145, "Net sales"), (280, 145, "87,772"), (340, 145, "74,602"),
              (410, 145, "224,942"), (470, 145, "235,459")]
    pr = read_page_rows(table_pdf(tmp_path / "atrl9m.pdf", [items]), 1)
    row = next(r for r in pr.rows if r.text.startswith("Net sales"))
    assert current_prior(pr, row) == (224942.0, 235459.0)
