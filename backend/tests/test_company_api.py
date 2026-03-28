from __future__ import annotations

from datetime import datetime, timezone

from datetime import date, timedelta

from app.models import ClinicalTrial, Filing, NewsItem, RegulatoryEvent, Watchlist


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
        company_tag_ids=[company.id],
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


def test_company_detail_news_uses_explicit_company_tags_not_freeform_mentions(client, db_session, company):
    tagged_news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Tagged story",
        canonical_url="https://example.com/tagged-story",
        excerpt="Tagged story",
        content_text="Sector update",
        published_at=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        article_hash="hash-tagged",
        mentioned_companies=["Sector update"],
        company_tag_ids=[company.id],
        topic_tags=["manufacturing"],
        composite_score=80,
        importance_score=70,
        market_cap_score=90,
        score_explanation={"components": {"importance": 70}, "confidence": "high"},
    )
    untagged_news = NewsItem(
        source_name="Fierce Pharma",
        source_weight=0.95,
        feed_url="https://example.com/rss",
        title="Mention-only story",
        canonical_url="https://example.com/mention-only-story",
        excerpt="Mention-only story",
        content_text="Mention-only story",
        published_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
        article_hash="hash-mention-only",
        mentioned_companies=["Apex Bio", "ABIO"],
        company_tag_ids=[],
        topic_tags=["finance"],
        composite_score=90,
        importance_score=75,
        market_cap_score=90,
        score_explanation={"components": {"importance": 75}, "confidence": "high"},
    )
    db_session.add_all([tagged_news, untagged_news])
    db_session.commit()

    detail_response = client.get(f"/api/v1/companies/{company.id}")
    payload = detail_response.json()

    assert detail_response.status_code == 200
    assert payload["news_count"] == 1
    assert [item["id"] for item in payload["recent_news"]] == [tagged_news.id]


def test_company_detail_groups_filings_by_type_priority_and_chronology(client, db_session, company):
    filings = [
        Filing(
            company_id=company.id,
            accession_number="annual-old",
            form_type="10-K",
            normalized_form_type="10-K",
            title="Apex Bio 2024 10-K",
            filed_at=datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc),
            filing_url="https://example.com/annual-old-index",
            original_document_url="https://example.com/annual-old-doc",
            importance_score=95,
            market_cap_score=90,
            impact_score=90,
            composite_score=99,
            score_explanation={"components": {"impact": 90}, "confidence": "high"},
        ),
        Filing(
            company_id=company.id,
            accession_number="annual-new",
            form_type="10-K",
            normalized_form_type="10-K",
            title="Apex Bio 2025 10-K",
            filed_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            filing_url="https://example.com/annual-new-index",
            original_document_url="https://example.com/annual-new-doc",
            importance_score=80,
            market_cap_score=90,
            impact_score=80,
            composite_score=70,
            score_explanation={"components": {"impact": 80}, "confidence": "high"},
        ),
        Filing(
            company_id=company.id,
            accession_number="quarter-high",
            form_type="10-Q/A",
            normalized_form_type="10-Q",
            title="Apex Bio Q1 Amendment",
            filed_at=datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc),
            filing_url="https://example.com/quarter-high-index",
            original_document_url="https://example.com/quarter-high-doc",
            importance_score=85,
            market_cap_score=90,
            impact_score=85,
            composite_score=88,
            score_explanation={"components": {"impact": 85}, "confidence": "high"},
        ),
        Filing(
            company_id=company.id,
            accession_number="quarter-low",
            form_type="10-Q",
            normalized_form_type="10-Q",
            title="Apex Bio Q1",
            filed_at=datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc),
            filing_url="https://example.com/quarter-low-index",
            original_document_url="https://example.com/quarter-low-doc",
            importance_score=78,
            market_cap_score=90,
            impact_score=78,
            composite_score=72,
            score_explanation={"components": {"impact": 78}, "confidence": "high"},
        ),
        Filing(
            company_id=company.id,
            accession_number="interim-latest",
            form_type="6-K",
            normalized_form_type="6-K",
            title="Apex Bio Interim Update",
            filed_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
            filing_url="https://example.com/interim-latest-index",
            original_document_url="https://example.com/interim-latest-doc",
            importance_score=92,
            market_cap_score=90,
            impact_score=92,
            composite_score=97,
            score_explanation={"components": {"impact": 92}, "confidence": "high"},
        ),
    ]
    db_session.add_all(filings)
    db_session.commit()

    response = client.get(f"/api/v1/companies/{company.id}")
    payload = response.json()

    assert response.status_code == 200
    assert [item["normalized_form_type"] for item in payload["recent_filings"]] == ["10-K", "10-K", "10-Q", "10-Q", "6-K"]
    assert [item["id"] for item in payload["recent_filings"]] == [
        filings[1].id,
        filings[0].id,
        filings[2].id,
        filings[3].id,
        filings[4].id,
    ]


