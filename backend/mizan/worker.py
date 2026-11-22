"""Celery worker + beat schedule (background jobs).

Run:
  celery -A mizan.worker worker -l info
  celery -A mizan.worker beat   -l info
"""
from __future__ import annotations

from celery import Celery

from .config import get_settings

s = get_settings()
app = Celery("mizan", broker=s.redis_url, backend=s.redis_url)
app.conf.beat_schedule = {
    "poll-psx-watchlist": {"task": "mizan.worker.poll", "schedule": s.poll_minutes * 60.0},
}


@app.task(name="mizan.worker.poll")
def poll() -> int:
    from .alerts.watcher import poll_watchlist
    from .services import get_extractor, get_llm
    from .store import get_store
    return len(poll_watchlist(get_store(), get_extractor(), get_llm()))


@app.task(name="mizan.worker.ingest_symbol")
def ingest_symbol(symbol: str, limit: int = 4) -> list[str]:
    from .ingest.pipeline import ingest_psx_symbol
    from .store import get_store
    return [d.doc_id for d in ingest_psx_symbol(get_store(), symbol, limit=limit)]
