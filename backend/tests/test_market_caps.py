from __future__ import annotations

from datetime import datetime, timezone

from app.models import Company, Filing, NewsItem
from app.services.filings import FilingService
from app.services.market_caps import MarketCapService
from app.services.news import NewsService


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


def test_rerank_after_market_cap_refresh_updates_existing_filing_and_news_scores(db_session, company):
    company.market_cap = None
    company.market_cap_source = None
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
    filing = Filing(
        company_id=company.id,
        accession_number="0001",
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Apex Bio Q1",
        filed_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
        filing_url="https://example.com/index",
        original_document_url="https://example.com/doc",
        raw_text="FDA approval and guidance increase lifted revenue 25%.",
        summary_status="pending",
        market_cap_score=0.0,
        importance_score=0.0,
        impact_score=0.0,
        composite_score=0.0,
    )
    news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Apex Bio expands plant",
        canonical_url="https://example.com/story",
        excerpt="Expansion announced",
        content_text="Expansion announced",
        published_at=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        article_hash="hash-1",
        mentioned_companies=["Apex Bio", "ABIO"],
        topic_tags=["manufacturing"],
        summary_status="pending",
        market_cap_score=0.0,
        importance_score=0.0,
        composite_score=0.0,
    )
    db_session.add_all([other, filing, news])
    db_session.commit()

    company.market_cap = 5_000_000_000
    company.market_cap_source = "fmp_market_cap_batch"
    company.market_cap_updated_at = datetime(2026, 3, 26, tzinfo=timezone.utc)

    reranked_filings = FilingService(db_session).rerank_for_companies([company.id])
    reranked_news = NewsService(db_session).rerank_for_companies([company.id])

    db_session.refresh(filing)
    db_session.refresh(news)

    assert reranked_filings == 1
    assert reranked_news == 1
    assert filing.market_cap_score == 100.0
    assert filing.composite_score > 0.0
    assert news.market_cap_score == 100.0
    assert news.composite_score > 0.0
