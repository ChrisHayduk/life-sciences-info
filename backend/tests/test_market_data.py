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
    monkeypatch.setattr(client.settings, "market_data_provider", "alpha_vantage")
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
    monkeypatch.setattr(client.settings, "market_data_provider", "alpha_vantage")
    monkeypatch.setattr(client.settings, "alpha_vantage_api_key", "test-key")

    with pytest.raises(RuntimeError, match="Alpha Vantage rejected LLY"):
        client.fetch_market_cap("LLY")


def test_fetch_market_caps_uses_fmp_batch_endpoint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/market-capitalization-batch")
        assert request.url.params["symbols"] == "LLY,JNJ"
        return httpx.Response(
            200,
            json=[
                {"symbol": "LLY", "marketCap": "900000000000"},
                {"symbol": "JNJ", "marketCap": 380000000000},
            ],
        )

    client = MarketDataClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(client.settings, "market_data_provider", "fmp")
    monkeypatch.setattr(client.settings, "fmp_api_key", "test-key")

    results = client.fetch_market_caps(["LLY", "JNJ"])

    assert results["LLY"]["market_cap"] == 900_000_000_000
    assert results["LLY"]["source"] == "fmp_market_cap_batch"
    assert results["JNJ"]["market_cap"] == 380_000_000_000


def test_fetch_market_caps_falls_back_to_single_company_when_batch_misses_ticker(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/market-capitalization-batch"):
            return httpx.Response(200, json=[{"symbol": "LLY", "marketCap": "900000000000"}])
        assert request.url.path.endswith("/market-capitalization")
        assert request.url.params["symbol"] == "JNJ"
        return httpx.Response(200, json=[{"symbol": "JNJ", "marketCap": "380000000000"}])

    client = MarketDataClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(client.settings, "market_data_provider", "fmp")
    monkeypatch.setattr(client.settings, "fmp_api_key", "test-key")

    results = client.fetch_market_caps(["LLY", "JNJ"])

    assert results["LLY"]["source"] == "fmp_market_cap_batch"
    assert results["JNJ"]["source"] == "fmp_market_cap_single"
    assert calls.count("/stable/market-capitalization-batch") == 1
    assert calls.count("/stable/market-capitalization") == 1


def test_fetch_market_cap_reports_fmp_provider_errors(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"Error": "Invalid API key"}))
    client = MarketDataClient(http_client=httpx.Client(transport=transport))
    monkeypatch.setattr(client.settings, "market_data_provider", "fmp")
    monkeypatch.setattr(client.settings, "fmp_api_key", "test-key")

    with pytest.raises(RuntimeError, match="FMP rejected LLY"):
        client.fetch_market_cap("LLY")
