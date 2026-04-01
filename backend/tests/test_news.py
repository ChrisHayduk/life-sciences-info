from __future__ import annotations

import feedparser
import httpx

from app.models import Company, NewsItem
from app.services.constants import COMPANY_IR_SOURCES
from app.services.news import NewsService


class StubSummarizer:
    def summarize(self, **kwargs):
        from app.schemas import SummaryPayload

        return SummaryPayload(
            summary=f"Summary for {kwargs['title']}",
            key_takeaways=["Takeaway 1"],
            material_changes=["Material change"],
            risk_flags=[],
            opportunity_flags=[],
            company_mentions=[kwargs.get("company_name")] if kwargs.get("company_name") else [],
            evidence_sections=kwargs.get("evidence_sections") or [],
            importance_score=82.0,
            market_cap_score=0.0,
            composite_score=82.0,
            score_explanation="Stub summary",
        )


def test_news_ingestion_dedupes_and_tags_company_mentions(db_session, company, monkeypatch):
    entries = [
        feedparser.FeedParserDict(
            title="Apex Bio raises guidance after FDA clearance",
            link="https://news.example.com/story?utm=test",
            summary="<p>Apex Bio reported strong demand.</p>",
            published="Mon, 24 Mar 2026 10:00:00 GMT",
        ),
        feedparser.FeedParserDict(
            title="Sponsored webinar: commercial strategy",
            link="https://news.example.com/sponsored",
            summary="<p>Skip me</p>",
            published="Mon, 24 Mar 2026 12:00:00 GMT",
        ),
    ]

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=entries))

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><article><p>Apex Bio won FDA clearance and raised guidance.</p></article></html>")
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    first_count = service.ingest_feeds()
    second_count = service.ingest_feeds()

    items = db_session.query(NewsItem).all()
    assert first_count == 1
    assert second_count == 0
    assert len(items) == 1
    assert any("Apex Bio" in item.mentioned_companies or "ABIO" in item.mentioned_companies for item in items)
    assert items[0].company_tag_ids == [company.id]
    assert all("Sponsored" not in item.title for item in items)
    assert items[0].summary_status == "pending"


def test_news_titles_strip_html_on_ingest_and_response(db_session, company, monkeypatch):
    entries = [
        feedparser.FeedParserDict(
            title='<a href="https://news.example.com/story" hreflang="en">Wave crashes after obesity trial</a>',
            link="https://news.example.com/story",
            summary="<p>Wave Life Sciences reported new obesity data.</p>",
            published="Wed, 26 Mar 2026 09:21:00 GMT",
        ),
    ]

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=entries))

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><article><p>Wave Life Sciences reported new obesity data.</p></article></html>")
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    inserted = service.ingest_feeds()
    item = db_session.query(NewsItem).one()
    response_item = service.list_news(limit=1)[0]

    assert inserted == 1
    assert item.title == "Wave crashes after obesity trial"
    assert response_item.title == "Wave crashes after obesity trial"


def test_news_summarize_pending_respects_limit(db_session, company, monkeypatch):
    monkeypatch.setenv("NEWS_SUMMARY_BACKLOG_DAYS", "30")
    entries = [
        feedparser.FeedParserDict(
            title="Apex Bio raises guidance after FDA clearance",
            link="https://news.example.com/story-1",
            summary="<p>Apex Bio reported strong demand.</p>",
            published="Mon, 24 Mar 2026 10:00:00 GMT",
        ),
        feedparser.FeedParserDict(
            title="Apex Bio expands manufacturing footprint",
            link="https://news.example.com/story-2",
            summary="<p>Manufacturing capacity expanded.</p>",
            published="Mon, 24 Mar 2026 11:00:00 GMT",
        ),
    ]

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=entries))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><article><p>Apex Bio won FDA clearance and expanded manufacturing.</p></article></html>")
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    inserted = service.ingest_feeds()
    result = service.summarize_pending(limit=1, automated=True)

    complete_count = db_session.query(NewsItem).filter(NewsItem.summary_status == "complete").count()
    assert inserted == 2
    assert result["summarized"] == 1
    assert complete_count == 1


