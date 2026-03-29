from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable

from sqlalchemy.orm import Session

from app.models import Company
from app.services.market_data import MarketDataClient


class MarketCapService:
    def __init__(self, session: Session, market_data_client: MarketDataClient | None = None) -> None:
        self.session = session
        self._owns_market_data_client = market_data_client is None
        self.market_data_client = market_data_client or MarketDataClient()

    def close(self) -> None:
        if self._owns_market_data_client:
            with contextlib.suppress(Exception):
                self.market_data_client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def refresh_company_market_cap(self, company: Company) -> bool:
        try:
            market = self.market_data_client.fetch_market_cap(company.ticker)
        except Exception:
            return False
        self._apply_market_cap(company, market)
        return True

    def refresh_market_caps(
        self,
        companies: Iterable[Company],
        *,
        progress_callback: Callable[[str], None] | None = None,
        progress_every: int = 100,
    ) -> dict[str, int | str | None]:
        target_companies = [company for company in companies if company.ticker]
        total = len(target_companies)
        refreshed = 0
        failed = 0
        last_error: str | None = None
        refreshed_company_ids: list[int] = []

        if progress_callback:
            progress_callback(f"Market cap refresh starting: {total} companies")

        provider = getattr(getattr(self.market_data_client, "settings", None), "market_data_provider", "fmp")
        batch_size = getattr(self.market_data_client, "FMP_BATCH_SIZE", 100) if provider == "fmp" else 1
        for start in range(0, total, batch_size):
            batch = target_companies[start : start + batch_size]
            tickers = [company.ticker for company in batch]

            try:
                market_caps = self.market_data_client.fetch_market_caps(tickers)
            except Exception as exc:
                market_caps = {}
                last_error = str(exc)

            for company in batch:
                result = market_caps.get((company.ticker or "").upper())
                if result is None:
                    failed += 1
                    if last_error is None:
                        last_error = f"No market cap returned for {company.ticker}"
                    continue
                self._apply_market_cap(company, result)
                refreshed += 1
                refreshed_company_ids.append(company.id)

            processed = min(start + len(batch), total)
            if progress_callback and (processed == total or processed % progress_every == 0):
                progress_callback(
                    f"Market cap refresh progress: processed {processed}/{total} companies, "
                    f"refreshed {refreshed}, failed {failed}"
                )

        self.session.commit()

        if progress_callback:
            suffix = f"Market cap refresh complete: refreshed {refreshed}, failed {failed}"
            if last_error:
                suffix += f" (last error: {last_error})"
            progress_callback(suffix)

        return {
            "companies": total,
            "refreshed": refreshed,
            "failed": failed,
            "last_error": last_error,
            "refreshed_company_ids": refreshed_company_ids,
        }

    @staticmethod
    def _apply_market_cap(company: Company, market: dict) -> None:
        company.market_cap = market["market_cap"]
        company.market_cap_source = market["source"]
        company.market_cap_updated_at = market["as_of"]
