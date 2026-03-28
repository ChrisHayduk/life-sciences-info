from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScoreExplanation(BaseModel):
    model_config = ConfigDict(extra="allow")

    components: dict[str, float] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    confidence: str = "high"


class ExtractedEntity(BaseModel):
    name: str
    type: str
    context: str = ""


class SummaryPayload(BaseModel):
    summary: str = ""
    event_type: str = ""  # Populated for 8-K filings (e.g., "leadership-change", "acquisition")
    key_takeaways: list[str] = Field(default_factory=list)
    material_changes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    opportunity_flags: list[str] = Field(default_factory=list)
    company_mentions: list[str] = Field(default_factory=list)
    evidence_sections: list[str] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    importance_score: float = 0.0
    market_cap_score: float = 0.0
    composite_score: float = 0.0
    score_explanation: str = ""


class SummaryBudgetSnapshot(BaseModel):
    used: int = 0
    limit: int = 0
    remaining: int = 0


class SummaryBudgetOverview(BaseModel):
    filing: SummaryBudgetSnapshot = Field(default_factory=SummaryBudgetSnapshot)
    news: SummaryBudgetSnapshot = Field(default_factory=SummaryBudgetSnapshot)
    override: SummaryBudgetSnapshot = Field(default_factory=SummaryBudgetSnapshot)


class CompanyResponse(BaseModel):
    id: int
    cik: str
    ticker: str | None
    name: str
    exchange: str | None
    sic: str | None
    sic_description: str | None
    market_cap: int | None
    market_cap_currency: str
    market_cap_source: str | None
    universe_reason: str
    universe_reason_label: str
    is_active: bool


class FilingListItem(BaseModel):
    id: int
    company_id: int
    company_name: str
    ticker: str | None
    accession_number: str
    form_type: str
    normalized_form_type: str
    filed_at: datetime
    title: str | None
    importance_score: float
    market_cap_score: float
    impact_score: float
    composite_score: float
    score_explanation: dict[str, Any] = Field(default_factory=dict)
    summary_status: str = "pending"
    summary_tier: str = "no_ai"
    source_type: str = "official_filing"
    event_type: str | None = None
    priority_reason: str = ""
    is_official_source: bool = True
    dedupe_group_id: str | None = None
    freshness_bucket: str = "stale"
    summary: str = ""
    original_document_url: str
    pdf_download_url: str | None = None


class FilingDetail(FilingListItem):
    parsed_sections: dict[str, str] = Field(default_factory=dict)
    key_takeaways: list[str] = Field(default_factory=list)
    material_changes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    opportunity_flags: list[str] = Field(default_factory=list)
    evidence_sections: list[str] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    prior_comparable_filing_id: int | None = None
    prior_comparable_filing_url: str | None = None
    diff_json: dict = Field(default_factory=dict)
    diff_status: str = "pending"
    related_news: list[NewsItemResponse] = Field(default_factory=list)


class NewsItemResponse(BaseModel):
    id: int
    source_name: str
    title: str
    canonical_url: str
    excerpt: str | None
    published_at: datetime
    mentioned_companies: list[str] = Field(default_factory=list)
    company_tag_ids: list[int] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    importance_score: float
    market_cap_score: float
    composite_score: float
    score_explanation: dict[str, Any] = Field(default_factory=dict)
    summary_status: str = "pending"
    summary_tier: str = "no_ai"
    source_type: str = "trade_press"
    event_type: str | None = None
    priority_reason: str = ""
    is_official_source: bool = False
    dedupe_group_id: str | None = None
    freshness_bucket: str = "stale"
    summary: str = ""
    key_takeaways: list[str] = Field(default_factory=list)


class CompanyTrend(BaseModel):
    direction: str = "insufficient_data"
    trend_score: float = 0.0
    risk_trend: str = "stable"
    opportunity_trend: str = "stable"
    filings_analyzed: int = 0


class CompanyDetailResponse(CompanyResponse):
    market_cap_updated_at: datetime | None = None
    filings_count: int = 0
    news_count: int = 0
    recent_filings: list[FilingListItem] = Field(default_factory=list)
    recent_news: list[NewsItemResponse] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    latest_filing: FilingListItem | None = None
    latest_news: NewsItemResponse | None = None
    latest_trial: dict[str, Any] | None = None
    business_summary: str = ""
    change_summary: list[str] = Field(default_factory=list)
    catalyst_summary: list[str] = Field(default_factory=list)
    catalysts: list[TimelineEvent] = Field(default_factory=list)
    trend: CompanyTrend | dict = Field(default_factory=dict)
    pipeline: dict = Field(default_factory=dict)


class DigestResponse(BaseModel):
    id: int
    digest_type: str
    title: str
    window_start: datetime
    window_end: datetime
    published_at: datetime
    narrative_summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class DashboardResponse(BaseModel):
    latest_filings: list[FilingListItem] = Field(default_factory=list)
    latest_news: list[NewsItemResponse] = Field(default_factory=list)
    important_filings: list[FilingListItem] = Field(default_factory=list)
    important_news: list[NewsItemResponse] = Field(default_factory=list)
    top_filings: list[FilingListItem] = Field(default_factory=list)
    top_news: list[NewsItemResponse] = Field(default_factory=list)
    watchlist_highlights: list[WatchlistHighlight] = Field(default_factory=list)
    upcoming_regulatory_events: list[TimelineEvent] = Field(default_factory=list)
    recent_trials: list[dict[str, Any]] = Field(default_factory=list)
    latest_digest: DigestResponse | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    ai_budget: SummaryBudgetOverview = Field(default_factory=SummaryBudgetOverview)
    queue_counts: dict[str, int] = Field(default_factory=dict)


class TimelineEvent(BaseModel):
    id: str
    item_type: str
    item_id: int
    occurred_at: datetime
    title: str
    summary: str = ""
    company_ids: list[int] = Field(default_factory=list)
    company_names: list[str] = Field(default_factory=list)
    href: str | None = None
    external_url: str | None = None
    source_type: str = ""
    event_type: str | None = None
    priority_reason: str = ""
    summary_tier: str = "no_ai"
    is_official_source: bool = False
    freshness_bucket: str = "stale"
    composite_score: float = 0.0
    tags: list[str] = Field(default_factory=list)


class WatchlistResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    preset_key: str | None = None
    company_ids: list[int] = Field(default_factory=list)
    form_types: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WatchlistHighlight(BaseModel):
    watchlist_id: int
    watchlist_name: str
    watchlist_description: str | None = None
    highlights: list[TimelineEvent] = Field(default_factory=list)


class WatchlistBriefingResponse(BaseModel):
    watchlist: WatchlistResponse
    filings: list[FilingListItem] = Field(default_factory=list)
    news: list[NewsItemResponse] = Field(default_factory=list)
    trials: list[dict[str, Any]] = Field(default_factory=list)
    catalysts: list[TimelineEvent] = Field(default_factory=list)
    highlights: list[TimelineEvent] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)


class AdminActionResponse(BaseModel):
    status: str
    message: str
