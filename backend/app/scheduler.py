from __future__ import annotations

import gc
import logging
import resource
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.jobs import (
    run_build_daily_digest,
    run_build_weekly_digest,
    run_ingest_news,
    run_poll_regulatory_events,
    run_poll_sec_filings,
    run_poll_trials,
    run_refresh_market_caps,
    run_sync_universe,
)

logger = logging.getLogger(__name__)


def _process_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(rss / (1024 * 1024), 2)
    return round(rss / 1024, 2)


def _logged_job(name: str, fn, **kwargs):
    rss_before = _process_rss_mb()
    started = time.perf_counter()
    logger.info("Scheduler job %s starting (rss_mb=%.2f)", name, rss_before)
    try:
        result = fn(**kwargs)
        rss_after = _process_rss_mb()
        logger.info(
            "Scheduler job %s completed in %.2fs (rss_mb=%.2f, delta_mb=%.2f)",
            name,
            time.perf_counter() - started,
            rss_after,
            rss_after - rss_before,
        )
        return result
    except Exception:
        rss_after = _process_rss_mb()
        logger.exception(
            "Scheduler job %s failed after %.2fs (rss_mb=%.2f, delta_mb=%.2f)",
            name,
            time.perf_counter() - started,
            rss_after,
            rss_after - rss_before,
        )
        raise
    finally:
        collected = gc.collect()
        if collected:
            logger.debug("GC after job %s collected %d objects", name, collected)


def build_scheduler(background: bool = False) -> BlockingScheduler | BackgroundScheduler:
    settings = get_settings()
    scheduler_class = BackgroundScheduler if background else BlockingScheduler
    scheduler = scheduler_class(
        timezone=settings.timezone,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(minute="5,35"),
        kwargs={"name": "poll_sec_filings", "fn": run_poll_sec_filings},
        id="poll_sec_filings",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(hour="1,7,13,19", minute=12),
        kwargs={"name": "ingest_news", "fn": run_ingest_news},
        id="ingest_news",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(hour="3,15", minute=18),
        kwargs={"name": "poll_regulatory_events", "fn": run_poll_regulatory_events},
        id="poll_regulatory_events",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(day_of_week="sun", hour=1, minute=5),
        kwargs={"name": "poll_trials", "fn": run_poll_trials, "limit": None},
        id="poll_trials",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(day_of_week="sun", hour=2, minute=5),
        kwargs={"name": "sync_universe", "fn": run_sync_universe},
        id="sync_universe",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(day_of_week="sun", hour=3, minute=5),
        kwargs={"name": "refresh_market_caps", "fn": run_refresh_market_caps, "count": None},
        id="refresh_market_caps",
        replace_existing=True,
    )
    scheduler.add_job(
        _logged_job,
        CronTrigger(day_of_week=settings.digest_weekday, hour=settings.digest_hour, minute=settings.digest_minute),
        kwargs={"name": "build_weekly_digest", "fn": run_build_weekly_digest},
        id="build_weekly_digest",
        replace_existing=True,
    )
    if getattr(settings, "enable_daily_digest", False):
        scheduler.add_job(
            _logged_job,
            CronTrigger(day_of_week="mon-fri", hour=getattr(settings, "daily_digest_hour", 7), minute=0),
            kwargs={"name": "build_daily_digest", "fn": run_build_daily_digest},
            id="build_daily_digest",
            replace_existing=True,
        )
    return scheduler


def main() -> None:
    scheduler = build_scheduler()
    scheduler.start()


if __name__ == "__main__":
    main()
