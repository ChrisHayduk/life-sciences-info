from __future__ import annotations

import httpx
import pytest

from app.services.market_data import MarketDataClient


def test_fetch_market_cap_reports_alpha_vantage_rate_limit(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."},
        )
    )
    client = MarketDataClient(http_client=httpx.Client(transport=transport))
    monkeypatch.setattr(client.settings, "alpha_vantage_api_key", "test-key")

    with pytest.raises(RuntimeError, match="Alpha Vantage rate limit"):
        client.fetch_market_cap("LLY")


def test_fetch_market_cap_reports_provider_errors(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"Error Message": "Invalid API call."},
        )
    )
    client = MarketDataClient(http_client=httpx.Client(transport=transport))
    monkeypatch.setattr(client.settings, "alpha_vantage_api_key", "test-key")

    with pytest.raises(RuntimeError, match="Alpha Vantage rejected LLY"):
        client.fetch_market_cap("LLY")
