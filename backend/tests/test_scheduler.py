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
