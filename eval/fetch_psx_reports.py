"""Download the PSX reports listed in data/psx_reports.csv into data/psx_pdfs/.

Get each link from https://dps.psx.com.pk/company/<SYMBOL> (Financial Results /
Financial Reports table -> right-click "PDF" -> copy link). If the url column says
AUTO, the latest annual report link is looked up automatically.
"""
from __future__ import annotations

import csv

import httpx

from common import DATA

from mizan.ingest.psx import UA, fetch_company_reports


def main() -> None:
    out = DATA / "psx_pdfs"
    out.mkdir(exist_ok=True)
    client = httpx.Client(headers=UA, timeout=120, follow_redirects=True)
    for r in csv.DictReader(open(DATA / "psx_reports.csv")):
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
        print(f"downloaded {path.name} ({len(resp.content) / 1e6:.1f} MB)  doc_id = {path.stem}")


if __name__ == "__main__":
    main()
