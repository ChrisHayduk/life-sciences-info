from __future__ import annotations

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