def test_news_ingestion_tags_multiple_companies_once_each(db_session, company, monkeypatch):
    other = Company(
        cik="0000000456",
        ticker="BETA",
        name="Beta Bio",
        exchange="NASDAQ",
        sic="2836",
        sic_description="BIOLOGICAL PRODUCTS",
        market_cap=900_000_000,
        market_cap_source="test",
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()

    entries = [
        feedparser.FeedParserDict(
            title="Apex Bio and Beta Bio sign manufacturing deal",
            link="https://news.example.com/story-3",
            summary="<p>Apex Bio and Beta Bio announced a deal.</p>",
            published="Mon, 24 Mar 2026 10:00:00 GMT",
        ),
    ]

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=entries))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html><article><p>Apex Bio and Beta Bio announced a manufacturing deal.</p></article></html>",
        )
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    inserted = service.ingest_feeds()
    item = db_session.query(NewsItem).one()

    assert inserted == 1
    assert item.company_tag_ids == [company.id, other.id]
    assert "Apex Bio" in item.mentioned_companies
    assert "Beta Bio" in item.mentioned_companies


def test_news_detection_avoids_partial_alias_false_positives(db_session, monkeypatch):
    company = Company(
        cik="0000000789",
        ticker="AB",
        name="Alpha Bio",
        exchange="NASDAQ",
        sic="2836",
        sic_description="BIOLOGICAL PRODUCTS",
        market_cap=700_000_000,
        market_cap_source="test",
        is_active=True,
    )
    db_session.add(company)
    db_session.commit()

    entries = [
        feedparser.FeedParserDict(
            title="Abstract manufacturing outlook improves",
            link="https://news.example.com/story-4",
            summary="<p>The abstract review was positive.</p>",
            published="Mon, 24 Mar 2026 10:00:00 GMT",
        ),
    ]

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=entries))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html><article><p>The abstract review was positive for the sector.</p></article></html>",
        )
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    inserted = service.ingest_feeds()
    item = db_session.query(NewsItem).one()

    assert inserted == 1
    assert item.company_tag_ids == []
    assert item.mentioned_companies == []


def test_retag_company_news_backfills_existing_archive_and_is_idempotent(db_session, company):
    company.market_cap = 4_500_000_000
    company.market_cap_source = "test"
    item = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Apex Bio raises guidance",
        canonical_url="https://example.com/story-retag",
        excerpt="Guidance raised",
        content_text="Apex Bio raised guidance after FDA clearance.",
        published_at=company.market_cap_updated_at,
        article_hash="hash-retag",
        mentioned_companies=[],
        company_tag_ids=[],
        topic_tags=["finance"],
        summary_status="pending",
        market_cap_score=0.0,
        importance_score=0.0,
        composite_score=0.0,
    )
    db_session.add(item)
    db_session.commit()

    service = NewsService(db_session)
    first = service.retag_company_news()
    db_session.refresh(item)
    second = service.retag_company_news()
    db_session.refresh(item)

    assert first["scanned"] == 1
    assert first["updated"] == 1
    assert first["reranked"] == 1
    assert item.company_tag_ids == [company.id]
    assert item.market_cap_score == 100.0
    assert "Apex Bio" in item.mentioned_companies
    assert second["updated"] == 0


def test_news_ingestion_includes_prioritized_company_ir_feeds(db_session, company, monkeypatch):
    company.extra_metadata = {"ir_feed_url": "https://ir.example.com/rss"}
    db_session.commit()

    def fake_parse(url: str):
        if url == "https://ir.example.com/rss":
            return feedparser.FeedParserDict(
                entries=[
                    feedparser.FeedParserDict(
                        title="Apex Bio announces Phase 3 data",
                        link="https://ir.example.com/news/phase-3-data",
                        summary="<p>Official company press release.</p>",
                        published="Thu, 26 Mar 2026 09:21:00 GMT",
                    )
                ]
            )
        return feedparser.FeedParserDict(entries=[])

    monkeypatch.setattr(feedparser, "parse", fake_parse)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html><article><p>Apex Bio announced positive Phase 3 data.</p></article></html>",
        )
    )
    service = NewsService(db_session, http_client=httpx.Client(transport=transport))

    inserted = service.ingest_feeds()
    item = db_session.query(NewsItem).one()

    assert inserted == 1
    assert item.source_type == "official_company_pr"
    assert item.is_official_source is True
    assert item.company_tag_ids == [company.id]
    assert "Apex Bio" in item.mentioned_companies


