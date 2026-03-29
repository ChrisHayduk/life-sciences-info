from __future__ import annotations

from starlette.requests import Request

from app.config import get_settings


def test_admin_routes_require_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret-token")
    get_settings.cache_clear()

    unauthorized = client.post("/api/v1/admin/build-weekly-digest")
    assert unauthorized.status_code == 401

    authorized = client.post("/api/v1/admin/build-weekly-digest", headers={"X-Admin-Token": "secret-token"})
    assert authorized.status_code == 200


def test_public_summarize_routes_do_not_require_admin_token(client, monkeypatch):
    class FakeFilingService:
        def __init__(self, session):
            self.session = session

        def summarize_item(self, item_id, *, consume_override_budget=False, force=False):
            assert item_id == 10
            assert consume_override_budget is True
            assert force is False
            return {"status": "summarized", "remaining_override_budget": 1}

    class FakeNewsService:
        def __init__(self, session):
            self.session = session

        def summarize_item(self, item_id, *, consume_override_budget=False, force=False):
            assert item_id == 20
            assert consume_override_budget is True
            assert force is False
            return {"status": "already_complete", "remaining_override_budget": 1}

    monkeypatch.setattr("app.api.routes.FilingService", FakeFilingService)
    monkeypatch.setattr("app.api.routes.NewsService", FakeNewsService)

    filing_response = client.post("/api/v1/filings/10/summarize")
    news_response = client.post("/api/v1/news/20/summarize")

    assert filing_response.status_code == 200
    assert news_response.status_code == 200


def test_public_summarize_route_returns_429_when_override_budget_is_exhausted(client, monkeypatch):
    class FakeFilingService:
        def __init__(self, session):
            self.session = session

        def summarize_item(self, item_id, *, consume_override_budget=False, force=False):
            raise RuntimeError("override_budget_exhausted")

    monkeypatch.setattr("app.api.routes.FilingService", FakeFilingService)

    response = client.post("/api/v1/filings/11/summarize")

    assert response.status_code == 429


def test_admin_poll_regulatory_events_route(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.run_poll_regulatory_events",
        lambda limit=None: {"inserted": 2, "updated": 1, "tagged": 2, "scanned": 3},
    )

    response = client.post("/api/v1/admin/poll-regulatory-events")

    assert response.status_code == 200
    assert "2 new and 1 updated FDA events" in response.json()["message"]


def test_admin_poll_trials_route_supports_focus_tickers(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.run_poll_trials",
        lambda limit=None, focus_tickers=None: {
            "provider": "aact_cloud",
            "companies_scanned": 2,
            "companies_succeeded": 2,
            "companies_failed": 0,
            "new_trials": 5,
            "updated_trials": 3,
            "pruned_trials": 1,
            "partial": 0,
            "skipped": 0,
        },
    )

    response = client.post("/api/v1/admin/poll-trials?limit=2&focus_tickers=MRK,PFE")

    assert response.status_code == 200
    assert "Provider aact_cloud" in response.json()["message"]
    assert "5 new trials" in response.json()["message"]


def test_events_stream_returns_cors_headers_for_frontend_origin(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://life-sciences-info.vercel.app")
    monkeypatch.setenv("CORS_ORIGINS", "")
    get_settings.cache_clear()

    from app.api.routes import _sse_cors_headers

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/events/stream",
            "headers": [(b"origin", b"https://life-sciences-info.vercel.app")],
        }
    )
    headers = _sse_cors_headers(request)

    assert headers["Access-Control-Allow-Origin"] == "https://life-sciences-info.vercel.app"
    assert headers["Access-Control-Allow-Credentials"] == "true"


def test_events_stream_returns_204_when_disabled(client):
    response = client.get("/api/v1/events/stream")

    assert response.status_code == 204


def test_dashboard_route_closes_request_scoped_services(client, monkeypatch):
    closed: list[str] = []

    class FakeFilingService:
        def __init__(self, session):
            self.session = session

        def list_filings(self, **kwargs):
            return []

        def pending_queue_counts(self):
            return {"filings_pending": 0, "filings_pending_full_ai": 0, "filings_pending_short_ai": 0}

        def close(self):
            closed.append("filing")

    class FakeNewsService:
        def __init__(self, session):
            self.session = session

        def list_news(self, **kwargs):
            return []

        def pending_queue_counts(self):
            return {"news_pending": 0, "news_pending_full_ai": 0, "news_pending_short_ai": 0}

        def close(self):
            closed.append("news")

    class FakeDigestService:
        def __init__(self, session):
            self.session = session

        def list_digests(self, limit=1):
            return []

        def close(self):
            closed.append("digest")

    class FakeClinicalTrialsService:
        def __init__(self, session):
            self.session = session

        def list_trials(self, **kwargs):
            return []

        def close(self):
            closed.append("trials")

    class FakeRegulatoryEventService:
        def __init__(self, session):
            self.session = session

        def list_timeline_events(self, **kwargs):
            return []

        def close(self):
            closed.append("regulatory")

    class FakeWatchlistService:
        def __init__(self, session):
            self.session = session

        def build_dashboard_highlights(self, **kwargs):
            return []

        def close(self):
            closed.append("watchlists")

    monkeypatch.setattr("app.api.routes.FilingService", FakeFilingService)
    monkeypatch.setattr("app.api.routes.NewsService", FakeNewsService)
    monkeypatch.setattr("app.api.routes.DigestService", FakeDigestService)
    monkeypatch.setattr("app.api.routes.ClinicalTrialsService", FakeClinicalTrialsService)
    monkeypatch.setattr("app.api.routes.RegulatoryEventService", FakeRegulatoryEventService)
    monkeypatch.setattr("app.api.routes.WatchlistService", FakeWatchlistService)

    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    assert set(closed) == {"filing", "news", "digest", "trials", "regulatory", "watchlists"}


def test_health_reports_event_listener_count(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert "event_listener_count" in response.json()
    assert "event_stream_enabled" in response.json()
    assert "rss_mb" in response.json()
    assert "thread_count" in response.json()
