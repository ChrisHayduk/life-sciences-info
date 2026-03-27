from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings


class MarketCapResult(dict):
    market_cap: int | None
    source: str
    as_of: datetime


class MarketDataClient:
    FMP_BATCH_SIZE = 100

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.http_client = http_client or httpx.Client(timeout=self.settings.source_fetch_timeout_seconds)

    def fetch_market_cap(self, ticker: str | None) -> dict:
        normalized = self._normalize_ticker(ticker)
        if not normalized:
            raise RuntimeError("Ticker is required for market cap refresh")

        provider = self.settings.market_data_provider
        if provider == "none":
            raise RuntimeError("Market data provider disabled")
        if provider == "alpha_vantage":
            return self._fetch_market_cap_alpha_vantage(normalized)
        return self._fetch_market_cap_fmp_single(normalized)

    def fetch_market_caps(self, tickers: list[str | None]) -> dict[str, dict]:
        normalized = []
        seen: set[str] = set()
        for ticker in tickers:
            symbol = self._normalize_ticker(ticker)
            if symbol and symbol not in seen:
                seen.add(symbol)
                normalized.append(symbol)

        if not normalized:
            return {}

        provider = self.settings.market_data_provider
        if provider == "none":
            raise RuntimeError("Market data provider disabled")
        if provider == "alpha_vantage":
            return {ticker: self._fetch_market_cap_alpha_vantage(ticker) for ticker in normalized}
        return self._fetch_market_caps_fmp(normalized)

    def _fetch_market_caps_fmp(self, tickers: list[str]) -> dict[str, dict]:
        self._require_fmp_api_key()
        results: dict[str, dict] = {}
        as_of = datetime.now(timezone.utc)

        for start in range(0, len(tickers), self.FMP_BATCH_SIZE):
            batch = tickers[start : start + self.FMP_BATCH_SIZE]
            response = self.http_client.get(
                f"{self.settings.fmp_base_url}/market-capitalization-batch",
                params={
                    "symbols": ",".join(batch),
                    "apikey": self.settings.fmp_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._raise_for_provider_error(payload, provider="fmp", ticker=",".join(batch))

            batch_results = self._parse_fmp_market_caps(payload, source="fmp_market_cap_batch", as_of=as_of)
            results.update(batch_results)

            for ticker in batch:
                if ticker in results:
                    continue
                try:
                    results[ticker] = self._fetch_market_cap_fmp_single(ticker)
                except Exception:
                    continue

        return results

    def _fetch_market_cap_fmp_single(self, ticker: str) -> dict:
        self._require_fmp_api_key()
        response = self.http_client.get(
            f"{self.settings.fmp_base_url}/market-capitalization",
            params={
                "symbol": ticker,
                "apikey": self.settings.fmp_api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_for_provider_error(payload, provider="fmp", ticker=ticker)

        parsed = self._parse_fmp_market_caps(payload, source="fmp_market_cap_single")
        result = parsed.get(ticker)
        if result:
            return result
        raise RuntimeError(f"No market cap returned for {ticker}")

    def _fetch_market_cap_alpha_vantage(self, ticker: str) -> dict:
        if not self.settings.alpha_vantage_api_key:
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
        self._raise_for_provider_error(payload, provider="alpha_vantage", ticker=ticker)
        market_cap = self._coerce_market_cap(payload.get("MarketCapitalization"))
        if market_cap is None:
            raise RuntimeError(f"No market cap returned for {ticker}")
        return {
            "market_cap": market_cap,
            "source": "alpha_vantage_overview",
            "as_of": datetime.now(timezone.utc),
        }

    def _parse_fmp_market_caps(
        self,
        payload: Any,
        *,
        source: str,
        as_of: datetime | None = None,
    ) -> dict[str, dict]:
        rows = self._normalize_fmp_rows(payload)
        if not rows:
            return {}

        now = as_of or datetime.now(timezone.utc)
        results: dict[str, dict] = {}
        for row in rows:
            ticker = self._normalize_ticker(row.get("symbol") or row.get("ticker"))
            market_cap = self._coerce_market_cap(
                row.get("marketCap")
                or row.get("market_cap")
                or row.get("marketCapitalization")
                or row.get("market_capitalization")
            )
            if not ticker or market_cap is None:
                continue
            results[ticker] = {
                "market_cap": market_cap,
                "source": source,
                "as_of": now,
            }
        return results

    @staticmethod
    def _normalize_fmp_rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                return [row for row in payload["data"] if isinstance(row, dict)]
            return [payload]
        return []

    @staticmethod
    def _normalize_ticker(ticker: str | None) -> str | None:
        if not ticker:
            return None
        normalized = str(ticker).strip().upper()
        return normalized or None

    @staticmethod
    def _coerce_market_cap(value: Any) -> int | None:
        if value in {None, "", 0, "0"}:
            return None
        if isinstance(value, bool):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _require_fmp_api_key(self) -> None:
        if not self.settings.fmp_api_key:
            raise RuntimeError("FMP credentials not configured")

    @staticmethod
    def _raise_for_provider_error(payload: Any, *, provider: str, ticker: str) -> None:
        if provider == "alpha_vantage":
            if isinstance(payload, dict):
                if payload.get("Error Message"):
                    raise RuntimeError(f"Alpha Vantage rejected {ticker}: {payload['Error Message']}")
                if payload.get("Information"):
                    raise RuntimeError(f"Alpha Vantage info for {ticker}: {payload['Information']}")
                if payload.get("Note"):
                    raise RuntimeError(f"Alpha Vantage rate limit for {ticker}: {payload['Note']}")
            return

        if isinstance(payload, dict):
            error_message = payload.get("Error Message") or payload.get("error") or payload.get("Error")
            if error_message:
                raise RuntimeError(f"FMP rejected {ticker}: {error_message}")
            message = payload.get("message") or payload.get("Message")
            if isinstance(message, str) and any(word in message.lower() for word in ("limit", "credits", "plan", "api key")):
                raise RuntimeError(f"FMP info for {ticker}: {message}")
