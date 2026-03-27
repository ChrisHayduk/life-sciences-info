from __future__ import annotations

import feedparser
import httpx

from app.models import NewsItem
from app.services.news import NewsService


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
