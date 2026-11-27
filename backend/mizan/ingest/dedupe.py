"""Never ingest the same filing twice (deterministic, no AI).

Two keys, both checked:
  * the PSX document id (".../download/document/282262.pdf" -> "282262"),
    checked BEFORE downloading, so a known filing is not fetched again;
  * the sha256 of the PDF bytes, checked after downloading, because PSX often
    posts the same PDF twice (e.g. under "Financial Results" and again under
    "Transmission of Annual Report"), with different ids.

The ledger is a small JSON file in the data directory, so it survives a backend
restart (the in-memory store does not).
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class Ledger:
    """{"by_remote_id": {id: doc_id}, "by_sha256": {sha: doc_id}}"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.by_remote_id: dict[str, str] = {}
        self.by_sha256: dict[str, str] = {}
        if self.path and self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                self.by_remote_id = dict(d.get("by_remote_id", {}))
                self.by_sha256 = dict(d.get("by_sha256", {}))
            except (OSError, ValueError):
                pass   # a broken ledger must not stop ingestion; it is rebuilt as we go

    def seen_remote(self, remote_id: str) -> str | None:
        return self.by_remote_id.get(remote_id) if remote_id else None

    def seen_sha(self, sha: str) -> str | None:
        return self.by_sha256.get(sha) if sha else None

    def record(self, doc_id: str, sha: str = "", remote_id: str = "") -> None:
        with self._lock:
            if sha:
                self.by_sha256.setdefault(sha, doc_id)
            if remote_id:
                self.by_remote_id.setdefault(remote_id, doc_id)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"by_remote_id": self.by_remote_id,
                                           "by_sha256": self.by_sha256}, indent=1))
                tmp.replace(self.path)