def test_dashboard_top_filings_remain_globally_ranked(client, db_session, company):
    highest_score = Filing(
        company_id=company.id,
        accession_number="global-high",
        form_type="6-K",
        normalized_form_type="6-K",
        title="Highest composite 6-K",
        filed_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
        filing_url="https://example.com/global-high-index",
        original_document_url="https://example.com/global-high-doc",
        importance_score=92,
        market_cap_score=90,
        impact_score=92,
        composite_score=98,
        score_explanation={"components": {"impact": 92}, "confidence": "high"},
    )
    lower_score = Filing(
        company_id=company.id,
        accession_number="global-lower",
        form_type="10-K",
        normalized_form_type="10-K",
        title="Lower composite 10-K",
        filed_at=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
        filing_url="https://example.com/global-lower-index",
        original_document_url="https://example.com/global-lower-doc",
        importance_score=80,
        market_cap_score=90,
        impact_score=80,
        composite_score=70,
        score_explanation={"components": {"impact": 80}, "confidence": "high"},
    )
    db_session.add_all([highest_score, lower_score])
    db_session.commit()

    response = client.get("/api/v1/dashboard")
    payload = response.json()

    assert response.status_code == 200
    assert payload["top_filings"][0]["id"] == highest_score.id


def test_company_detail_and_watchlist_briefing_include_structured_catalysts(client, db_session, company):
    filing = Filing(
        company_id=company.id,
        accession_number="catalyst-filing",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio announces collaboration",
        filed_at=datetime.now(timezone.utc) - timedelta(days=2),
        filing_url="https://example.com/catalyst-index",
        original_document_url="https://example.com/catalyst-doc",
        summary_status="pending",
        summary_tier="no_ai",
        source_type="official_filing",
        event_type="material-agreement",
        priority_reason="material agreement event",
        is_official_source=True,
        freshness_bucket="last_7d",
        composite_score=78.0,
        importance_score=55.0,
        market_cap_score=80.0,
        impact_score=70.0,
        score_explanation={"components": {"recency": 80}, "confidence": "high"},
    )
    news = NewsItem(
        source_name="Apex Bio Investor Relations",
        source_weight=0.98,
        feed_url="https://ir.example.com/rss",
        title="Apex Bio reports positive Phase 3 data",
        canonical_url="https://ir.example.com/phase-3-data",
        excerpt="Positive Phase 3 data",
        content_text="Official company press release describing positive Phase 3 data.",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        article_hash="catalyst-news",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["company-pr", "clinical"],
        summary_status="pending",
        summary_tier="no_ai",
        source_type="official_company_pr",
        event_type="clinical-data",
        priority_reason="official source, clinical data coverage",
        is_official_source=True,
        freshness_bucket="last_24h",
        composite_score=88.0,
        importance_score=70.0,
        market_cap_score=80.0,
        score_explanation={"components": {"importance": 70}, "confidence": "high"},
    )
    trial = ClinicalTrial(
        nct_id="NCT00000001",
        company_id=company.id,
        title="Apex Bio pivotal study",
        phase="Phase 3",
        status="Recruiting",
        sponsor="Apex Bio",
        primary_completion_date=date.today() + timedelta(days=45),
        last_update_date=date.today(),
    )
    watchlist = Watchlist(name="Tracked names", company_ids=[company.id])
    db_session.add_all([filing, news, trial, watchlist])
    db_session.commit()

    company_response = client.get(f"/api/v1/companies/{company.id}")
    company_payload = company_response.json()

    assert company_response.status_code == 200
    assert company_payload["catalysts"]
    assert {item["item_type"] for item in company_payload["catalysts"]} >= {"news", "trial"}

    watchlist_response = client.get(f"/api/v1/watchlists/{watchlist.id}/briefing")
    watchlist_payload = watchlist_response.json()

    assert watchlist_response.status_code == 200
    assert watchlist_payload["catalysts"]
    assert any(item["item_type"] == "trial" for item in watchlist_payload["catalysts"])


def test_company_and_dashboard_surfaces_include_regulatory_events(client, db_session, company):
    event = RegulatoryEvent(
        source_name="FDA Advisory Committee Calendar",
        title="April 30, 2026: Meeting of the Oncologic Drugs Advisory Committee",
        canonical_url="https://www.fda.gov/advisory-committees/advisory-committee-calendar/april-30-2026-apex-bio",
        starts_at=datetime.now(timezone.utc) + timedelta(days=10),
        committee_name="Oncologic Drugs Advisory Committee",
        summary_text="The FDA will discuss Apex Bio's oncology application.",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["regulatory", "advisory-committee"],
        source_type="regulator",
        event_type="fda-advisory-committee",
        priority_reason="official FDA calendar, upcoming committee date, linked to tracked company",
        is_official_source=True,
        freshness_bucket="upcoming",
        importance_score=88.0,
        market_cap_score=100.0,
        composite_score=92.0,
    )
    watchlist = Watchlist(name="Tracked names", company_ids=[company.id])
    db_session.add_all([event, watchlist])
    db_session.commit()

    company_response = client.get(f"/api/v1/companies/{company.id}")
    company_payload = company_response.json()
    assert company_response.status_code == 200
    assert any(item["item_type"] == "regulatory" for item in company_payload["catalysts"])
    assert any(item["item_type"] == "regulatory" for item in company_payload["timeline"])

    watchlist_response = client.get(f"/api/v1/watchlists/{watchlist.id}/briefing")
    watchlist_payload = watchlist_response.json()
    assert watchlist_response.status_code == 200
    assert any(item["item_type"] == "regulatory" for item in watchlist_payload["timeline"])

    dashboard_response = client.get("/api/v1/dashboard")
    dashboard_payload = dashboard_response.json()
    assert dashboard_response.status_code == 200
    assert dashboard_payload["upcoming_regulatory_events"]
    assert dashboard_payload["upcoming_regulatory_events"][0]["item_type"] == "regulatory"
