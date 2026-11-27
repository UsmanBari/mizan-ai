"""Download the PSX reports listed in data/psx_reports.csv into data/psx_pdfs/.

Get each link from https://dps.psx.com.pk/company/<SYMBOL> (Financial Results /
Financial Reports table -> right-click "PDF" -> copy link). If the url column says
AUTO, the latest annual report link is looked up automatically.
"""
from __future__ import annotations

import csv

import httpx

from common import DATA

from mizan.ingest.dedupe import sha256_file
from mizan.ingest.psx import UA, fetch_company_reports


def main() -> None:
    out = DATA / "psx_pdfs"
    out.mkdir(exist_ok=True)
    client = httpx.Client(headers=UA, timeout=120, follow_redirects=True)
    # de-duplication: the same PSX document id or the same PDF bytes is kept once
    seen_ids: dict[str, str] = {}
    seen_sha = {sha256_file(p): p.stem for p in sorted(out.glob("*.pdf"))}
    for r in csv.DictReader(open(DATA / "psx_reports.csv")):
        rid = r["url"].rstrip("/").split("/")[-1].split(".")[0].split("-")[0]
        if rid.isdigit() and rid in seen_ids:
            print(f"{r['symbol']}_{r['period']}: same PSX document as {seen_ids[rid]} - skipped"); continue
        if rid.isdigit():
            seen_ids[rid] = f"{r['symbol']}_{r['period']}"
        url = r["url"].strip()
        if url.upper() == "AUTO":
            links = [l for l in fetch_company_reports(r["symbol"], client) if l.doc_type == r["doc_type"]]
            if not links:
                print(f"{r['symbol']}: no {r['doc_type']} report found automatically"); continue
            url = links[0].url
        if not url.startswith("http"):
            print(f"{r['symbol']}: paste a PDF link into data/psx_reports.csv"); continue
        path = out / f"{r['symbol']}_{r['period']}.pdf"
        if path.exists():
            print(f"{path.name} already downloaded"); continue
        resp = client.get(url)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        sha = sha256_file(path)
        if sha in seen_sha:
            path.unlink()
            print(f"{path.name}: identical PDF to {seen_sha[sha]} (same filing posted twice) - not kept")
            continue
        seen_sha[sha] = path.stem
        import pymupdf
        with pymupdf.open(str(path)) as d:
            n = len(d)
        warn = "  <-- only a few pages: is this the real report or just a notice?" if n < 15 else ""
        print(f"downloaded {path.name} ({len(resp.content) / 1e6:.1f} MB, {n} pages)  doc_id = {path.stem}{warn}")


if __name__ == "__main__":
    main()
