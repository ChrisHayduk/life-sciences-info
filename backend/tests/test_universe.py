from __future__ import annotations

from app.models import Company
from app.services.universe import UniverseService, is_core_life_sciences


class FakeSECClient:
    def get_company_tickers(self):
        return [
            {"cik": "123", "ticker": "ABIO", "name": "Apex Bio", "exchange": "NASDAQ"},
            {"cik": "124", "ticker": "TOOLS", "name": "Tools Co", "exchange": "NASDAQ"},
            {"cik": "125", "ticker": "MANU", "name": "Manual Include", "exchange": "NYSE"},
        ]

    def get_company_submissions(self, cik: str):
        payloads = {
            "0000000123": {"sic": "2836", "sicDescription": "BIOLOGICAL PRODUCTS", "name": "Apex Bio"},
            "0000000124": {"sic": "7372", "sicDescription": "SOFTWARE", "name": "Tools Co"},
            "0000000125": {"sic": "7372", "sicDescription": "SOFTWARE", "name": "Manual Include"},
        }
        return payloads[cik]


class FakeMarketDataClient:
    def fetch_market_cap(self, ticker):
        return {"market_cap": 2_000_000_000, "source": "test", "as_of": None}


def test_is_core_life_sciences_and_overrides():
    assert is_core_life_sciences("2834") is True
    assert is_core_life_sciences("7372") is False
    assert is_core_life_sciences("7372", allowlisted=True) is True
    assert is_core_life_sciences("2834", denylisted=True) is False


def test_sync_universe_filters_by_sic_and_honors_overrides(db_session):
    service = UniverseService(
        db_session,
        sec_client=FakeSECClient(),
        market_data_client=FakeMarketDataClient(),
        allowlist={"MANU"},
        denylist={"TOOLS"},
    )

    count = service.sync_universe()

    companies = db_session.query(Company).order_by(Company.ticker).all()
    tickers = [company.ticker for company in companies]
    assert count == 2
    assert tickers == ["ABIO", "MANU"]
    assert companies[1].universe_reason == "manual-allowlist"


def test_sync_universe_reports_progress_when_callback_is_provided(db_session):
    messages = []
    service = UniverseService(
        db_session,
        sec_client=FakeSECClient(),
        market_data_client=FakeMarketDataClient(),
        allowlist={"MANU"},
        denylist={"TOOLS"},
    )

    count = service.sync_universe(progress_callback=messages.append, progress_every=1)

    assert count == 2
    assert messages[0] == "Universe sync starting: scanning 3 SEC issuers"
    assert any("scanned 1/3 issuers" in message for message in messages)
    assert any("scanned 2/3 issuers" in message for message in messages)
    assert any("scanned 3/3 issuers" in message for message in messages)
    assert messages[-1] == "Universe sync complete: matched 2 covered companies, market caps refreshed 2, failed 0"
