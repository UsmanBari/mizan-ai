"""PSX data portal client (deterministic code, no AI).

Company page:      https://dps.psx.com.pk/company/{SYMBOL}
Report PDFs:       https://dps.psx.com.pk/download/document/{id}.pdf
Announcement PDFs: https://dps.psx.com.pk/download/attachment/{id}.pdf

We parse the company page for the "Financial Results" announcements and the
"Financial Reports" table and return report links. The portal has no public API,
so parsing is defensive: if the layout changes, the PDF-link regex still works.
Please be polite: one request per company per poll, with a user agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from pathlib import Path

import httpx

from ..config import get_settings

UA = {"User-Agent": "MizanAI/0.1 (FAST-NUCES student research project)"}


@dataclass
class ReportLink:
    symbol: str
    title: str
    url: str
    date: str = ""
    doc_type: str = "other"
    period: str = ""

    @property
    def remote_id(self) -> str:
        m = re.search(r"/(\d+)(?:-\d+)?\.pdf", self.url)
        return m.group(1) if m else re.sub(r"\W+", "", self.url)[-12:]


def classify(title: str) -> tuple[str, str]:
    """Guess document type and period from an announcement title (rules, not AI)."""
    t = title.lower()
    if "annual" in t or "year ended" in t or "year end" in t:
        kind = "annual"
    elif "half" in t or "six month" in t:
        kind = "half-yearly"
    elif "quarter" in t or "nine month" in t or "three month" in t:
        kind = "quarterly"
    else:
        kind = "other"
    years = re.findall(r"20\d\d", title)
    period = f"{kind[:1].upper()}{years[-1]}" if years else ""
    return kind, period


def parse_company_page(html: str, symbol: str, base: str = "https://dps.psx.com.pk") -> list[ReportLink]:
    links: list[ReportLink] = []
    seen = set()
    # each table row: <tr> <td>date</td> <td>title</td> <td>... href=".pdf" ...</td> </tr>
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        hrefs = re.findall(r'href="([^"]+\.pdf)"', row, re.I)
        if not hrefs:
            continue
        cells = [re.sub(r"<[^>]+>", " ", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
        date = next((c for c in cells if re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", c)), "")
        title = max(cells, key=len) if cells else ""
        for h in hrefs:
            url = h if h.startswith("http") else base.rstrip("/") + "/" + h.lstrip("/")
            if url in seen:
                continue
            seen.add(url)
            kind, period = classify(title)
            links.append(ReportLink(symbol=symbol.upper(), title=title, url=url, date=date,
                                    doc_type=kind, period=period))
    return links


def is_financial(link: ReportLink) -> bool:
    t = link.title.lower()
    return any(w in t for w in ("financial result", "quarterly report", "annual report", "half year",
                                "accounts", "financial statement", "transmission of"))


def fetch_company_reports(symbol: str, client: httpx.Client | None = None) -> list[ReportLink]:
    s = get_settings()
    c = client or httpx.Client(headers=UA, timeout=30, follow_redirects=True)
    r = c.get(f"{s.psx_base_url}/company/{symbol.upper()}")
    r.raise_for_status()
    return [l for l in parse_company_page(r.text, symbol, s.psx_base_url) if is_financial(l)]


def download(link: ReportLink, dest_dir: Path, client: httpx.Client | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{link.symbol}_{link.remote_id}.pdf"
    if path.exists() and path.stat().st_size > 1000:
        return path
    c = client or httpx.Client(headers=UA, timeout=120, follow_redirects=True)
    with c.stream("GET", link.url) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path


def doc_id_for(link: ReportLink) -> str:
    return f"{link.symbol}_{link.period or 'X'}_{link.remote_id}"


def now() -> str:
    return _utcnow().isoformat(timespec="seconds")
