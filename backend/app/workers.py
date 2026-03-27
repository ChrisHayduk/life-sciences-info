from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.config import get_settings
from app.jobs import (
    run_backfill_company,
    run_build_weekly_digest,
    run_ingest_news,
    run_poll_sec_filings,
    run_refresh_market_caps,
    run_resummarize_item,
    run_summarize_pending,
    run_sync_universe,
)

settings = get_settings()
redis_broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(redis_broker)


@dramatiq.actor
def sync_universe(limit: int | None = None) -> int:
    return run_sync_universe(limit=limit)


@dramatiq.actor
def backfill_company(company_id: int) -> int:
    return run_backfill_company(company_id)


@dramatiq.actor
def refresh_market_caps(count: int | None = None) -> dict[str, int | str | None]:
    return run_refresh_market_caps(count=count)


@dramatiq.actor
def poll_sec_filings() -> dict[str, int]:
    return run_poll_sec_filings()


@dramatiq.actor
def ingest_news() -> dict[str, int]:
    return run_ingest_news()


@dramatiq.actor
def summarize_pending(kind: str, limit: int | None = None) -> dict[str, int]:
    return run_summarize_pending(kind, limit=limit, automated=False)


@dramatiq.actor
def build_weekly_digest() -> int:
    return run_build_weekly_digest()


@dramatiq.actor
def resummarize_item(kind: str, item_id: int) -> int:
    return run_resummarize_item(kind, item_id)
