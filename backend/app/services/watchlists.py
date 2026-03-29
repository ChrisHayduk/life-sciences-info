from __future__ import annotations

import contextlib
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClinicalTrial, Company, Watchlist
from app.services.catalysts import CatalystService
from app.services.clinical_trials import ClinicalTrialsService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.regulatory_events import RegulatoryEventService


def _coerce_timeline_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


class WatchlistService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.filing_service = FilingService(session)
        self.news_service = NewsService(session)
        self.trials_service = ClinicalTrialsService(session)
        self.catalyst_service = CatalystService(session)
        self.regulatory_service = RegulatoryEventService(session)

    def close(self) -> None:
        for service in (
            self.regulatory_service,
            self.trials_service,
            self.news_service,
            self.filing_service,
        ):
            with contextlib.suppress(Exception):
                close = getattr(service, "close", None)
                if callable(close):
                    close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def list_watchlists(self) -> list[Watchlist]:
        return self.session.scalars(select(Watchlist).order_by(Watchlist.created_at.desc())).all()

    def ensure_starter_watchlists(self) -> list[Watchlist]:
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        ranked = sorted(companies, key=lambda company: (company.market_cap or 0), reverse=True)
        large_cap_pharma = [
            company.id
            for company in ranked
            if (company.sic or "") in {"2834", "2836"}
        ][:15]
        smid_cap_biotech = [
            company.id
            for company in ranked
            if (company.sic or "") == "2836" and (company.market_cap or 0) < 10_000_000_000
        ][:20]
        presets = [
            {
                "preset_key": "large-cap-pharma",
                "name": "Large-cap pharma",
                "description": "The largest covered pharma and biologics issuers for broad market awareness.",
                "company_ids": large_cap_pharma,
            },
            {
                "preset_key": "smid-cap-biotech",
                "name": "Smid-cap biotech",
                "description": "Emerging biotech names where catalysts and funding updates move quickly.",
                "company_ids": smid_cap_biotech,
            },
            {
                "preset_key": "my-tracked-names",
                "name": "My tracked names",
                "description": "A personal empty watchlist for manual tracking.",
                "company_ids": [],
            },
        ]

        created_or_existing: list[Watchlist] = []
        for preset in presets:
            watchlist = self.session.scalar(
                select(Watchlist).where(Watchlist.preset_key == preset["preset_key"])
            )
            if watchlist is None:
                watchlist = Watchlist(
                    preset_key=preset["preset_key"],
                    name=preset["name"],
                    description=preset["description"],
                    company_ids=preset["company_ids"],
                )
                self.session.add(watchlist)
                self.session.flush()
            created_or_existing.append(watchlist)

        self.session.commit()
        return created_or_existing

    def add_companies(self, watchlist_id: int, company_ids: list[int]) -> Watchlist:
        watchlist = self.session.get(Watchlist, watchlist_id)
        if not watchlist:
            raise ValueError(f"Unknown watchlist id={watchlist_id}")
        merged = sorted({int(company_id) for company_id in (watchlist.company_ids or []) + company_ids})
        watchlist.company_ids = merged
        self.session.commit()
        self.session.refresh(watchlist)
        return watchlist

    def build_company_timeline(self, company_id: int, limit: int = 30) -> list[dict[str, Any]]:
        company = self.session.get(Company, company_id)
        if not company:
            return []

        filings = self.filing_service.list_filings(company_id=company_id, limit=min(limit, 12))
        news = self.news_service.list_news_for_company(company, limit=min(limit, 12))
        trials = self.trials_service.list_trials(company_id=company_id, limit=min(limit, 12))
        regulatory_events = self.regulatory_service.list_timeline_events(
            company_ids={company_id},
            limit=min(limit, 8),
            include_past_days=90,
            upcoming_days=180,
        )
        timeline = self._merge_timeline(
            company_ids={company_id},
            filings=filings,
            news=news,
            trials=trials,
            regulatory_events=regulatory_events,
            limit=limit,
        )
        return timeline

    def build_watchlist_briefing(self, watchlist_id: int, limit: int = 20) -> dict[str, Any]:
        watchlist = self.session.get(Watchlist, watchlist_id)
        if not watchlist:
            raise ValueError(f"Unknown watchlist id={watchlist_id}")

        company_ids = {int(company_id) for company_id in (watchlist.company_ids or [])}
        filings = self.filing_service.list_filings(
            limit=max(limit, 12),
            watchlist_id=watchlist_id,
            recent_days=120,
            sort_mode="personal",
        )
        news = self.news_service.list_news(
            limit=max(limit, 12),
            watchlist_id=watchlist_id,
            recent_days=30,
            sort_mode="personal",
        )
        trials = self._watchlist_trials(company_ids=company_ids, limit=min(limit, 12))
        regulatory_events = self.regulatory_service.list_timeline_events(
            company_ids=company_ids,
            limit=min(max(limit, 10), 12),
            include_past_days=90,
            upcoming_days=180,
        )
        timeline = self._merge_timeline(
            company_ids=company_ids,
            filings=filings,
            news=news,
            trials=trials,
            regulatory_events=regulatory_events,
            limit=max(limit, 20),
        )
        catalysts = self.catalyst_service.build_watchlist_catalysts(company_ids, limit=min(max(limit, 8), 10))
        highlights = timeline[:6]
        return {
            "watchlist": {
                "id": watchlist.id,
                "name": watchlist.name,
                "description": watchlist.description,
                "preset_key": watchlist.preset_key,
                "company_ids": list(watchlist.company_ids or []),
                "form_types": list(watchlist.form_types or []),
                "topic_tags": list(watchlist.topic_tags or []),
                "created_at": watchlist.created_at,
                "updated_at": watchlist.updated_at,
            },
            "filings": filings[:limit],
            "news": news[:limit],
            "trials": trials[:limit],
            "catalysts": catalysts,
            "highlights": highlights,
            "timeline": timeline[: max(limit, 20)],
        }

    def build_dashboard_highlights(self, limit_watchlists: int = 3, limit_items: int = 3) -> list[dict[str, Any]]:
        highlights: list[dict[str, Any]] = []
        for watchlist in self.list_watchlists()[:limit_watchlists]:
            briefing = self.build_watchlist_briefing(watchlist.id, limit=limit_items)
            highlights.append(
                {
                    "watchlist_id": watchlist.id,
                    "watchlist_name": watchlist.name,
                    "watchlist_description": watchlist.description,
                    "highlights": briefing["highlights"][:limit_items],
                }
            )
        return highlights

    def _watchlist_trials(self, *, company_ids: set[int], limit: int) -> list[dict[str, Any]]:
        if not company_ids:
            return []
        query = (
            select(ClinicalTrial)
            .where(ClinicalTrial.company_id.in_(company_ids))
            .order_by(ClinicalTrial.last_update_date.desc().nullslast(), ClinicalTrial.id.desc())
            .limit(limit)
        )
        trials = self.session.scalars(query).all()
        return [self.trials_service._to_response(trial) for trial in trials]

    def _merge_timeline(
        self,
        *,
        company_ids: set[int],
        filings: list[Any],
        news: list[Any],
        trials: list[dict[str, Any]],
        regulatory_events: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for filing in filings:
            events.append(
                {
                    "id": f"filing-{filing.id}",
                    "item_type": "filing",
                    "item_id": filing.id,
                    "occurred_at": filing.filed_at,
                    "title": filing.title or f"{filing.company_name} {filing.form_type}",
                    "summary": filing.summary or filing.priority_reason,
                    "company_ids": [filing.company_id],
                    "company_names": [filing.company_name],
                    "href": f"/filings/{filing.id}",
                    "external_url": filing.original_document_url,
                    "source_type": filing.source_type,
                    "event_type": filing.event_type,
                    "priority_reason": filing.priority_reason,
                    "summary_tier": filing.summary_tier,
                    "is_official_source": filing.is_official_source,
                    "freshness_bucket": filing.freshness_bucket,
                    "composite_score": filing.composite_score,
                    "tags": [filing.form_type, filing.freshness_bucket],
                }
            )
        for item in news:
            company_names = []
            for company_id in item.company_tag_ids:
                company = self.session.get(Company, company_id)
                if company:
                    company_names.append(company.name)
            events.append(
                {
                    "id": f"news-{item.id}",
                    "item_type": "news",
                    "item_id": item.id,
                    "occurred_at": item.published_at,
                    "title": item.title,
                    "summary": item.summary or item.excerpt or item.priority_reason,
                    "company_ids": item.company_tag_ids,
                    "company_names": company_names,
                    "href": None,
                    "external_url": item.canonical_url,
                    "source_type": item.source_type,
                    "event_type": item.event_type,
                    "priority_reason": item.priority_reason,
                    "summary_tier": item.summary_tier,
                    "is_official_source": item.is_official_source,
                    "freshness_bucket": item.freshness_bucket,
                    "composite_score": item.composite_score,
                    "tags": list(item.topic_tags or []),
                }
            )
        for trial in trials:
            trial_company_ids = [trial["company_id"]] if trial.get("company_id") else []
            if company_ids and trial_company_ids and not set(trial_company_ids).intersection(company_ids):
                continue
            trial_date = trial.get("last_update_date") or trial.get("primary_completion_date") or trial.get("start_date")
            occurred_at = _coerce_timeline_datetime(trial_date)
            tags = [value for value in [trial.get("phase"), trial.get("status")] if value]
            events.append(
                {
                    "id": f"trial-{trial['id']}",
                    "item_type": "trial",
                    "item_id": trial["id"],
                    "occurred_at": occurred_at,
                    "title": trial["title"],
                    "summary": trial.get("status", "Clinical trial update"),
                    "company_ids": trial_company_ids,
                    "company_names": [trial.get("company_name")] if trial.get("company_name") else [],
                    "href": None,
                    "external_url": f"https://clinicaltrials.gov/study/{trial['nct_id']}",
                    "source_type": "trial_registry",
                    "event_type": "clinical-trial",
                    "priority_reason": "recent pipeline update",
                    "summary_tier": "no_ai",
                    "is_official_source": True,
                    "freshness_bucket": "last_90d",
                    "composite_score": 0.0,
                    "tags": tags,
                }
            )

        for event in regulatory_events:
            if company_ids and event.get("company_ids") and not set(event["company_ids"]).intersection(company_ids):
                continue
            events.append(event)

        events.sort(key=lambda event: (event["occurred_at"], event["composite_score"]), reverse=True)
        return events[:limit]
