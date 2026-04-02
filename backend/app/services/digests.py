from __future__ import annotations

import contextlib
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Digest, Filing, NewsItem
from app.schemas import DigestResponse
from app.services.digest_email import DigestEmailService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.summarization import OpenAISummarizer, UsageMetrics
from app.services.summary_budget import SummaryBudgetService

logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        session: Session,
        email_sender: DigestEmailService | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.summarizer = OpenAISummarizer()
        self._owns_summarizer = True
        self.email_sender = email_sender or DigestEmailService(self.settings)

    def close(self) -> None:
        if self._owns_summarizer:
            with contextlib.suppress(Exception):
                self.summarizer.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

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

    def send_daily_digest_email(
        self,
        *,
        reference: datetime | None = None,
        force: bool = False,
    ) -> dict[str, int | bool | str | None]:
        window_start, window_end = daily_digest_window(reference, self.settings.timezone)
        existing = self.session.scalar(
            select(Digest).where(
                Digest.digest_type == "daily",
                Digest.window_start == window_start,
                Digest.window_end == window_end,
            )
        )
        built = existing is None
        digest = existing or self.build_daily_digest(reference=reference)
        delivery_status = digest.email_delivery_status or "pending"

        if delivery_status == "sent" and not force:
            logger.info("Daily digest %s already emailed; skipping resend", digest.id)
            return {
                "digest_id": digest.id,
                "title": digest.title,
                "built": built,
                "delivery_status": "already_sent",
                "error": None,
            }

        if not self._has_email_content(digest):
            digest.email_delivery_status = "skipped"
            digest.email_last_attempted_at = datetime.now(ZoneInfo(self.settings.timezone))
            digest.email_delivery_error = None
            self.session.commit()
            logger.info("Daily digest %s has no filing/news items; email skipped", digest.id)
            return {
                "digest_id": digest.id,
                "title": digest.title,
                "built": built,
                "delivery_status": "skipped",
                "error": None,
            }

        if not self.email_sender.is_enabled() or not self.email_sender.is_configured():
            logger.info("Daily digest %s built but email delivery is disabled or not configured", digest.id)
            return {
                "digest_id": digest.id,
                "title": digest.title,
                "built": built,
                "delivery_status": "disabled",
                "error": None,
            }

        attempted_at = datetime.now(ZoneInfo(self.settings.timezone))
        digest.email_last_attempted_at = attempted_at
        digest.email_delivery_error = None
        try:
            self.email_sender.send_daily_digest(digest)
        except Exception as exc:
            digest.email_delivery_status = "failed"
            digest.email_delivery_error = str(exc)
            self.session.commit()
            logger.error("Daily digest %s email delivery failed: %s", digest.id, exc)
            return {
                "digest_id": digest.id,
                "title": digest.title,
                "built": built,
                "delivery_status": "failed",
                "error": str(exc),
            }

        digest.email_delivery_status = "sent"
        digest.email_delivered_at = attempted_at
        digest.email_delivery_error = None
        self.session.commit()
        logger.info("Daily digest %s emailed to %s", digest.id, self.settings.digest_email_to)
        return {
            "digest_id": digest.id,
            "title": digest.title,
            "built": built,
            "delivery_status": "sent",
            "error": None,
        }

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
            if existing.email_delivery_status is None:
                existing.email_delivery_status = "pending" if digest_type == "daily" else "skipped"
                self.session.commit()
            return existing

        self._proactively_summarize_digest_candidates(
            window_start=window_start,
            window_end=window_end,
            filing_limit=filing_limit,
            news_limit=news_limit,
        )

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
            email_delivery_status="pending" if digest_type == "daily" else "skipped",
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
                        "canonical_url": item.canonical_url,
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

    def _proactively_summarize_digest_candidates(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        filing_limit: int,
        news_limit: int,
    ) -> None:
        filing_gap = self._digest_candidate_gap(
            model=Filing,
            timestamp_column=Filing.filed_at,
            window_start=window_start,
            window_end=window_end,
            limit=filing_limit,
        )
        news_gap = self._digest_candidate_gap(
            model=NewsItem,
            timestamp_column=NewsItem.published_at,
            window_start=window_start,
            window_end=window_end,
            limit=news_limit,
        )

        if filing_gap > 0:
            filing_service = FilingService(self.session, summarizer=self.summarizer)
            try:
                result = filing_service.summarize_for_digest_window(
                    window_start=window_start,
                    window_end=window_end,
                    limit=filing_gap,
                )
                logger.info("Digest filing catch-up summarized=%s", result.get("summarized", 0))
            finally:
                filing_service.close()

        if news_gap > 0:
            news_service = NewsService(self.session, summarizer=self.summarizer)
            try:
                result = news_service.summarize_for_digest_window(
                    window_start=window_start,
                    window_end=window_end,
                    limit=news_gap,
                )
                logger.info("Digest news catch-up summarized=%s", result.get("summarized", 0))
            finally:
                news_service.close()

    def _digest_candidate_gap(
        self,
        *,
        model: type[Filing] | type[NewsItem],
        timestamp_column,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> int:
        rows = self.session.execute(
            select(model.summary_status, model.summary_json)
            .where(
                timestamp_column >= window_start,
                timestamp_column < window_end,
            )
            .order_by(model.composite_score.desc(), timestamp_column.desc(), model.id.desc())
            .limit(max(limit * 3, limit))
        ).all()
        summarized = sum(1 for row in rows if row.summary_status == "complete" or (row.summary_json or {}).get("summary"))
        pending = len(rows) - summarized
        return min(max(limit - summarized, 0), pending)

    @staticmethod
    def _has_summary(item: Filing | NewsItem) -> bool:
        return bool(
            item.summary_status == "complete"
            or (item.summary_json or {}).get("summary")
        )

    @staticmethod
    def _has_email_content(digest: Digest) -> bool:
        payload = digest.payload or {}
        return bool((payload.get("filings") or []) or (payload.get("news") or []))
