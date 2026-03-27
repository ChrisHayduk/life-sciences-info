from __future__ import annotations

from types import SimpleNamespace

from app import jobs


def test_run_refresh_market_caps_targets_top_companies(db_session, company, monkeypatch):
    other = SimpleNamespace(
        id=99,
        cik="0000000999",
        ticker="ZZZZ",
        name="Zeta Bio",
        market_cap=9_000_000_000,
        is_active=True,
    )
    company.market_cap = 2_000_000_000

    class FakeMarketCapService:
        captured = []

        def __init__(self, session):
            self.session = session

        def refresh_market_caps(self, companies, *, progress_callback=None, progress_every=100):
            FakeMarketCapService.captured = [item.ticker for item in companies]
            return {"companies": len(FakeMarketCapService.captured), "refreshed": len(FakeMarketCapService.captured), "failed": 0, "last_error": None}

    monkeypatch.setattr("app.jobs.init_db", lambda: None)
    monkeypatch.setattr("app.jobs.SessionLocal", lambda: db_session)
    monkeypatch.setattr(jobs, "_load_active_companies", lambda session, focus_tickers=None: [other, company])
    monkeypatch.setattr("app.jobs.MarketCapService", FakeMarketCapService)

    result = jobs.run_refresh_market_caps(count=1)

    assert FakeMarketCapService.captured == ["ZZZZ"]
    assert result["refreshed"] == 1


def test_run_refresh_all_data_refreshes_market_caps_before_selecting_companies(monkeypatch):
    events: list[str] = []

    company = SimpleNamespace(id=1, name="Apex Bio", ticker="ABIO", cik="0000000123")

    class FakeUniverseService:
        def __init__(self, session, only_tickers=None):
            self.session = session

        def sync_universe(self, limit=None, progress_callback=None, progress_every=100):
            events.append("sync")
            return 1

    class FakeFilingService:
        def __init__(self, session):
            self.session = session

        def reprocess_company_filings(self, company_id):
            events.append(f"reprocess:{company_id}")
            return 2

        def backfill_company(self, company_id, max_filings=None, years_back=None):
            events.append(f"backfill:{company_id}")
            return 3

    monkeypatch.setattr(jobs, "UniverseService", FakeUniverseService)
    monkeypatch.setattr(jobs, "FilingService", FakeFilingService)
    monkeypatch.setattr(jobs, "run_refresh_market_caps", lambda **kwargs: events.append("refresh_caps") or {"companies": 1, "refreshed": 1, "failed": 0, "last_error": None})
    monkeypatch.setattr(jobs, "_load_active_companies", lambda session, focus_tickers=None: [company])
    monkeypatch.setattr(jobs, "_with_session", lambda callback: callback(object()))

    result = jobs.run_refresh_all_data(include_news=False, build_digest=False, company_count=1)

    assert events[:4] == ["sync", "refresh_caps", "reprocess:1", "backfill:1"]
    assert result["refreshed_market_caps"] == 1
    assert result["failed_market_caps"] == 0
