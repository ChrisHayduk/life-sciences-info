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
