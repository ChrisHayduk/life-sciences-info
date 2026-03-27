from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Digest, Filing, NewsItem
from app.schemas import DigestResponse
from app.services.summarization import OpenAISummarizer


def weekly_digest_window(reference: datetime | None = None, timezone_name: str = "America/New_York") -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    reference = (reference or datetime.now(tz)).astimezone(tz)
    monday = (reference - timedelta(days=reference.weekday())).date()
    current_week_start = datetime.combine(monday, time.min, tz)
    previous_week_start = current_week_start - timedelta(days=7)
    return previous_week_start, current_week_start


class DigestService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def build_weekly_digest(self, reference: datetime | None = None) -> Digest:
        window_start, window_end = weekly_digest_window(reference, self.settings.timezone)
        existing = self.session.scalar(
            select(Digest).where(
                Digest.digest_type == "weekly",
                Digest.window_start == window_start,
                Digest.window_end == window_end,
            )
        )
        if existing:
            return existing

        filings = self.session.scalars(
            select(Filing)
            .where(Filing.filed_at >= window_start, Filing.filed_at < window_end)
            .order_by(Filing.composite_score.desc())
            .limit(10)
        ).all()
        news_items = self.session.scalars(
            select(NewsItem)
            .where(NewsItem.published_at >= window_start, NewsItem.published_at < window_end)
            .order_by(NewsItem.composite_score.desc())
            .limit(10)
        ).all()

        # Build summaries for AI digest generation
        filing_summaries = []
        for f in filings:
            summary = (f.summary_json or {}).get("summary", "")
            company = self.session.get(Filing, f.id)  # Already have the filing
            filing_summaries.append({
                "form_type": f.form_type,
                "company": f.title or "Unknown",
                "summary": summary,
                "score": f"{f.composite_score:.1f}",
            })
        news_summaries = []
        for n in news_items:
            summary = (n.summary_json or {}).get("summary", "")
            news_summaries.append({
                "source": n.source_name,
                "title": n.title,
                "summary": summary,
            })

        window_label = f"{window_start.date()} to {(window_end - timedelta(days=1)).date()}"
        summarizer = OpenAISummarizer()
        narrative_summary = summarizer.summarize_digest(
            window_label=window_label,
            filing_summaries=filing_summaries,
            news_summaries=news_summaries,
        )

        digest = Digest(
            digest_type="weekly",
            title=f"Weekly Life Sciences Digest: {window_start.date()} to {window_end.date() - timedelta(days=1)}",
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

    def list_digests(self, limit: int = 20) -> list[DigestResponse]:
        digests = self.session.scalars(select(Digest).order_by(Digest.window_start.desc()).limit(limit)).all()
        return [DigestResponse.model_validate(digest, from_attributes=True) for digest in digests]

    def get_digest(self, digest_id: int) -> DigestResponse | None:
        digest = self.session.get(Digest, digest_id)
        if not digest:
            return None
        return DigestResponse.model_validate(digest, from_attributes=True)

