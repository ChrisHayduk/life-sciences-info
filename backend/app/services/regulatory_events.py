from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, RegulatoryEvent
from app.services.news import NewsService, _clean_html_text
from app.services.ranking import company_market_cap_percentiles, freshness_bucket

FDA_ADVISORY_CALENDAR_URL = "https://www.fda.gov/advisory-committees/advisory-committee-calendar"
FDA_ADVISORY_CALENDAR_JSON_URL = "https://www.fda.gov/datatables-json/advisory-committee-calendar-json"


class RegulatoryEventService:
    def __init__(self, session: Session, http_client: httpx.Client | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=self.settings.source_fetch_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.settings.sec_user_agent},
        )

    def close(self) -> None:
        if self._owns_http_client:
            with contextlib.suppress(Exception):
                self.http_client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def poll_fda_advisory_calendar(self, *, limit: int | None = None) -> dict[str, int]:
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        aliases = NewsService._company_aliases(companies)
        market_caps = company_market_cap_percentiles(self.session)
        rows = self._fetch_calendar_rows(limit=limit)

        inserted = 0
        updated = 0
        tagged = 0
        for row in rows:
            detail = self._fetch_detail(row["canonical_url"])
            combined_text = "\n".join(
                value
                for value in [
                    detail.get("title") or row["title"],
                    detail.get("summary_text") or "",
                    row.get("context_text") or "",
                ]
                if value
            )
            mentioned, company_tag_ids = NewsService._detect_companies(combined_text, aliases)
            if company_tag_ids:
                tagged += 1

            starts_at = detail.get("starts_at") or row["starts_at"]
            ends_at = detail.get("ends_at") or row.get("ends_at")
            event = self.session.scalar(select(RegulatoryEvent).where(RegulatoryEvent.canonical_url == row["canonical_url"]))
            is_new = event is None
            if event is None:
                event = RegulatoryEvent(
                    source_name="FDA Advisory Committee Calendar",
                    title=detail.get("title") or row["title"],
                    canonical_url=row["canonical_url"],
                    starts_at=starts_at,
                )
                self.session.add(event)
            else:
                previous_state = {
                    "title": event.title,
                    "starts_at": event.starts_at,
                    "ends_at": event.ends_at,
                    "committee_name": event.committee_name,
                    "summary_text": event.summary_text,
                    "mentioned_companies": list(event.mentioned_companies or []),
                    "company_tag_ids": list(event.company_tag_ids or []),
                    "priority_reason": event.priority_reason,
                    "importance_score": float(event.importance_score or 0.0),
                    "market_cap_score": float(event.market_cap_score or 0.0),
                    "composite_score": float(event.composite_score or 0.0),
                }

            event.title = detail.get("title") or row["title"]
            event.starts_at = starts_at
            event.ends_at = ends_at
            event.committee_name = detail.get("committee_name") or row.get("committee_name")
            event.summary_text = detail.get("summary_text") or row.get("context_text") or event.summary_text
            event.mentioned_companies = mentioned
            event.company_tag_ids = company_tag_ids
            event.topic_tags = ["regulatory", "advisory-committee"]
            event.source_type = "regulator"
            event.event_type = "fda-advisory-committee"
            event.is_official_source = True
            event.market_cap_score = max((market_caps.get(company_id, 0.0) for company_id in company_tag_ids), default=0.0)
            event.importance_score = self._importance_score(
                title=event.title,
                committee_name=event.committee_name,
                starts_at=event.starts_at,
                market_cap_score=event.market_cap_score,
            )
            event.composite_score = self._composite_score(
                starts_at=event.starts_at,
                market_cap_score=event.market_cap_score,
                importance_score=event.importance_score,
            )
            event.priority_reason = self._priority_reason(
                starts_at=event.starts_at,
                market_cap_score=event.market_cap_score,
                company_tag_ids=company_tag_ids,
            )
            event.freshness_bucket = "upcoming" if event.starts_at >= datetime.now(UTC) else freshness_bucket(event.starts_at)
            event.extra_metadata = {
                **(event.extra_metadata or {}),
                "calendar_url": FDA_ADVISORY_CALENDAR_URL,
                "center": row.get("center"),
                "detail_summary_source": "detail_page" if detail.get("summary_text") else "calendar_page",
            }

            if is_new:
                inserted += 1
            elif previous_state != {
                "title": event.title,
                "starts_at": event.starts_at,
                "ends_at": event.ends_at,
                "committee_name": event.committee_name,
                "summary_text": event.summary_text,
                "mentioned_companies": list(event.mentioned_companies or []),
                "company_tag_ids": list(event.company_tag_ids or []),
                "priority_reason": event.priority_reason,
                "importance_score": float(event.importance_score or 0.0),
                "market_cap_score": float(event.market_cap_score or 0.0),
                "composite_score": float(event.composite_score or 0.0),
            }:
                updated += 1

        self.session.commit()
        return {"scanned": len(rows), "inserted": inserted, "updated": updated, "tagged": tagged}

    def list_events(
        self,
        *,
        company_ids: Iterable[int] | None = None,
        limit: int = 20,
        include_past_days: int | None = None,
        upcoming_days: int | None = None,
    ) -> list[RegulatoryEvent]:
        rows = self.session.scalars(
            select(RegulatoryEvent).order_by(RegulatoryEvent.starts_at.asc(), RegulatoryEvent.composite_score.desc())
        ).all()
        now = datetime.now(UTC)
        target_ids = {int(company_id) for company_id in (company_ids or [])}
        items: list[RegulatoryEvent] = []
        for item in rows:
            if target_ids and not set(item.company_tag_ids or []).intersection(target_ids):
                continue
            if include_past_days is not None and item.starts_at < now - timedelta(days=include_past_days):
                continue
            if upcoming_days is not None and item.starts_at > now + timedelta(days=upcoming_days):
                continue
            items.append(item)
        if company_ids:
            items.sort(key=lambda item: self._timeline_sort_key(item, now=now))
        return items[:limit]

    def list_timeline_events(
        self,
        *,
        company_ids: Iterable[int] | None = None,
        limit: int = 20,
        include_past_days: int | None = None,
        upcoming_days: int | None = None,
    ) -> list[dict[str, Any]]:
        events = self.list_events(
            company_ids=company_ids,
            limit=limit,
            include_past_days=include_past_days,
            upcoming_days=upcoming_days,
        )
        if not events:
            return []

        company_map = {
            company.id: company.name
            for company in self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        }
        return [self._to_timeline_event(item, company_map=company_map) for item in events]

    def _fetch_calendar_rows(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        try:
            response = self.http_client.get(FDA_ADVISORY_CALENDAR_JSON_URL)
            response.raise_for_status()
        except Exception:
            return []

        try:
            payload = response.json()
        except ValueError:
            return []

        raw_rows = payload if isinstance(payload, list) else payload.get("data", [])
        rows: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for raw in raw_rows:
            title_html = raw.get("title") or ""
            title_soup = BeautifulSoup(title_html, "html.parser")
            anchor = title_soup.select_one("a[href]")
            if not anchor:
                continue
            href = anchor.get("href") or ""
            canonical_url = urljoin(FDA_ADVISORY_CALENDAR_URL, href)
            if canonical_url in seen_urls:
                continue
            starts_at = self._parse_datetime(raw.get("field_start_date"))
            if starts_at is None:
                continue
            ends_at = self._parse_datetime(raw.get("field_end_date"))
            title = _clean_html_text(anchor.get_text(" ", strip=True)) or _clean_html_text(title_html)
            rows.append(
                {
                    "title": title,
                    "canonical_url": canonical_url,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "committee_name": self._extract_committee_name(title),
                    "context_text": " ".join(
                        value
                        for value in [
                            title,
                            _clean_html_text(raw.get("field_center")),
                            _clean_html_text(raw.get("field_contributing_office")),
                        ]
                        if value
                    ),
                    "center": _clean_html_text(raw.get("field_center")),
                }
            )
            seen_urls.add(canonical_url)

        rows.sort(key=lambda item: item["starts_at"], reverse=True)
        if limit is not None:
            return rows[:limit]
        return rows

    def _fetch_detail(self, url: str) -> dict[str, Any]:
        try:
            response = self.http_client.get(url)
            response.raise_for_status()
        except Exception:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        title = ""
        for selector in ["h1", "main h1", ".content h1"]:
            element = soup.select_one(selector)
            if element:
                title = _clean_html_text(element.get_text(" ", strip=True))
                break

        main = soup.select_one("main") or soup.select_one("article") or soup
        paragraphs = [_clean_html_text(tag.get_text(" ", strip=True)) for tag in main.find_all("p")]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        summary_text = " ".join(paragraphs[:3])[:900]

        starts_at = None
        time_tag = soup.select_one("time[datetime]")
        if time_tag and time_tag.get("datetime"):
            try:
                starts_at = date_parser.parse(time_tag["datetime"])
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                starts_at = None

        return {
            "title": title,
            "starts_at": starts_at,
            "ends_at": None,
            "committee_name": self._extract_committee_name(title) if title else None,
            "summary_text": summary_text,
        }

    @staticmethod
    def _extract_committee_name(title: str) -> str | None:
        normalized = title.strip()
        match = re.search(r"meeting of the ([^.]+?)(?: meeting announcement| advisory committee|$)", normalized, re.IGNORECASE)
        if match:
            name = match.group(1).strip(" -,:")
            return f"{name} Advisory Committee" if "advisory committee" not in name.lower() else name
        match = re.search(r"([A-Za-z][A-Za-z\s&-]+Advisory Committee)", normalized)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _parse_datetime(text: str | None) -> datetime | None:
        if not text:
            return None
        try:
            parsed = date_parser.parse(text)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _importance_score(
        *,
        title: str,
        committee_name: str | None,
        starts_at: datetime,
        market_cap_score: float,
    ) -> float:
        now = datetime.now(UTC)
        days_until = (starts_at.date() - now.date()).days
        if 0 <= days_until <= 30:
            timing = 100.0 - min(days_until * 2.0, 50.0)
        elif -14 <= days_until < 0:
            timing = 78.0
        elif days_until > 30:
            timing = max(35.0, 85.0 - min((days_until - 30) * 0.6, 45.0))
        else:
            timing = 28.0

        committee_bonus = 16.0 if committee_name and "oncologic" in committee_name.lower() else 8.0
        title_bonus = 12.0 if "advisory committee" in title.lower() else 6.0
        return round(min(0.60 * timing + 0.20 * market_cap_score + committee_bonus + title_bonus, 100.0), 2)

    @staticmethod
    def _composite_score(*, starts_at: datetime, market_cap_score: float, importance_score: float) -> float:
        now = datetime.now(UTC)
        days_until = (starts_at.date() - now.date()).days
        if 0 <= days_until <= 14:
            urgency = 100.0
        elif 15 <= days_until <= 45:
            urgency = 82.0
        elif days_until > 45:
            urgency = 62.0
        elif -7 <= days_until < 0:
            urgency = 74.0
        else:
            urgency = 40.0
        return round((0.55 * urgency) + (0.25 * market_cap_score) + (0.20 * importance_score), 2)

    @staticmethod
    def _priority_reason(*, starts_at: datetime, market_cap_score: float, company_tag_ids: list[int]) -> str:
        now = datetime.now(UTC)
        days_until = (starts_at.date() - now.date()).days
        reasons: list[str] = ["official FDA calendar"]
        if 0 <= days_until <= 30:
            reasons.append("upcoming committee date")
        elif days_until < 0:
            reasons.append("recent committee activity")
        if company_tag_ids:
            reasons.append("linked to tracked company")
        if market_cap_score >= 75:
            reasons.append("large-cap sponsor relevance")
        return ", ".join(reasons[:3])

    @staticmethod
    def _timeline_sort_key(item: RegulatoryEvent, *, now: datetime) -> tuple[float, float, float]:
        if item.starts_at >= now:
            hours_until = max((item.starts_at - now).total_seconds() / 3600.0, 0.0)
            return (0.0, hours_until, -(item.composite_score or 0.0))
        return (1.0, -item.starts_at.timestamp(), -(item.composite_score or 0.0))

    @staticmethod
    def _to_timeline_event(item: RegulatoryEvent, *, company_map: dict[int, str]) -> dict[str, Any]:
        return {
            "id": f"regulatory-{item.id}",
            "item_type": "regulatory",
            "item_id": item.id,
            "occurred_at": item.starts_at,
            "title": item.title,
            "summary": item.summary_text or item.priority_reason or "",
            "company_ids": list(item.company_tag_ids or []),
            "company_names": [company_map[company_id] for company_id in (item.company_tag_ids or []) if company_id in company_map],
            "href": None,
            "external_url": item.canonical_url,
            "source_type": item.source_type,
            "event_type": item.event_type,
            "priority_reason": item.priority_reason or "",
            "summary_tier": "no_ai",
            "is_official_source": bool(item.is_official_source),
            "freshness_bucket": item.freshness_bucket or freshness_bucket(item.starts_at),
            "composite_score": float(item.composite_score or 0.0),
            "tags": list(item.topic_tags or []),
        }
