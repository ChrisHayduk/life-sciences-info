from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Digest, Filing, NewsItem
from app.services.digest_email import DigestEmailService
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


def test_daily_digest_reuses_existing_window(db_session, company):
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="daily-1",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio partnership update",
        filed_at=now - timedelta(hours=20),
        filing_url="https://example.com/daily-index",
        original_document_url="https://example.com/daily-doc",
        summary_json={"summary": "Partnership expanded", "importance_score": 80},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=80,
        market_cap_score=90,
        impact_score=84,
        composite_score=86,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    news = NewsItem(
        source_name="FDA Press Releases",
        source_weight=1.0,
        feed_url="https://example.com/rss",
        title="Apex Bio receives FDA milestone",
        canonical_url="https://example.com/daily-story",
        excerpt="FDA milestone",
        content_text="FDA milestone",
        published_at=now - timedelta(hours=18),
        article_hash="daily-news",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["regulatory"],
        summary_json={"summary": "Regulatory milestone", "importance_score": 84},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=84,
        market_cap_score=90,
        composite_score=88,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    db_session.add_all([filing, news])
    db_session.commit()

    digest_service = DigestService(db_session)
    digest = digest_service.build_daily_digest(reference=now)
    digest_repeat = digest_service.build_daily_digest(reference=now)

    assert digest.digest_type == "daily"
    assert digest_repeat.id == digest.id
    assert digest.payload["filings"][0]["id"] == filing.id
    assert digest.payload["news"][0]["id"] == news.id


class FakeDigestEmailSender:
    def __init__(self, *, enabled: bool = True, configured: bool = True, fail_times: int = 0):
        self.enabled = enabled
        self.configured = configured
        self.fail_times = fail_times
        self.sent_digest_ids: list[int] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def is_configured(self) -> bool:
        return self.configured

    def send_daily_digest(self, digest: Digest) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("smtp unavailable")
        self.sent_digest_ids.append(digest.id)


def test_daily_digest_email_sends_once_and_reuses_window(db_session, company):
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="daily-email-filing",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio partnership update",
        filed_at=now - timedelta(hours=20),
        filing_url="https://example.com/daily-index",
        original_document_url="https://example.com/daily-doc",
        summary_json={"summary": "Partnership expanded", "importance_score": 80},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=80,
        market_cap_score=90,
        impact_score=84,
        composite_score=86,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    news = NewsItem(
        source_name="FDA Press Releases",
        source_weight=1.0,
        feed_url="https://example.com/rss",
        title="Apex Bio receives FDA milestone",
        canonical_url="https://example.com/daily-story",
        excerpt="FDA milestone",
        content_text="FDA milestone",
        published_at=now - timedelta(hours=18),
        article_hash="daily-email-news",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["regulatory"],
        summary_json={"summary": "Regulatory milestone", "importance_score": 84},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=84,
        market_cap_score=90,
        composite_score=88,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    db_session.add_all([filing, news])
    db_session.commit()

    sender = FakeDigestEmailSender()
    service = DigestService(db_session, email_sender=sender)

    first = service.send_daily_digest_email(reference=now)
    second = service.send_daily_digest_email(reference=now)
    digest = db_session.get(Digest, int(first["digest_id"]))

    assert first["delivery_status"] == "sent"
    assert first["built"] is True
    assert second["delivery_status"] == "already_sent"
    assert second["built"] is False
    assert sender.sent_digest_ids == [digest.id]
    assert digest.email_delivery_status == "sent"
    assert digest.email_delivered_at is not None
    assert db_session.query(Digest).count() == 1


def test_daily_digest_email_skips_quiet_days(db_session):
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    sender = FakeDigestEmailSender()
    service = DigestService(db_session, email_sender=sender)

    result = service.send_daily_digest_email(reference=now)
    digest = db_session.get(Digest, int(result["digest_id"]))

    assert result["delivery_status"] == "skipped"
    assert sender.sent_digest_ids == []
    assert digest.email_delivery_status == "skipped"


def test_daily_digest_email_failure_is_persisted_and_retry_succeeds(db_session, company):
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="daily-email-retry",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio retry event",
        filed_at=now - timedelta(hours=20),
        filing_url="https://example.com/retry-index",
        original_document_url="https://example.com/retry-doc",
        summary_json={"summary": "Retry summary", "importance_score": 76},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=76,
        market_cap_score=90,
        impact_score=79,
        composite_score=82,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    db_session.add(filing)
    db_session.commit()

    sender = FakeDigestEmailSender(fail_times=1)
    service = DigestService(db_session, email_sender=sender)

    failed = service.send_daily_digest_email(reference=now)
    digest = db_session.get(Digest, int(failed["digest_id"]))
    assert failed["delivery_status"] == "failed"
    assert digest.email_delivery_status == "failed"
    assert digest.email_delivery_error == "smtp unavailable"

    retried = service.send_daily_digest_email(reference=now)
    digest = db_session.get(Digest, int(retried["digest_id"]))
    assert retried["delivery_status"] == "sent"
    assert digest.email_delivery_status == "sent"
    assert sender.sent_digest_ids == [digest.id]


def test_daily_digest_email_returns_disabled_when_sender_is_not_configured(db_session, company):
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="daily-email-disabled",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio email disabled event",
        filed_at=now - timedelta(hours=20),
        filing_url="https://example.com/disabled-index",
        original_document_url="https://example.com/disabled-doc",
        summary_json={"summary": "Disabled summary", "importance_score": 76},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=76,
        market_cap_score=90,
        impact_score=79,
        composite_score=82,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    db_session.add(filing)
    db_session.commit()

    sender = FakeDigestEmailSender(enabled=False, configured=False)
    service = DigestService(db_session, email_sender=sender)

    result = service.send_daily_digest_email(reference=now)
    digest = db_session.get(Digest, int(result["digest_id"]))

    assert result["delivery_status"] == "disabled"
    assert digest.email_delivery_status == "pending"


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: int = 30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ehlo(self):
        return None

    def starttls(self, context=None):
        return None

    def login(self, username: str, password: str):
        self.username = username
        self.password = password

    def send_message(self, message):
        self.messages.append(message)


def test_digest_email_message_contains_subject_and_links(db_session, company, monkeypatch):
    monkeypatch.setenv("DIGEST_EMAIL_ENABLED", "true")
    monkeypatch.setenv("DIGEST_EMAIL_TO", "chris.hayduk1@gmail.com")
    monkeypatch.setenv("DIGEST_EMAIL_FROM", "chris.hayduk1@gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "chris.hayduk1@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://life-sciences-info.vercel.app")
    from app.config import get_settings

    get_settings.cache_clear()
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    filing = Filing(
        company_id=company.id,
        accession_number="daily-email-format",
        form_type="8-K",
        normalized_form_type="8-K",
        title="Apex Bio formatted event",
        filed_at=now - timedelta(hours=20),
        filing_url="https://example.com/format-index",
        original_document_url="https://example.com/format-doc",
        summary_json={"summary": "Formatted summary", "importance_score": 82},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=82,
        market_cap_score=90,
        impact_score=84,
        composite_score=86,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    news = NewsItem(
        source_name="FDA Press Releases",
        source_weight=1.0,
        feed_url="https://example.com/rss",
        title="Apex Bio formatted news",
        canonical_url="https://example.com/formatted-story",
        excerpt="Formatted news",
        content_text="Formatted news",
        published_at=now - timedelta(hours=18),
        article_hash="formatted-news",
        mentioned_companies=["Apex Bio"],
        company_tag_ids=[company.id],
        topic_tags=["regulatory"],
        summary_json={"summary": "Formatted news summary", "importance_score": 83},
        summary_status="complete",
        summary_tier="full_ai",
        importance_score=83,
        market_cap_score=90,
        composite_score=87,
        score_explanation={"components": {"recency": 100}, "confidence": "high"},
    )
    db_session.add_all([filing, news])
    db_session.commit()

    digest = DigestService(db_session).build_daily_digest(reference=now)
    sender = DigestEmailService(smtp_factory=FakeSMTP)
    message = sender.build_daily_digest_message(digest)

    assert message["Subject"] == "Daily Life Sciences Briefing: 2026-03-30"
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "https://life-sciences-info.vercel.app/digests" in plain
    assert f"https://life-sciences-info.vercel.app/filings/{filing.id}" in plain
    assert f"https://life-sciences-info.vercel.app/companies/{company.id}" in plain
    assert "https://example.com/formatted-story" in plain
    assert "https://life-sciences-info.vercel.app/digests" in html
    get_settings.cache_clear()
