from __future__ import annotations

from datetime import datetime, timezone

from app.models import Company
from app.services.market_caps import MarketCapService


class FakeBatchMarketDataClient:
    def fetch_market_caps(self, tickers):
        assert tickers == ["ABIO", "BETA"]
        return {
            "ABIO": {
                "market_cap": 5_000_000_000,
                "source": "fmp_market_cap_batch",
                "as_of": datetime(2026, 3, 26, tzinfo=timezone.utc),
            }
        }


class FakeSingleMarketDataClient:
    def fetch_market_cap(self, ticker):
        assert ticker == "ABIO"
        return {
            "market_cap": 6_000_000_000,
            "source": "fmp_market_cap_single",
            "as_of": datetime(2026, 3, 26, tzinfo=timezone.utc),
        }


def test_refresh_market_caps_updates_only_successful_companies_and_preserves_existing_values(db_session, company):
    other = Company(
        cik="0000000456",
        ticker="BETA",
        name="Beta Bio",
        exchange="NASDAQ",
        sic="2836",
        sic_description="BIOLOGICAL PRODUCTS",
        market_cap=750_000_000,
        market_cap_source="cached",
        market_cap_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()

    result = MarketCapService(db_session, market_data_client=FakeBatchMarketDataClient()).refresh_market_caps([company, other])

    db_session.refresh(company)
    db_session.refresh(other)

    assert result["refreshed"] == 1
    assert result["failed"] == 1
    assert company.market_cap == 5_000_000_000
    assert company.market_cap_source == "fmp_market_cap_batch"
    assert other.market_cap == 750_000_000
    assert other.market_cap_source == "cached"


def test_refresh_company_market_cap_updates_one_company(db_session, company):
    service = MarketCapService(db_session, market_data_client=FakeSingleMarketDataClient())

    refreshed = service.refresh_company_market_cap(company)

    assert refreshed is True
    assert company.market_cap == 6_000_000_000
    assert company.market_cap_source == "fmp_market_cap_single"
