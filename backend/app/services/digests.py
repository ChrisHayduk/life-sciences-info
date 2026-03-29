from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Digest, Filing, NewsItem
from app.schemas import DigestResponse
from app.services.summarization import OpenAISummarizer, UsageMetrics
from app.services.summary_budget import SummaryBudgetService


def weekly_digest_window(reference: datetime | None = None, timezone_name: str = "America/New_York") -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    reference = (reference or datetime.now(tz)).astimezone(tz)
    monday = (reference - timedelta(days=reference.weekday())).date()
    current_week_start = datetime.combine(monday, time.min, tz)
    previous_week_start = current_week_start - timedelta(days=7)
    return previous_week_start, current_week_start


def daily_digest_window(reference: datetime | None = None, timezone_name: str = "America/New_York") -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    reference = (reference or datetime.now(tz)).astimezone(tz)
    current_day_start = datetime.combine(reference.date(), time.min, tz)
    previous_day_start = current_day_start - timedelta(days=1)
    return previous_day_start, current_day_start


class DigestService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.summarizer = OpenAISummarizer()

    def build_weekly_digest(self, reference: datetime | None = None) -> Digest:
        window_start, window_end = weekly_digest_window(reference, self.settings.timezone)
        title = f"Weekly Life Sciences Digest: {window_start.date()} to {window_end.date() - timedelta(days=1)}"
        window_label = f"{window_start.date()} to {(window_end - timedelta(days=1)).date()}"
        return self._build_digest(
            digest_type="weekly",
            window_start=window_start,
            window_end=window_end,
            title=title,
            window_label=window_label,
            filing_limit=10,
            news_limit=10,
        )

    def build_daily_digest(self, reference: datetime | None = None) -> Digest:
        window_start, window_end = daily_digest_window(reference, self.settings.timezone)
        title = f"Daily Life Sciences Briefing: {window_start.date()}"
        window_label = f"{window_start.date()}"
        return self._build_digest(
            digest_type="daily",
            window_start=window_start,
            window_end=window_end,
            title=title,
            window_label=window_label,
            filing_limit=8,
            news_limit=8,
        )

    def list_digests(self, limit: int = 20) -> list[DigestResponse]:
        digests = self.session.scalars(select(Digest).order_by(Digest.window_start.desc()).limit(limit)).all()
        return [DigestResponse.model_validate(digest, from_attributes=True) for digest in digests]

    def get_digest(self, digest_id: int) -> DigestResponse | None:
        digest = self.session.get(Digest, digest_id)
        if not digest:
            return None
        return DigestResponse.model_validate(digest, from_attributes=True)

    def _build_digest(
        self,
        *,
        digest_type: str,
        window_start: datetime,
        window_end: datetime,
        title: str,
        window_label: str,
        filing_limit: int,
        news_limit: int,
    ) -> Digest:
        existing = self.session.scalar(
            select(Digest).where(
                Digest.digest_type == digest_type,
                Digest.window_start == window_start,
                Digest.window_end == window_end,
            )
        )
        if existing:
            return existing

        candidate_filings = self.session.scalars(
            select(Filing)
            .where(
                Filing.filed_at >= window_start,
                Filing.filed_at < window_end,
            )
            .order_by(Filing.composite_score.desc())
            .limit(max(filing_limit * 3, filing_limit))
        ).all()
        filings = [filing for filing in candidate_filings if self._has_summary(filing)][:filing_limit]

        candidate_news = self.session.scalars(
            select(NewsItem)
            .where(
                NewsItem.published_at >= window_start,
                NewsItem.published_at < window_end,
            )
            .order_by(NewsItem.composite_score.desc())
            .limit(max(news_limit * 3, news_limit))
        ).all()
        news_items = [item for item in candidate_news if self._has_summary(item)][:news_limit]

        filing_summaries = [
            {
                "form_type": filing.form_type,
                "company": (self.session.get(Company, filing.company_id).name if filing.company_id else "Unknown"),
                "summary": (filing.summary_json or {}).get("summary", ""),
                "score": f"{filing.composite_score:.1f}",
            }
            for filing in filings
        ]
        news_summaries = [
            {
                "source": item.source_name,
                "title": item.title,
                "summary": (item.summary_json or {}).get("summary", ""),
            }
            for item in news_items
        ]

        narrative_summary, usage = self._generate_digest_narrative(
            digest_type=digest_type,
            window_label=window_label,
            filing_summaries=filing_summaries,
            news_summaries=news_summaries,
        )

        digest = Digest(
            digest_type=digest_type,
            title=title,
            window_start=window_start,
            window_end=window_end,
            narrative_summary=narrative_summary,
            payload={
                "filings": [
                    {
                        "id": filing.id,
                        "title": filing.title,
                        "company_id": filing.company_id,
                        "company_name": (self.session.get(Company, filing.company_id).name if filing.company_id else None),
                        "score": filing.composite_score,
                    }
                    for filing in filings
                ],
                "news": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "source_name": item.source_name,
                        "mentioned_companies": item.mentioned_companies or [],
                        "company_tag_ids": item.company_tag_ids or [],
                        "score": item.composite_score,
                    }
                    for item in news_items
                ],
            },
        )
        self.session.add(digest)
        self.session.commit()
        self.session.refresh(digest)
        return digest

    def _generate_digest_narrative(
        self,
        *,
        digest_type: str,
        window_label: str,
        filing_summaries: list[dict[str, str]],
        news_summaries: list[dict[str, str]],
    ) -> tuple[str, UsageMetrics]:
        budget_service = SummaryBudgetService(self.session)
        model = self.settings.openai_model_digest
        prompt_cache_key = f"digest:{digest_type}:{self.settings.summary_prompt_version}:{model}"

        if self.settings.openai_api_key and budget_service.has_capacity("digest"):
            if hasattr(self.summarizer, "summarize_digest_with_usage"):
                result = self.summarizer.summarize_digest_with_usage(
                    window_label=window_label,
                    filing_summaries=filing_summaries,
                    news_summaries=news_summaries,
                    model=model,
                    prompt_cache_key=prompt_cache_key,
                )
            else:
                result = type(
                    "DigestResult",
                    (),
                    {
                        "text": self.summarizer.summarize_digest(
                            window_label=window_label,
                            filing_summaries=filing_summaries,
                            news_summaries=news_summaries,
                        ),
                        "usage": UsageMetrics(model=model),
                    },
                )()
            budget_service.record(
                "digest",
                1,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                reasoning_tokens=result.usage.reasoning_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
                estimated_cost_usd=result.usage.estimated_cost_usd,
                model=result.usage.model,
            )
            return result.text, result.usage

        return self.summarizer._fallback_digest_narrative(filing_summaries, news_summaries), UsageMetrics(model="fallback-local")

    @staticmethod
    def _has_summary(item: Filing | NewsItem) -> bool:
        return bool(
            item.summary_status == "complete"
            or (item.summary_json or {}).get("summary")
        )
