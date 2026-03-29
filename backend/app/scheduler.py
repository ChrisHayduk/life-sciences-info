from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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


def build_scheduler(background: bool = False) -> BlockingScheduler | BackgroundScheduler:
    settings = get_settings()
    scheduler_class = BackgroundScheduler if background else BlockingScheduler
    scheduler = scheduler_class(timezone=settings.timezone)
    scheduler.add_job(run_poll_sec_filings, IntervalTrigger(minutes=30), id="poll_sec_filings", replace_existing=True)
    scheduler.add_job(run_ingest_news, IntervalTrigger(hours=6), id="ingest_news", replace_existing=True)
    scheduler.add_job(run_poll_regulatory_events, IntervalTrigger(hours=12), id="poll_regulatory_events", replace_existing=True)
    scheduler.add_job(
        run_poll_trials,
        IntervalTrigger(days=7),
        kwargs={"limit": None},
        id="poll_trials",
        replace_existing=True,
    )
    scheduler.add_job(run_sync_universe, IntervalTrigger(days=7), id="sync_universe", replace_existing=True)
    scheduler.add_job(
        run_refresh_market_caps,
        IntervalTrigger(days=7),
        kwargs={"count": None},
        id="refresh_market_caps",
        replace_existing=True,
    )
    scheduler.add_job(
        run_build_weekly_digest,
        CronTrigger(day_of_week=settings.digest_weekday, hour=settings.digest_hour, minute=settings.digest_minute),
        id="build_weekly_digest",
        replace_existing=True,
    )
    if getattr(settings, "enable_daily_digest", False):
        scheduler.add_job(
            run_build_daily_digest,
            CronTrigger(day_of_week="mon-fri", hour=getattr(settings, "daily_digest_hour", 7), minute=0),
            id="build_daily_digest",
            replace_existing=True,
        )
    return scheduler


def main() -> None:
    scheduler = build_scheduler()
    scheduler.start()


if __name__ == "__main__":
    main()
