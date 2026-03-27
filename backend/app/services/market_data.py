from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.config import get_settings


class MarketCapResult(dict):
    market_cap: int | None
    source: str
    as_of: datetime


class MarketDataClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.http_client = http_client or httpx.Client(timeout=self.settings.source_fetch_timeout_seconds)

    def fetch_market_cap(self, ticker: str | None) -> dict:
        if not ticker or not self.settings.alpha_vantage_api_key:
            raise RuntimeError("Alpha Vantage credentials not configured")

        response = self.http_client.get(
            self.settings.alpha_vantage_base_url,
            params={
                "function": "OVERVIEW",
                "symbol": ticker,
                "apikey": self.settings.alpha_vantage_api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("Error Message"):
            raise RuntimeError(f"Alpha Vantage rejected {ticker}: {payload['Error Message']}")
        if payload.get("Information"):
            raise RuntimeError(f"Alpha Vantage info for {ticker}: {payload['Information']}")
        if payload.get("Note"):
            raise RuntimeError(f"Alpha Vantage rate limit for {ticker}: {payload['Note']}")
        market_cap = payload.get("MarketCapitalization")
        if not market_cap:
            raise RuntimeError(f"No market cap returned for {ticker}")
        return {
            "market_cap": int(market_cap),
            "source": "alpha_vantage_overview",
            "as_of": datetime.now(timezone.utc),
        }
