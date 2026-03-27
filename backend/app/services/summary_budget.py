from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SummaryUsage


class SummaryBudgetService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def remaining(self, kind: str) -> int:
        limit = self._limit_for_kind(kind)
        used = self.used_today(kind)
        return max(limit - used, 0)

    def used_today(self, kind: str) -> int:
        usage = self.session.scalar(
            select(SummaryUsage).where(
                SummaryUsage.usage_date == self._today_local_date(),
                SummaryUsage.kind == kind,
            )
        )
        return usage.count if usage else 0

    def record(self, kind: str, count: int) -> None:
        if count <= 0:
            return
        usage = self.session.scalar(
            select(SummaryUsage).where(
                SummaryUsage.usage_date == self._today_local_date(),
                SummaryUsage.kind == kind,
            )
        )
        if usage is None:
            usage = SummaryUsage(usage_date=self._today_local_date(), kind=kind, count=0)
            self.session.add(usage)
            self.session.flush()
        usage.count += count
        self.session.flush()

    def _limit_for_kind(self, kind: str) -> int:
        if kind == "filing":
            return self.settings.max_filing_summaries_per_day
        if kind == "news":
            return self.settings.max_news_summaries_per_day
        raise ValueError(f"Unsupported summary budget kind: {kind}")

    def _today_local_date(self) -> date:
        tz = ZoneInfo(self.settings.timezone)
        return datetime.now(tz).date()
