from __future__ import annotations

from types import SimpleNamespace

from app import scheduler as scheduler_module


def test_build_scheduler_includes_weekly_trial_poll(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(
            timezone="America/New_York",
            digest_weekday="mon",
            digest_hour=8,
            digest_minute=0,
        ),
    )

    scheduler = scheduler_module.build_scheduler(background=True)
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "poll_trials" in job_ids


def test_build_scheduler_can_include_daily_digest(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(
            timezone="America/New_York",
            digest_weekday="mon",
            digest_hour=8,
            digest_minute=0,
            enable_daily_digest=True,
            daily_digest_hour=7,
        ),
    )

    scheduler = scheduler_module.build_scheduler(background=True)
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "build_daily_digest" in job_ids


def test_build_scheduler_uses_non_overlapping_job_defaults(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(
            timezone="America/New_York",
            digest_weekday="mon",
            digest_hour=8,
            digest_minute=0,
        ),
    )

    scheduler = scheduler_module.build_scheduler(background=True)

    assert scheduler._job_defaults["coalesce"] is True
    assert scheduler._job_defaults["max_instances"] == 1
    assert scheduler._job_defaults["misfire_grace_time"] == 3600

    for job in scheduler.get_jobs():
        assert getattr(job, "max_instances", scheduler._job_defaults["max_instances"]) == 1
        assert getattr(job, "coalesce", scheduler._job_defaults["coalesce"]) is True
        assert getattr(job, "misfire_grace_time", scheduler._job_defaults["misfire_grace_time"]) == 3600
