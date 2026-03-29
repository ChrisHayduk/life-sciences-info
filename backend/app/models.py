from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    exchange: Mapped[str | None] = mapped_column(String(64))
    sic: Mapped[str | None] = mapped_column(String(8), index=True)
    sic_description: Mapped[str | None] = mapped_column(String(255))
    universe_reason: Mapped[str] = mapped_column(String(255), default="sic-allowlist")
    market_cap: Mapped[int | None] = mapped_column(BigInteger)
    market_cap_currency: Mapped[str] = mapped_column(String(8), default="USD")
    market_cap_source: Mapped[str | None] = mapped_column(String(64))
    market_cap_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    filings: Mapped[list[Filing]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Filing(Base, TimestampMixin):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filings_accession_number"),
        Index("ix_filings_company_form_filed_at", "company_id", "normalized_form_type", "filed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    prior_comparable_filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    accession_number: Mapped[str] = mapped_column(String(32))
    form_type: Mapped[str] = mapped_column(String(16), index=True)
    normalized_form_type: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255))
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end_date: Mapped[date | None] = mapped_column(Date)
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    is_periodic_equivalent: Mapped[bool] = mapped_column(Boolean, default=True)
    filing_url: Mapped[str] = mapped_column(Text)
    original_document_url: Mapped[str] = mapped_column(Text)
    source_json_url: Mapped[str | None] = mapped_column(Text)
    primary_document: Mapped[str | None] = mapped_column(String(255))
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_sections: Mapped[dict] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary_model: Mapped[str | None] = mapped_column(String(64))
    summary_prompt_version: Mapped[str | None] = mapped_column(String(64))
    summary_status: Mapped[str] = mapped_column(String(32), default="pending")
    summary_tier: Mapped[str] = mapped_column(String(32), default="no_ai")
    summary_attempts: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str] = mapped_column(String(32), default="official_filing")
    event_type: Mapped[str | None] = mapped_column(String(64))
    priority_reason: Mapped[str | None] = mapped_column(String(255))
    is_official_source: Mapped[bool] = mapped_column(Boolean, default=True)
    dedupe_group_id: Mapped[str | None] = mapped_column(String(128), index=True)
    freshness_bucket: Mapped[str] = mapped_column(String(32), default="stale")
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap_score: Mapped[float] = mapped_column(Float, default=0.0)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    score_confidence: Mapped[str] = mapped_column(String(32), default="high")
    raw_artifact_key: Mapped[str | None] = mapped_column(String(255))
    pdf_artifact_key: Mapped[str | None] = mapped_column(String(255))
    item_numbers: Mapped[list] = mapped_column(JSON, default=list)
    diff_json: Mapped[dict] = mapped_column(JSON, default=dict)
    diff_status: Mapped[str] = mapped_column(String(32), default="pending")
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    company: Mapped[Company] = relationship(back_populates="filings", foreign_keys=[company_id])
    prior_comparable_filing: Mapped[Filing | None] = relationship(remote_side=[id], foreign_keys=[prior_comparable_filing_id])


class NewsItem(Base, TimestampMixin):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_news_canonical_url"),
        UniqueConstraint("article_hash", name="uq_news_article_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    source_weight: Mapped[float] = mapped_column(Float, default=0.5)
    feed_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(512), index=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    article_hash: Mapped[str] = mapped_column(String(64))
    mentioned_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    company_tag_ids: Mapped[list[int] | None] = mapped_column(JSON, default=list)
    topic_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary_model: Mapped[str | None] = mapped_column(String(64))
    summary_prompt_version: Mapped[str | None] = mapped_column(String(64))
    summary_status: Mapped[str] = mapped_column(String(32), default="pending")
    summary_tier: Mapped[str] = mapped_column(String(32), default="no_ai")
    summary_attempts: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str] = mapped_column(String(32), default="trade_press")
    event_type: Mapped[str | None] = mapped_column(String(64))
    priority_reason: Mapped[str | None] = mapped_column(String(255))
    is_official_source: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_group_id: Mapped[str | None] = mapped_column(String(128), index=True)
    freshness_bucket: Mapped[str] = mapped_column(String(32), default="stale")
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap_score: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class FilingNewsLink(Base):
    """Association between a filing and a news item that cover the same event."""
    __tablename__ = "filing_news_links"
    __table_args__ = (
        UniqueConstraint("filing_id", "news_item_id", name="uq_filing_news_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), index=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(32), default="temporal")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)


class Digest(Base, TimestampMixin):
    __tablename__ = "digests"
    __table_args__ = (
        UniqueConstraint("digest_type", "window_start", "window_end", name="uq_digests_window"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest_type: Mapped[str] = mapped_column(String(32), default="weekly")
    title: Mapped[str] = mapped_column(String(255))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    narrative_summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ClinicalTrial(Base, TimestampMixin):
    """Clinical trial data sourced from ClinicalTrials.gov."""
    __tablename__ = "clinical_trials"
    __table_args__ = (
        UniqueConstraint("nct_id", name="uq_clinical_trials_nct_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nct_id: Mapped[str] = mapped_column(String(16), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(512))
    phase: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    interventions: Mapped[list] = mapped_column(JSON, default=list)
    sponsor: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    primary_completion_date: Mapped[date | None] = mapped_column(Date)
    last_update_date: Mapped[date | None] = mapped_column(Date, index=True)
    enrollment: Mapped[int | None] = mapped_column(Integer)
    study_type: Mapped[str | None] = mapped_column(String(64))
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    company: Mapped[Company | None] = relationship(foreign_keys=[company_id])


class RegulatoryEvent(Base, TimestampMixin):
    """Official regulatory or advisory-calendar event."""

    __tablename__ = "regulatory_events"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_regulatory_events_canonical_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committee_name: Mapped[str | None] = mapped_column(String(255), index=True)
    summary_text: Mapped[str | None] = mapped_column(Text)
    mentioned_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    company_tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    topic_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_type: Mapped[str] = mapped_column(String(32), default="regulator")
    event_type: Mapped[str] = mapped_column(String(64), default="fda-advisory-committee")
    priority_reason: Mapped[str | None] = mapped_column(String(255))
    is_official_source: Mapped[bool] = mapped_column(Boolean, default=True)
    freshness_bucket: Mapped[str] = mapped_column(String(32), default="upcoming")
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap_score: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class Watchlist(Base, TimestampMixin):
    """User-defined watchlist for tracking specific companies and topics."""
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(255))
    preset_key: Mapped[str | None] = mapped_column(String(64), index=True)
    company_ids: Mapped[list] = mapped_column(JSON, default=list)
    form_types: Mapped[list] = mapped_column(JSON, default=list)
    topic_tags: Mapped[list] = mapped_column(JSON, default=list)


class SummaryUsage(Base, TimestampMixin):
    __tablename__ = "summary_usage"
    __table_args__ = (
        UniqueConstraint("usage_date", "kind", name="uq_summary_usage_date_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    model_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
