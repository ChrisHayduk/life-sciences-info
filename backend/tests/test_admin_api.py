from __future__ import annotations

from app.config import get_settings


def test_admin_routes_require_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret-token")
    get_settings.cache_clear()

    unauthorized = client.post("/api/v1/admin/build-weekly-digest")
    assert unauthorized.status_code == 401

    authorized = client.post("/api/v1/admin/build-weekly-digest", headers={"X-Admin-Token": "secret-token"})
    assert authorized.status_code == 200
