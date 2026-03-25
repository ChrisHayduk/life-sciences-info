from __future__ import annotations

from datetime import datetime, timezone

from app.models import Filing, NewsItem


def test_company_list_and_detail_include_labels_filings_and_news(client, db_session, company):
    company.market_cap = 4_500_000_000
    company.market_cap_source = "alpha_vantage_overview"
    company.universe_reason = "sic-allowlist"

    filing = Filing(
        company_id=company.id,
        accession_number="0001",
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Apex Bio Q1",
        filed_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
        filing_url="https://example.com/index",
        original_document_url="https://example.com/doc",
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
        published_at=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        article_hash="hash-1",
        mentioned_companies=["Apex Bio", "ABIO"],
        topic_tags=["manufacturing"],
        summary_json={"summary": "Plant expansion", "key_takeaways": ["New capacity"], "importance_score": 68},
        importance_score=68,
        market_cap_score=90,
        composite_score=75,
        score_explanation={"components": {"importance": 68}, "confidence": "high"},
    )
    db_session.add_all([filing, news])
    db_session.commit()

    companies_response = client.get("/api/v1/companies")
    assert companies_response.status_code == 200
    assert companies_response.json()[0]["universe_reason_label"] == "Core life sciences SIC filter"

    detail_response = client.get(f"/api/v1/companies/{company.id}")
    payload = detail_response.json()

    assert detail_response.status_code == 200
    assert payload["market_cap"] == 4_500_000_000
    assert payload["filings_count"] == 1
    assert payload["news_count"] == 1
    assert payload["recent_filings"][0]["id"] == filing.id
    assert payload["recent_news"][0]["id"] == news.id
