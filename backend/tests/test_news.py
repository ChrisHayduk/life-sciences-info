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
