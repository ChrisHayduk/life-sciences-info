from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SummaryUsage

BASE_BUDGET_KINDS = {"filing", "news", "override", "diff", "digest"}
TIER_COUNT_KINDS = {"filing_full_ai", "filing_short_ai", "news_full_ai", "news_short_ai"}
SUPPORTED_KINDS = BASE_BUDGET_KINDS | TIER_COUNT_KINDS


class SummaryBudgetService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def remaining(self, kind: str) -> int:
        limit = self._limit_for_kind(kind)
        used = self.used_today(kind)
        return max(limit - used, 0)

    def used_today(self, kind: str) -> int:
        usage = self._usage_row(kind=kind, usage_date=self._today_local_date())
        return usage.count if usage else 0

    def budget_usd_for_kind(self, kind: str) -> float:
        if kind == "filing":
            return self.settings.daily_ai_budget_usd * self.settings.ai_budget_filing_share
        if kind == "news":
            return self.settings.daily_ai_budget_usd * self.settings.ai_budget_news_share
        if kind == "diff":
            return self.settings.daily_ai_budget_usd * self.settings.ai_budget_diff_share
        if kind == "override":
            return self.settings.daily_ai_budget_usd * self.settings.ai_budget_override_share
        if kind == "digest":
            return self.settings.daily_ai_budget_usd * self.settings.ai_budget_digest_share
        raise ValueError(f"Unsupported dollar-budget kind: {kind}")

    def used_cost_today(self, kind: str) -> float:
        usage = self._usage_row(kind=kind, usage_date=self._today_local_date())
        return float(usage.estimated_cost_usd if usage else 0.0)

    def remaining_usd(self, kind: str) -> float:
        return max(self.budget_usd_for_kind(kind) - self.used_cost_today(kind), 0.0)

    def has_capacity(self, kind: str) -> bool:
        if kind in BASE_BUDGET_KINDS:
            return self.remaining(kind) > 0 and self.remaining_usd(kind) > 0
        return self.remaining(kind) > 0

    def record(
        self,
        kind: str,
        count: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        *,
        reasoning_tokens: int = 0,
        cached_input_tokens: int = 0,
        model: str | None = None,
    ) -> None:
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported summary budget kind: {kind}")
        if (
            count == 0
            and prompt_tokens == 0
            and completion_tokens == 0
            and reasoning_tokens == 0
            and cached_input_tokens == 0
            and estimated_cost_usd == 0.0
        ):
            return

        usage = self._usage_row(kind=kind, usage_date=self._today_local_date())
        if usage is None:
            usage = SummaryUsage(usage_date=self._today_local_date(), kind=kind, count=0)
            self.session.add(usage)
            self.session.flush()

        usage.count += count
        usage.prompt_tokens += prompt_tokens
        usage.completion_tokens += completion_tokens
        usage.reasoning_tokens += reasoning_tokens
        usage.cached_input_tokens += cached_input_tokens
        usage.estimated_cost_usd += estimated_cost_usd

        if model:
            breakdown = dict(usage.model_breakdown or {})
            current = dict(breakdown.get(model) or {})
            current["count"] = int(current.get("count") or 0) + count
            current["prompt_tokens"] = int(current.get("prompt_tokens") or 0) + prompt_tokens
            current["completion_tokens"] = int(current.get("completion_tokens") or 0) + completion_tokens
            current["reasoning_tokens"] = int(current.get("reasoning_tokens") or 0) + reasoning_tokens
            current["cached_input_tokens"] = int(current.get("cached_input_tokens") or 0) + cached_input_tokens
            current["estimated_cost_usd"] = float(current.get("estimated_cost_usd") or 0.0) + estimated_cost_usd
            breakdown[model] = current
            usage.model_breakdown = breakdown

        self.session.flush()

    def snapshot(self, kind: str) -> dict[str, Any]:
        if kind not in BASE_BUDGET_KINDS:
            raise ValueError(f"Unsupported snapshot kind: {kind}")
        return {
            "used": self.used_today(kind),
            "limit": self._limit_for_kind(kind),
            "remaining": self.remaining(kind),
            "used_usd": round(self.used_cost_today(kind), 4),
            "limit_usd": round(self.budget_usd_for_kind(kind), 4),
            "remaining_usd": round(self.remaining_usd(kind), 4),
        }

    def rows_since(self, days: int) -> list[SummaryUsage]:
        cutoff = self._today_local_date() - timedelta(days=max(days - 1, 0))
        return self.session.scalars(
            select(SummaryUsage)
            .where(SummaryUsage.usage_date >= cutoff)
            .order_by(SummaryUsage.usage_date.desc(), SummaryUsage.kind.asc())
        ).all()

    def spend_by_model_since(self, days: int) -> dict[str, dict[str, float | int]]:
        totals: dict[str, dict[str, float | int]] = {}
        for row in self.rows_since(days):
            for model, payload in (row.model_breakdown or {}).items():
                current = totals.setdefault(
                    model,
                    {
                        "count": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "cached_input_tokens": 0,
                        "estimated_cost_usd": 0.0,
                    },
                )
                current["count"] = int(current["count"]) + int(payload.get("count") or 0)
                current["prompt_tokens"] = int(current["prompt_tokens"]) + int(payload.get("prompt_tokens") or 0)
                current["completion_tokens"] = int(current["completion_tokens"]) + int(payload.get("completion_tokens") or 0)
                current["reasoning_tokens"] = int(current["reasoning_tokens"]) + int(payload.get("reasoning_tokens") or 0)
                current["cached_input_tokens"] = int(current["cached_input_tokens"]) + int(payload.get("cached_input_tokens") or 0)
                current["estimated_cost_usd"] = float(current["estimated_cost_usd"]) + float(payload.get("estimated_cost_usd") or 0.0)
        return totals

    def _usage_row(self, *, kind: str, usage_date: date) -> SummaryUsage | None:
        return self.session.scalar(
            select(SummaryUsage).where(
                SummaryUsage.usage_date == usage_date,
                SummaryUsage.kind == kind,
            )
        )

    def _limit_for_kind(self, kind: str) -> int:
        if kind == "filing":
            return self.settings.max_filing_summaries_per_day
        if kind == "news":
            return self.settings.max_news_summaries_per_day
        if kind == "override":
            return self.settings.max_override_summaries_per_day
        if kind == "diff":
            return self.settings.max_filing_diffs_per_day
        if kind == "digest":
            return self.settings.max_digest_generations_per_day
        if kind == "filing_full_ai":
            return self.settings.max_filing_full_ai_per_day
        if kind == "filing_short_ai":
            return self.settings.max_filing_short_ai_per_day
        if kind == "news_full_ai":
            return self.settings.max_news_full_ai_per_day
        if kind == "news_short_ai":
            return self.settings.max_news_short_ai_per_day
        raise ValueError(f"Unsupported summary budget kind: {kind}")

    def _today_local_date(self) -> date:
        tz = ZoneInfo(self.settings.timezone)
        return datetime.now(tz).date()
