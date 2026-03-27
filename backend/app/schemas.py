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


class NewsItemResponse(BaseModel):
    id: int
    source_name: str
    title: str
    canonical_url: str
    excerpt: str | None
    published_at: datetime
    mentioned_companies: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    importance_score: float
    market_cap_score: float
    composite_score: float
    score_explanation: dict[str, Any] = Field(default_factory=dict)
    summary_status: str = "pending"
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
    top_filings: list[FilingListItem] = Field(default_factory=list)
    top_news: list[NewsItemResponse] = Field(default_factory=list)
    latest_digest: DigestResponse | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class AdminActionResponse(BaseModel):
    status: str
    message: str
