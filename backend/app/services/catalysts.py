from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ClinicalTrial, Company, Filing, NewsItem, RegulatoryEvent
from app.services.ranking import freshness_bucket, personal_relevance_score

RECENT_EVENT_TYPES = {
    "approval",
    "regulatory",
    "earnings",
    "results-of-operations",
    "acquisition",
    "acquisition-disposition",
    "material-agreement",
    "leadership-change",
    "financing",
    "clinical-data",
}


class CatalystService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def build_company_catalysts(self, company_id: int, limit: int = 6) -> list[dict[str, Any]]:
        company = self.session.get(Company, company_id)
        if not company:
            return []
        return self._build_catalysts({company_id}, limit=limit)

    def build_watchlist_catalysts(self, company_ids: set[int], limit: int = 8) -> list[dict[str, Any]]:
        return self._build_catalysts(company_ids, limit=limit)

    def summarize_catalysts(self, catalysts: list[dict[str, Any]], limit: int = 4) -> list[str]:
        summaries: list[str] = []
        for catalyst in catalysts[:limit]:
            if catalyst["item_type"] == "trial":
                if "upcoming" in catalyst.get("tags", []):
                    summaries.append(f"{catalyst['title']} on {self._display_date(catalyst['occurred_at'])}")
                else:
                    summaries.append(f"Clinical trial signal: {catalyst['title']}")
            elif catalyst["item_type"] == "filing":
                summaries.append(f"{catalyst['title']} ({self._display_date(catalyst['occurred_at'])})")
            elif catalyst["item_type"] == "regulatory":
                summaries.append(f"FDA catalyst: {catalyst['title']} ({self._display_date(catalyst['occurred_at'])})")
            else:
                summaries.append(catalyst["title"])
        return summaries

    def _build_catalysts(self, company_ids: set[int], *, limit: int) -> list[dict[str, Any]]:
        if not company_ids:
            return []

        recent_cutoff = datetime.now(UTC) - timedelta(days=self.settings.recent_catalyst_days)
        today = datetime.now(UTC).date()
        lookahead_end = today + timedelta(days=self.settings.catalyst_lookahead_days)

        catalysts: list[dict[str, Any]] = []
        catalysts.extend(self._recent_filing_catalysts(company_ids, recent_cutoff))
        catalysts.extend(self._recent_news_catalysts(company_ids, recent_cutoff))
        catalysts.extend(self._regulatory_catalysts(company_ids, recent_cutoff=recent_cutoff, lookahead_end=lookahead_end))
        catalysts.extend(self._trial_catalysts(company_ids, today=today, lookahead_end=lookahead_end, recent_cutoff=recent_cutoff))

        deduped: dict[str, dict[str, Any]] = {}
        for catalyst in catalysts:
            key = catalyst["id"]
            if key not in deduped:
                deduped[key] = catalyst
                continue
            existing = deduped[key]
            if catalyst["composite_score"] > existing["composite_score"]:
                deduped[key] = catalyst

        now = datetime.now(UTC)
        ordered = sorted(
            deduped.values(),
            key=lambda item: self._sort_key(item, now=now),
        )
        return ordered[:limit]

    def _recent_filing_catalysts(self, company_ids: set[int], recent_cutoff: datetime) -> list[dict[str, Any]]:
        filings = self.session.scalars(
            select(Filing)
            .where(Filing.company_id.in_(company_ids), Filing.filed_at >= recent_cutoff)
            .order_by(Filing.filed_at.desc(), Filing.composite_score.desc())
        ).all()

        items: list[dict[str, Any]] = []
        for filing in filings:
            if filing.normalized_form_type not in {"8-K", "6-K"} and filing.event_type not in RECENT_EVENT_TYPES:
                continue
            company = self.session.get(Company, filing.company_id)
            if not company:
                continue
            summary = (filing.summary_json or {}).get("summary") or filing.priority_reason or filing.title or ""
            items.append(
                {
                    "id": f"catalyst-filing-{filing.id}",
                    "item_type": "filing",
                    "item_id": filing.id,
                    "occurred_at": filing.filed_at,
                    "title": filing.title or f"{company.name} {filing.form_type}",
                    "summary": summary,
                    "company_ids": [company.id],
                    "company_names": [company.name],
                    "href": f"/filings/{filing.id}",
                    "external_url": filing.original_document_url,
                    "source_type": filing.source_type or "official_filing",
                    "event_type": filing.event_type,
                    "priority_reason": filing.priority_reason or "recent official filing",
                    "summary_tier": filing.summary_tier or "no_ai",
                    "is_official_source": bool(filing.is_official_source),
                    "freshness_bucket": filing.freshness_bucket or freshness_bucket(filing.filed_at),
                    "composite_score": float(filing.composite_score or 0.0),
                    "tags": [filing.form_type, "recent"],
                }
            )
        return items

    def _regulatory_catalysts(
        self,
        company_ids: set[int],
        *,
        recent_cutoff: datetime,
        lookahead_end: date,
    ) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(RegulatoryEvent)
            .order_by(RegulatoryEvent.starts_at.asc(), RegulatoryEvent.composite_score.desc())
        ).all()
        companies = {
            company.id: company
            for company in self.session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
        }
        lookahead_dt = datetime.combine(lookahead_end, time.max, tzinfo=UTC)

        items: list[dict[str, Any]] = []
        for event in rows:
            matched_ids = sorted(set(event.company_tag_ids or []).intersection(company_ids))
            if not matched_ids:
                continue
            if event.starts_at < recent_cutoff or event.starts_at > lookahead_dt:
                continue
            company_names = [companies[company_id].name for company_id in matched_ids if company_id in companies]
            items.append(
                {
                    "id": f"catalyst-regulatory-{event.id}",
                    "item_type": "regulatory",
                    "item_id": event.id,
                    "occurred_at": event.starts_at,
                    "title": event.title,
                    "summary": event.summary_text or event.priority_reason or "",
                    "company_ids": matched_ids,
                    "company_names": company_names,
                    "href": None,
                    "external_url": event.canonical_url,
                    "source_type": event.source_type or "regulator",
                    "event_type": event.event_type,
                    "priority_reason": event.priority_reason or "upcoming FDA committee date",
                    "summary_tier": "no_ai",
                    "is_official_source": bool(event.is_official_source),
                    "freshness_bucket": event.freshness_bucket or freshness_bucket(event.starts_at),
                    "composite_score": float(event.composite_score or 0.0),
                    "tags": list(event.topic_tags or []),
                }
            )
        return items

    def _recent_news_catalysts(self, company_ids: set[int], recent_cutoff: datetime) -> list[dict[str, Any]]:
        news_items = self.session.scalars(
            select(NewsItem)
            .where(NewsItem.published_at >= recent_cutoff)
            .order_by(NewsItem.published_at.desc(), NewsItem.composite_score.desc())
        ).all()
        companies = {
            company.id: company
            for company in self.session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
        }

        items: list[dict[str, Any]] = []
        for news_item in news_items:
            tagged_ids = set(news_item.company_tag_ids or [])
            if not tagged_ids.intersection(company_ids):
                continue
            if not news_item.is_official_source and news_item.event_type not in RECENT_EVENT_TYPES:
                continue
            matched_ids = sorted(tagged_ids.intersection(company_ids))
            company_names = [companies[company_id].name for company_id in matched_ids if company_id in companies]
            items.append(
                {
                    "id": f"catalyst-news-{news_item.id}",
                    "item_type": "news",
                    "item_id": news_item.id,
                    "occurred_at": news_item.published_at,
                    "title": news_item.title,
                    "summary": (news_item.summary_json or {}).get("summary") or news_item.excerpt or news_item.priority_reason or "",
                    "company_ids": matched_ids,
                    "company_names": company_names,
                    "href": None,
                    "external_url": news_item.canonical_url,
                    "source_type": news_item.source_type or "trade_press",
                    "event_type": news_item.event_type,
                    "priority_reason": news_item.priority_reason or "recent news catalyst",
                    "summary_tier": news_item.summary_tier or "no_ai",
                    "is_official_source": bool(news_item.is_official_source),
                    "freshness_bucket": news_item.freshness_bucket or freshness_bucket(news_item.published_at),
                    "composite_score": float(news_item.composite_score or 0.0),
                    "tags": list(news_item.topic_tags or []) + ["recent"],
                }
            )
        return items

    def _trial_catalysts(
        self,
        company_ids: set[int],
        *,
        today: date,
        lookahead_end: date,
        recent_cutoff: datetime,
    ) -> list[dict[str, Any]]:
        trials = self.session.scalars(
            select(ClinicalTrial)
            .where(ClinicalTrial.company_id.in_(company_ids))
            .order_by(ClinicalTrial.primary_completion_date.asc().nullslast(), ClinicalTrial.last_update_date.desc().nullslast())
        ).all()
        companies = {
            company.id: company
            for company in self.session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
        }

        items: list[dict[str, Any]] = []
        recent_cutoff_date = recent_cutoff.date()
        for trial in trials:
            company = companies.get(trial.company_id or -1)
            if not company:
                continue

            upcoming_date = trial.primary_completion_date
            last_update_date = trial.last_update_date

            if upcoming_date and today <= upcoming_date <= lookahead_end:
                occurred_at = datetime.combine(upcoming_date, time.min, tzinfo=UTC)
                items.append(
                    {
                        "id": f"catalyst-trial-upcoming-{trial.id}",
                        "item_type": "trial",
                        "item_id": trial.id,
                        "occurred_at": occurred_at,
                        "title": f"{company.name}: primary completion expected for {trial.title}",
                        "summary": f"{trial.phase or 'Clinical'} program with status {trial.status}.",
                        "company_ids": [company.id],
                        "company_names": [company.name],
                        "href": None,
                        "external_url": f"https://clinicaltrials.gov/study/{trial.nct_id}",
                        "source_type": "trial_registry",
                        "event_type": "upcoming-trial-readout",
                        "priority_reason": "upcoming primary completion date",
                        "summary_tier": "no_ai",
                        "is_official_source": True,
                        "freshness_bucket": "upcoming",
                        "composite_score": self._trial_priority(trial, upcoming=True),
                        "tags": [trial.phase or "trial", trial.status, "upcoming"],
                    }
                )
            elif last_update_date and last_update_date >= recent_cutoff_date:
                occurred_at = datetime.combine(last_update_date, time.min, tzinfo=UTC)
                items.append(
                    {
                        "id": f"catalyst-trial-recent-{trial.id}",
                        "item_type": "trial",
                        "item_id": trial.id,
                        "occurred_at": occurred_at,
                        "title": f"{company.name}: trial registry update for {trial.title}",
                        "summary": f"{trial.phase or 'Clinical'} program currently {trial.status}.",
                        "company_ids": [company.id],
                        "company_names": [company.name],
                        "href": None,
                        "external_url": f"https://clinicaltrials.gov/study/{trial.nct_id}",
                        "source_type": "trial_registry",
                        "event_type": "clinical-trial",
                        "priority_reason": "recent trial registry update",
                        "summary_tier": "no_ai",
                        "is_official_source": True,
                        "freshness_bucket": freshness_bucket(occurred_at),
                        "composite_score": self._trial_priority(trial, upcoming=False),
                        "tags": [trial.phase or "trial", trial.status, "recent"],
                    }
                )
        return items

    @staticmethod
    def _trial_priority(trial: ClinicalTrial, *, upcoming: bool) -> float:
        phase_bonus_map = {
            "Phase 3": 25.0,
            "Phase 2/Phase 3": 22.0,
            "Phase 2": 18.0,
            "Phase 1/Phase 2": 14.0,
            "Phase 1": 10.0,
        }
        base = 70.0 if upcoming else 55.0
        return base + phase_bonus_map.get(trial.phase or "", 8.0)

    def _sort_key(self, item: dict[str, Any], *, now: datetime) -> tuple[float, float, float]:
        occurred_at: datetime = item["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        is_upcoming = "upcoming" in item.get("tags", []) and occurred_at >= now
        if is_upcoming:
            hours_until = max((occurred_at - now).total_seconds() / 3600.0, 0.0)
            return (0.0, hours_until, -(item.get("composite_score") or 0.0))

        relevance = personal_relevance_score(
            composite_score=float(item.get("composite_score") or 0.0),
            published_at=occurred_at,
            is_official_source=bool(item.get("is_official_source")),
            watchlist_match=False,
            event_type=item.get("event_type"),
            now=now,
        )
        return (1.0, -relevance, -occurred_at.timestamp())

    @staticmethod
    def _display_date(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.strftime("%b %d, %Y").replace(" 0", " ")