def test_news_ingestion_supports_builtin_html_ir_pages(db_session, monkeypatch):
    company = Company(
        cik="0000000456",
        ticker="GILD",
        name="Gilead Sciences",
        exchange="NASDAQ",
        sic="2834",
        sic_description="PHARMACEUTICAL PREPARATIONS",
        market_cap=120_000_000_000,
        market_cap_source="test",
        is_active=True,
    )
    db_session.add(company)
    db_session.commit()

    source_url = str(COMPANY_IR_SOURCES["GILD"][0]["url"])
    article_url = "https://investors.gilead.com/news/news-details/2026/Gilead-Announces-Phase-3-Data/default.aspx"

    monkeypatch.setattr(feedparser, "parse", lambda url: feedparser.FeedParserDict(entries=[]))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == source_url:
            return httpx.Response(
                200,
                text="""
                <html>
                  <body>
                    <section>
                      <a href="/news/news-details/2026/Gilead-Announces-Phase-3-Data/default.aspx">
                        Gilead announces Phase 3 data in oncology
                      </a>
                      <div>March 27, 2026</div>
                    </section>
                  </body>
                </html>
                """,
            )
        if str(request.url) == article_url:
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <meta property="article:published_time" content="2026-03-27T08:00:00-04:00" />
                  </head>
                  <body>
                    <article>
                      <p>Gilead Sciences reported positive Phase 3 oncology data.</p>
                    </article>
                  </body>
                </html>
                """,
            )
        return httpx.Response(404)

    service = NewsService(db_session, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    inserted = service.ingest_feeds()
    item = db_session.query(NewsItem).one()

    assert inserted == 1
    assert item.source_type == "official_company_pr"
    assert item.is_official_source is True
    assert item.company_tag_ids == [company.id]
    assert item.canonical_url == article_url
    assert item.title == "Gilead announces Phase 3 data in oncology"


def test_news_summarize_item_consumes_override_budget(db_session, company, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MAX_OVERRIDE_SUMMARIES_PER_DAY", "1")
    from app.config import get_settings

    get_settings.cache_clear()

    first = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Apex Bio raises guidance",
        canonical_url="https://example.com/story-override-1",
        excerpt="Guidance raised",
        content_text="Apex Bio raised guidance after FDA clearance.",
        published_at=company.market_cap_updated_at,
        article_hash="hash-override-1",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["finance"],
        summary_status="pending",
        summary_tier="no_ai",
    )
    second = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Apex Bio expands plant",
        canonical_url="https://example.com/story-override-2",
        excerpt="Plant expansion",
        content_text="Apex Bio expanded a major manufacturing plant.",
        published_at=company.market_cap_updated_at,
        article_hash="hash-override-2",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["manufacturing"],
        summary_status="pending",
        summary_tier="no_ai",
    )
    db_session.add_all([first, second])
    db_session.commit()

    service = NewsService(db_session, summarizer=StubSummarizer())
    result = service.summarize_item(first.id, consume_override_budget=True)

    db_session.refresh(first)
    assert result["status"] == "summarized"
    assert first.summary_status == "complete"

    try:
        service.summarize_item(second.id, consume_override_budget=True)
        assert False, "expected override budget exhaustion"
    except RuntimeError as exc:
        assert str(exc) == "override_budget_exhausted"
    finally:
        get_settings.cache_clear()


def test_news_pending_queue_counts_uses_narrow_projection(db_session, monkeypatch):
    monkeypatch.setattr("app.services.news._watchlist_company_ids", lambda session: set())
    captured: dict[str, str] = {}

    class FakeResult:
        def all(self):
            return []

    def fake_execute(statement, *args, **kwargs):
        captured["sql"] = str(statement)
        return FakeResult()

    monkeypatch.setattr(db_session, "execute", fake_execute)

    counts = NewsService(db_session).pending_queue_counts()
    sql = captured["sql"].upper()

    assert counts == {"news_pending": 0, "news_pending_full_ai": 0, "news_pending_short_ai": 0}
    assert "NEWS_ITEMS.CONTENT_TEXT" not in sql
    assert "NEWS_ITEMS.SUMMARY_JSON" not in sql
    assert "NEWS_ITEMS.EXCERPT" not in sql
