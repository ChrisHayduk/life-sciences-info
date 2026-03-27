from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Digest, Filing, NewsItem
from app.services.digests import DigestService


def test_weekly_digest_window_and_dashboard_api(client, db_session, company):
    now = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="0001",
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Apex Bio Q1",
        filed_at=now - timedelta(days=2),
        filing_url="https://example.com/index",
        original_document_url="https://example.com/doc",
        pdf_artifact_key="filings/pdf/1.pdf",
        summary_json={"summary": "Quarter improved", "importance_score": 72},
        importance_score=72,
        market_cap_score=90,
        impact_score=76,
        composite_score=81,
        score_explanation={"components": {"impact": 76}, "confidence": "high"},
    )
    news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Apex Bio expands plant",
        canonical_url="https://example.com/story",
        excerpt="Expansion announced",
        content_text="Expansion announced",
        published_at=now - timedelta(days=1),
        article_hash="hash-1",
        mentioned_companies=["Apex Bio"],
        topic_tags=["manufacturing"],
        summary_json={"summary": "Plant expansion", "key_takeaways": ["New capacity"], "importance_score": 68},
        importance_score=68,
        market_cap_score=90,
        composite_score=75,
        score_explanation={"components": {"importance": 68}, "confidence": "high"},
    )
    db_session.add_all([filing, news])
    db_session.commit()

    digest_service = DigestService(db_session)
    digest = digest_service.build_weekly_digest(reference=now)
    digest_repeat = digest_service.build_weekly_digest(reference=now)

    assert digest.window_end > digest.window_start
    assert digest.payload["filings"][0]["id"] == filing.id
    assert digest.payload["news"][0]["id"] == news.id
    assert digest_repeat.id == digest.id
    assert db_session.query(Digest).count() == 1

    response = client.get("/api/v1/dashboard")
    payload = response.json()

    assert response.status_code == 200
    assert payload["top_filings"][0]["pdf_download_url"].endswith(f"/artifacts/filings/{filing.id}/pdf")
    assert payload["top_news"][0]["title"] == "Apex Bio expands plant"


def test_dashboard_prefers_recent_filings_and_news(client, db_session, company):
    now = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    recent_filing = Filing(
        company_id=company.id,
        accession_number="recent-filing",
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Recent Apex Bio Q1",
        filed_at=now - timedelta(days=5),
        filing_url="https://example.com/recent-index",
        original_document_url="https://example.com/recent-doc",
        summary_json={"summary": "Recent quarter", "importance_score": 70},
        importance_score=70,
        market_cap_score=70,
        impact_score=72,
        composite_score=74,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    stale_filing = Filing(
        company_id=company.id,
        accession_number="stale-filing",
        form_type="10-K",
        normalized_form_type="10-K",
        title="Stale Apex Bio 10-K",
        filed_at=now - timedelta(days=4000),
        filing_url="https://example.com/stale-index",
        original_document_url="https://example.com/stale-doc",
        summary_json={"summary": "Old filing", "importance_score": 99},
        importance_score=99,
        market_cap_score=99,
        impact_score=99,
        composite_score=99,
        score_explanation={"components": {"recency": 10}, "confidence": "high"},
    )
    recent_news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Recent plant expansion",
        canonical_url="https://example.com/recent-story",
        excerpt="Recent expansion",
        content_text="Recent expansion",
        published_at=now - timedelta(days=2),
        article_hash="recent-news",
        mentioned_companies=["Apex Bio"],
        topic_tags=["manufacturing"],
        summary_json={"summary": "Recent news", "importance_score": 60},
        importance_score=60,
        market_cap_score=60,
        composite_score=68,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    stale_news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Old financing story",
        canonical_url="https://example.com/stale-story",
        excerpt="Old story",
        content_text="Old story",
        published_at=now - timedelta(days=120),
        article_hash="stale-news",
        mentioned_companies=["Apex Bio"],
        topic_tags=["finance"],
        summary_json={"summary": "Old news", "importance_score": 98},
        importance_score=98,
        market_cap_score=98,
        composite_score=98,
        score_explanation={"components": {"recency": 20}, "confidence": "high"},
    )
    db_session.add_all([recent_filing, stale_filing, recent_news, stale_news])
    db_session.commit()

    response = client.get("/api/v1/dashboard")
    payload = response.json()

    assert response.status_code == 200
    assert [item["id"] for item in payload["top_filings"]] == [recent_filing.id]
    assert [item["id"] for item in payload["top_news"]] == [recent_news.id]
