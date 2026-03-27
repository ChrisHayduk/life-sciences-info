from __future__ import annotations

from datetime import datetime, timezone

from app.models import Filing, NewsItem
from app.services.ranking import compute_filing_scores, compute_news_scores


def test_filing_scores_reflect_material_change_and_degraded_market_cap():
    current = Filing(
        accession_number="1",
        company_id=1,
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Apex Bio 10-Q",
        filed_at=datetime.now(timezone.utc),
        filing_url="https://example.com",
        original_document_url="https://example.com/doc",
        summary_json={"importance_score": 85},
        raw_text="Revenue increased 45%. FDA approval expected. Manufacturing expansion announced.",
    )
    prior = Filing(
        accession_number="0",
        company_id=1,
        form_type="10-Q",
        normalized_form_type="10-Q",
        title="Prior 10-Q",
        filed_at=datetime.now(timezone.utc),
        filing_url="https://example.com",
        original_document_url="https://example.com/doc",
        summary_json={"importance_score": 40},
        raw_text="Revenue increased 5%.",
    )

    high_scores = compute_filing_scores(current, company_market_cap_score=92, has_market_cap=True, prior_filing=prior)
    degraded_scores = compute_filing_scores(
        current,
        company_market_cap_score=0,
        has_market_cap=False,
        prior_filing=prior,
    )

    assert float(high_scores["composite_score"]) > float(degraded_scores["composite_score"])
    assert degraded_scores["score_confidence"] == "degraded"
    assert float(high_scores["impact_score"]) > 70


def test_filing_scores_allow_zero_percentile_when_market_cap_exists():
    filing = Filing(
        accession_number="2",
        company_id=1,
        form_type="10-K",
        normalized_form_type="10-K",
        title="Small Cap 10-K",
        filed_at=datetime.now(timezone.utc),
        filing_url="https://example.com",
        original_document_url="https://example.com/doc",
        summary_json={"importance_score": 50},
        raw_text="Revenue increased 10%.",
    )

    scores = compute_filing_scores(filing, company_market_cap_score=0, has_market_cap=True, prior_filing=None)

    assert scores["market_cap_score"] == 0
    assert scores["score_confidence"] == "high"


def test_news_scores_renormalize_without_company_mentions():
    news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="FDA approves new therapy",
        canonical_url="https://example.com/story",
        published_at=datetime.now(timezone.utc),
        article_hash="hash",
        mentioned_companies=[],
        summary_json={"importance_score": 90},
    )

    scores = compute_news_scores(news, company_market_cap_score=0)
    assert float(scores["composite_score"]) > 70
    assert scores["score_explanation"]["confidence"] == "medium"
