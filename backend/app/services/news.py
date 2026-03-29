from __future__ import annotations

import contextlib
import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, NewsItem, Watchlist
from app.schemas import NewsItemResponse
from app.services.constants import COMPANY_IR_FEEDS, COMPANY_IR_SOURCES, NEWS_FEEDS
from app.services.ranking import (
    company_market_cap_percentiles,
    compute_news_scores,
    compute_pending_news_scores,
    freshness_bucket,
    news_priority_reason,
    news_summary_priority_score,
    personal_relevance_score,
)
from app.services.summary_budget import SummaryBudgetService
from app.services.summarization import OpenAISummarizer, UsageMetrics

COMPANY_TAG_LIMIT = 10
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
MULTISPACE_RE = re.compile(r"\s+")
OFFICIAL_NEWS_SOURCES = {"FDA Press Releases", "FDA Drug Approvals"}
REGULATOR_NEWS_SOURCES = {"FDA Press Releases", "FDA Drug Approvals"}
HIGH_SIGNAL_NEWS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "approval": ("approval", "approves", "clearance", "authorized"),
    "regulatory": ("fda", "complete response letter", "crl", "warning letter", "advisory committee"),
    "earnings": ("earnings", "quarterly results", "annual results", "guidance", "results"),
    "financing": ("offering", "financing", "debt", "raise", "capital"),
    "clinical-data": ("phase 3", "phase 2", "topline", "trial data", "clinical data"),
    "material-agreement": ("partnership", "collaboration", "license", "licensing", "agreement"),
    "acquisition": ("acquisition", "merger", "buyout", "takeover"),
    "leadership-change": ("ceo", "cfo", "chief executive", "board", "chair", "appointed"),
    "manufacturing": ("manufacturing", "plant", "facility", "supply"),
}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _published_at(entry: feedparser.FeedParserDict) -> datetime:
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            try:
                parsed = date_parser.parse(raw)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    if entry.get("published_parsed"):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _clean_html_text(value: str | None) -> str:
    raw = unescape(value or "")
    if "<" not in raw and ">" not in raw:
        return MULTISPACE_RE.sub(" ", raw).strip()
    return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)


def _normalize_company_text(value: str) -> str:
    normalized = NON_ALNUM_RE.sub(" ", (value or "").lower())
    return MULTISPACE_RE.sub(" ", normalized).strip()


def _dedupe_preserve_order(values: Iterable[int | str]) -> list:
    seen: set[int | str] = set()
    deduped: list[int | str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _watchlist_company_ids(session: Session) -> set[int]:
    watchlists = session.scalars(select(Watchlist)).all()
    ids: set[int] = set()
    for watchlist in watchlists:
        ids.update(int(company_id) for company_id in (watchlist.company_ids or []))
    return ids


def _classify_news_source(source_name: str, canonical_url: str) -> tuple[str, bool]:
    if source_name in REGULATOR_NEWS_SOURCES or "fda.gov" in canonical_url:
        return "regulator", True
    if source_name in OFFICIAL_NEWS_SOURCES:
        return "official_company_pr", True
    return "trade_press", False


def _infer_news_event_type(title: str, text: str, topic_tags: list[str]) -> str | None:
    lowered = f"{title} {text}".lower()
    for event_type, markers in HIGH_SIGNAL_NEWS_KEYWORDS.items():
        if any(marker in lowered for marker in markers):
            return event_type
    if "clinical" in topic_tags:
        return "clinical-data"
    if "regulatory" in topic_tags:
        return "regulatory"
    if "finance" in topic_tags:
        return "earnings"
    return None


def _build_news_dedupe_group_id(
    *,
    company_tag_ids: list[int],
    event_type: str | None,
    title: str,
    published_at: datetime,
) -> str:
    company_key = "-".join(str(company_id) for company_id in sorted(company_tag_ids)[:3]) or "sector"
    event_key = event_type or _normalize_company_text(title).split(" ")[:3]
    if isinstance(event_key, list):
        event_key = "-".join(filter(None, event_key)) or "general"
    date_key = published_at.date().isoformat()
    return f"{company_key}:{event_key}:{date_key}"


class NewsService:
    def __init__(
        self,
        session: Session,
        summarizer: OpenAISummarizer | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.session = session
        self._owns_summarizer = summarizer is None
        self._owns_http_client = http_client is None
        self.summarizer = summarizer or OpenAISummarizer()
        self.http_client = http_client or httpx.Client(timeout=get_settings().source_fetch_timeout_seconds, follow_redirects=True)
        self.settings = get_settings()

    def close(self) -> None:
        if self._owns_http_client:
            with contextlib.suppress(Exception):
                self.http_client.close()
        if self._owns_summarizer:
            with contextlib.suppress(Exception):
                self.summarizer.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def ingest_feeds(self) -> int:
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        company_aliases = self._company_aliases(companies)
        inserted = 0

        for feed in self._feeds_to_ingest(companies):
            for entry in self._entries_for_source(feed):
                title = _clean_html_text(entry.get("title"))
                if self._should_skip_entry(title):
                    continue
                canonical_url = _normalize_url(entry.get("link", ""))
                article_hash = hashlib.sha256(f"{canonical_url}|{title}".encode("utf-8")).hexdigest()
                existing = self.session.scalar(
                    select(NewsItem).where((NewsItem.canonical_url == canonical_url) | (NewsItem.article_hash == article_hash))
                )
                if existing:
                    continue

                excerpt = _clean_html_text(entry.get("summary")) or None
                article_text, article_published_at = self._fetch_article_details(canonical_url)
                article_text = article_text or excerpt or title
                mentioned, company_tag_ids = self._detect_companies(f"{title}\n{article_text}", company_aliases)
                if feed.get("seed_company_name"):
                    mentioned = _dedupe_preserve_order([feed["seed_company_name"], *mentioned])
                if feed.get("seed_company_id") is not None:
                    company_tag_ids = _dedupe_preserve_order([int(feed["seed_company_id"]), *company_tag_ids])
                topic_tags = sorted(set(feed["topic_tags"] + self._infer_topics(title, article_text)))
                source_type, is_official_source = (
                    feed.get("source_type"),
                    bool(feed.get("is_official_source")),
                )
                if not source_type:
                    source_type, is_official_source = _classify_news_source(feed["name"], canonical_url)
                published_at = article_published_at or _published_at(entry)
                event_type = _infer_news_event_type(title, article_text, topic_tags)
                dedupe_group_id = _build_news_dedupe_group_id(
                    company_tag_ids=company_tag_ids,
                    event_type=event_type,
                    title=title,
                    published_at=published_at,
                )

                news_item = NewsItem(
                    source_name=feed["name"],
                    source_weight=feed["source_weight"],
                    feed_url=feed["feed_url"],
                    title=title,
                    canonical_url=canonical_url,
                    excerpt=excerpt,
                    content_text=article_text,
                    published_at=published_at,
                    article_hash=article_hash,
                    mentioned_companies=mentioned,
                    company_tag_ids=company_tag_ids,
                    topic_tags=topic_tags,
                    source_type=source_type,
                    event_type=event_type,
                    is_official_source=is_official_source,
                    dedupe_group_id=dedupe_group_id,
                    freshness_bucket=freshness_bucket(published_at),
                )
                self.session.add(news_item)
                self.session.flush()
                news_item.summary_status = "pending"
                news_item.summary_tier = "no_ai"
                self._apply_scores(news_item, companies)
                inserted += 1

        self.session.commit()
        return inserted

    def summarize_item(
        self,
        item_id: int,
        *,
        consume_override_budget: bool = False,
        force: bool = False,
    ) -> dict[str, int | str]:
        news_item = self.session.get(NewsItem, item_id)
        if not news_item:
            raise ValueError(f"Unknown news id={item_id}")
        if not force and news_item.summary_status == "complete":
            return {"status": "already_complete", "remaining_override_budget": self._remaining_override_budget()}

        budget_service = SummaryBudgetService(self.session)
        if consume_override_budget and self.settings.openai_api_key and not budget_service.has_capacity("override"):
            raise RuntimeError("override_budget_exhausted")

        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        self._apply_summary(
            news_item,
            trigger="manual",
            summary_tier="full_ai",
            budget_kind="override" if consume_override_budget else None,
        )
        self._apply_scores(news_item, companies)

        self.session.commit()
        return {"status": "summarized", "remaining_override_budget": self._remaining_override_budget()}

    def summarize_pending(self, *, limit: int | None = None, automated: bool = True) -> dict[str, int]:
        budget_service = SummaryBudgetService(self.session)
        remaining_daily = (
            budget_service.remaining("news")
            if automated and self.settings.openai_api_key
            else max(limit or 0, self.settings.max_news_summaries_per_run)
        )
        remaining_override = budget_service.remaining("override") if automated and self.settings.openai_api_key else 0
        effective_limit = limit or self.settings.max_news_summaries_per_run

        if effective_limit <= 0:
            return {
                "summarized": 0,
                "remaining_daily_budget": remaining_daily,
                "remaining_daily_budget_usd": round(budget_service.remaining_usd("news"), 4) if self.settings.openai_api_key else 0.0,
            }

        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        market_caps = company_market_cap_percentiles(self.session)
        watchlist_company_ids = _watchlist_company_ids(self.session)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.news_summary_backlog_days)
        raw_candidates = self.session.scalars(
            select(NewsItem)
            .where(NewsItem.summary_status.in_(["pending", "failed", "stale"]), NewsItem.summary_attempts < 3)
        ).all()
        candidates = sorted(
            raw_candidates,
            key=lambda item: news_summary_priority_score(
                item,
                max((market_caps.get(cid, 0.0) for cid in (item.company_tag_ids or [])), default=0.0),
            ) + (20.0 if set(item.company_tag_ids or []).intersection(watchlist_company_ids) else 0.0),
            reverse=True,
        )

        summarized = 0
        for news_item in candidates:
            published_at = news_item.published_at
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            if automated and published_at < cutoff:
                continue
            is_override = self._qualifies_for_priority_override(news_item, watchlist_company_ids)
            if automated and self.settings.openai_api_key:
                budget_kind = self._select_automated_budget_kind(
                    budget_service,
                    primary_kind="news",
                    allow_override=is_override,
                )
                if budget_kind is None:
                    continue
            else:
                budget_kind = "news"
            try:
                preferred_tier = self._summary_tier_for_news_item(
                    news_item,
                    automated=automated,
                    watchlist_company_ids=watchlist_company_ids,
                )
                summary_tier = self._resolve_summary_tier(
                    budget_service,
                    preferred_tier=preferred_tier,
                    automated=automated,
                )
                if summary_tier is None:
                    continue
                self._apply_summary(
                    news_item,
                    trigger="auto" if automated else "manual",
                    summary_tier=summary_tier,
                    budget_kind=budget_kind,
                )
                self._apply_scores(news_item, companies)
            except Exception:
                news_item.summary_status = "failed"
                news_item.summary_attempts += 1
                continue
            summarized += 1
            if summarized >= effective_limit:
                break

        self.session.commit()
        remaining = budget_service.remaining("news") if self.settings.openai_api_key else 0
        return {
            "summarized": summarized,
            "remaining_daily_budget": remaining,
            "remaining_daily_budget_usd": round(budget_service.remaining_usd("news"), 4) if self.settings.openai_api_key else 0.0,
        }

    def list_news(
        self,
        limit: int = 50,
        recent_days: int | None = None,
        watchlist_id: int | None = None,
        sort_mode: str = "importance",
    ) -> list[NewsItemResponse]:
        rows = self._list_news_items(
            limit=limit,
            offset=0,
            recent_days=recent_days,
            watchlist_id=watchlist_id,
            sort_mode=sort_mode,
        )["items"]
        return [self._to_response(item) for item in rows]

    def list_news_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        source_name: str | None = None,
        search: str | None = None,
        sort_by: str = "composite_score",
        recent_days: int | None = None,
        watchlist_id: int | None = None,
        sort_mode: str | None = None,
    ) -> dict:
        result = self._list_news_items(
            limit=limit,
            offset=offset,
            source_name=source_name,
            search=search,
            recent_days=recent_days,
            watchlist_id=watchlist_id,
            sort_mode=sort_mode or ("freshness" if sort_by == "published_at" else "importance"),
        )
        return {
            "items": [self._to_response(item) for item in result["items"]],
            "total": result["total"],
            "offset": offset,
            "limit": limit,
        }

    def list_news_for_company(self, company: Company, limit: int = 20) -> list[NewsItemResponse]:
        matches = self._news_items_for_company(company, sort_mode="personal")
        return [self._to_response(item) for item in matches[:limit]]

    def list_news_for_company_by_id(self, company_id: int, limit: int = 20) -> list[NewsItemResponse]:
        """List news for a company by ID (used by watchlist feed)."""
        company = self.session.get(Company, company_id)
        if not company:
            return []
        return self.list_news_for_company(company, limit=limit)

    def count_news_for_company(self, company: Company) -> int:
        return len(self._news_items_for_company(company, sort_mode="personal"))

    def retag_company_news(
        self,
        *,
        limit: int | None = None,
        recent_days: int | None = None,
        focus_tickers: list[str] | None = None,
    ) -> dict[str, int]:
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        if not companies:
            return {"scanned": 0, "updated": 0, "reranked": 0}

        focus_set = {ticker.upper() for ticker in (focus_tickers or [])}
        focus_company_ids = {
            company.id
            for company in companies
            if focus_set and (company.ticker or "").upper() in focus_set
        }
        company_aliases = self._company_aliases(companies)
        market_caps = company_market_cap_percentiles(self.session)

        query = select(NewsItem).order_by(NewsItem.published_at.desc(), NewsItem.id.desc())
        if recent_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
            query = query.where(NewsItem.published_at >= cutoff)
        news_items = self.session.scalars(query).all()

        scanned = 0
        updated = 0
        reranked = 0
        for news_item in news_items:
            text = f"{news_item.title or ''}\n{news_item.content_text or news_item.excerpt or ''}"
            mentioned, company_tag_ids = self._detect_companies(text, company_aliases)
            if focus_set and not (
                focus_company_ids.intersection(company_tag_ids) or focus_company_ids.intersection(set(news_item.company_tag_ids or []))
            ):
                continue
            if limit is not None and scanned >= limit:
                break
            scanned += 1

            existing_mentions = news_item.mentioned_companies or []
            existing_company_tags = news_item.company_tag_ids or []
            if mentioned != existing_mentions or company_tag_ids != existing_company_tags:
                news_item.mentioned_companies = mentioned
                news_item.company_tag_ids = company_tag_ids
                updated += 1

            source_type, is_official_source = _classify_news_source(
                news_item.source_name,
                news_item.canonical_url,
            )
            news_item.source_type = source_type
            news_item.is_official_source = is_official_source
            news_item.event_type = _infer_news_event_type(
                news_item.title or "",
                news_item.content_text or news_item.excerpt or "",
                news_item.topic_tags or [],
            )
            news_item.dedupe_group_id = _build_news_dedupe_group_id(
                company_tag_ids=company_tag_ids,
                event_type=news_item.event_type,
                title=news_item.title,
                published_at=news_item.published_at,
            )
            news_item.freshness_bucket = freshness_bucket(news_item.published_at)

            self._apply_scores(news_item, companies, market_caps=market_caps)
            reranked += 1

        self.session.commit()
        return {"scanned": scanned, "updated": updated, "reranked": reranked}

    def rerank_for_companies(self, company_ids: Iterable[int] | None = None) -> int:
        target_ids = sorted({int(company_id) for company_id in (company_ids or [])})
        if company_ids is not None and not target_ids:
            return 0

        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        if not companies:
            return 0

        news_items = self.session.scalars(select(NewsItem).order_by(NewsItem.published_at.desc(), NewsItem.id.desc())).all()
        market_caps = company_market_cap_percentiles(self.session)
        updated = 0
        for news_item in news_items:
            if target_ids and not set(news_item.company_tag_ids or []).intersection(target_ids):
                continue
            self._apply_scores(news_item, companies, market_caps=market_caps)
            updated += 1

        self.session.commit()
        return updated

    def _to_response(self, item: NewsItem) -> NewsItemResponse:
        summary = item.summary_json or {}
        return NewsItemResponse(
            id=item.id,
            source_name=item.source_name,
            title=_clean_html_text(item.title),
            canonical_url=item.canonical_url,
            excerpt=item.excerpt,
            published_at=item.published_at,
            mentioned_companies=item.mentioned_companies or [],
            company_tag_ids=item.company_tag_ids or [],
            topic_tags=item.topic_tags or [],
            importance_score=item.importance_score,
            market_cap_score=item.market_cap_score,
            composite_score=item.composite_score,
            score_explanation=item.score_explanation or {},
            summary_status=self._effective_summary_status(item),
            summary_tier=item.summary_tier or "no_ai",
            source_type=item.source_type or "trade_press",
            event_type=item.event_type,
            priority_reason=item.priority_reason or "",
            is_official_source=bool(item.is_official_source),
            dedupe_group_id=item.dedupe_group_id,
            freshness_bucket=item.freshness_bucket or freshness_bucket(item.published_at),
            summary=summary.get("summary", ""),
            key_takeaways=summary.get("key_takeaways", []),
        )

    def _apply_summary(self, news_item: NewsItem, *, trigger: str, summary_tier: str, budget_kind: str | None) -> None:
        text_limit = 4000 if summary_tier == "short_ai" else 12000
        source_text = (news_item.content_text or news_item.excerpt or news_item.title)[:text_limit]
        model = self._model_for_summary(summary_tier=summary_tier, trigger=trigger)
        prompt_cache_key = self._summary_prompt_cache_key(news_item, summary_tier=summary_tier, model=model)
        if hasattr(self.summarizer, "summarize_with_usage"):
            result = self.summarizer.summarize_with_usage(
                kind="news",
                title=news_item.title,
                text=source_text,
                company_name=", ".join(news_item.mentioned_companies) if news_item.mentioned_companies else None,
                evidence_sections=news_item.topic_tags or [],
                model=model,
                prompt_cache_key=prompt_cache_key,
            )
            summary = result.payload
            usage = result.usage
        else:
            summary = self.summarizer.summarize(
                kind="news",
                title=news_item.title,
                text=source_text,
                company_name=", ".join(news_item.mentioned_companies) if news_item.mentioned_companies else None,
                evidence_sections=news_item.topic_tags or [],
            )
            usage = UsageMetrics(model=model if self.settings.openai_api_key else "fallback-local")

        news_item.summary_json = summary.model_dump()
        news_item.summary_model = usage.model
        news_item.summary_prompt_version = self.settings.summary_prompt_version
        news_item.summary_status = "complete"
        news_item.summary_tier = summary_tier
        news_item.summary_attempts += 1
        news_item.extra_metadata = {**(news_item.extra_metadata or {}), "summary_trigger": trigger}
        self._record_usage(budget_kind, self._summary_usage_kind(summary_tier), usage)

    def _apply_scores(
        self,
        news_item: NewsItem,
        companies: list[Company],
        *,
        market_caps: dict[int, float] | None = None,
    ) -> None:
        market_caps = market_caps or company_market_cap_percentiles(self.session)
        company_scores = [
            market_caps.get(company.id, 0.0)
            for company in companies
            if company.id in set(news_item.company_tag_ids or [])
        ]
        market_score = max(company_scores) if company_scores else 0.0
        if news_item.summary_status == "complete":
            scores = compute_news_scores(news_item, company_market_cap_score=market_score)
        else:
            scores = compute_pending_news_scores(news_item, company_market_cap_score=market_score)
        news_item.importance_score = float(scores["importance_score"])
        news_item.market_cap_score = float(scores["market_cap_score"])
        news_item.composite_score = float(scores["composite_score"])
        news_item.score_explanation = dict(scores["score_explanation"])
        news_item.freshness_bucket = freshness_bucket(news_item.published_at)
        news_item.priority_reason = news_priority_reason(
            news_item,
            company_market_cap_score=market_score,
            importance=news_item.importance_score,
            recency=float((news_item.score_explanation or {}).get("components", {}).get("recency", 0.0)),
        )

    def _fetch_article_details(self, url: str) -> tuple[str, datetime | None]:
        from app.services.constants import SITE_ARTICLE_SELECTORS

        if not url:
            return "", None
        try:
            response = self.http_client.get(url)
            response.raise_for_status()
        except Exception:
            return "", None
        soup = BeautifulSoup(response.text, "html.parser")
        published_at = self._extract_published_at_from_soup(soup)

        # Try per-site CSS selector first
        parsed_domain = urlparse(url).netloc.lower()
        for domain, selector in SITE_ARTICLE_SELECTORS.items():
            if domain in parsed_domain:
                element = soup.select_one(selector)
                if element:
                    return element.get_text(" ", strip=True), published_at

        # Generic fallback: <article> tag or all <p> tags
        article = soup.find("article")
        if article:
            return article.get_text(" ", strip=True), published_at
        paragraphs = [tag.get_text(" ", strip=True) for tag in soup.find_all("p")]
        return " ".join(paragraphs[:40]), published_at

    def _entries_for_source(self, feed: dict) -> list[feedparser.FeedParserDict]:
        if str(feed.get("source_kind") or "rss") == "html_page":
            return self._parse_html_page_entries(feed)
        parsed = feedparser.parse(feed["feed_url"])
        return list(parsed.entries)

    def _parse_html_page_entries(self, feed: dict) -> list[feedparser.FeedParserDict]:
        try:
            response = self.http_client.get(feed["feed_url"])
            response.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        selectors = list(feed.get("entry_selectors") or [])
        link_patterns = [pattern.lower() for pattern in (feed.get("entry_path_patterns") or [])]

        anchor_candidates = []
        if selectors:
            for selector in selectors:
                anchor_candidates.extend(soup.select(selector))
        else:
            anchor_candidates.extend(soup.select("a[href]"))

        entries: list[feedparser.FeedParserDict] = []
        seen_urls: set[str] = set()
        for anchor in anchor_candidates:
            href = anchor.get("href") or ""
            if not href or href.startswith(("mailto:", "javascript:", "#")):
                continue
            canonical_url = _normalize_url(urljoin(feed["feed_url"], href))
            if canonical_url in seen_urls:
                continue
            lowered_href = canonical_url.lower()
            if link_patterns and not any(pattern in lowered_href for pattern in link_patterns):
                continue
            title = _clean_html_text(anchor.get_text(" ", strip=True))
            if len(title) < 15:
                continue

            published_text = ""
            for ancestor in list(anchor.parents)[:4]:
                ancestor_text = _clean_html_text(ancestor.get_text(" ", strip=True))
                if not ancestor_text:
                    continue
                published_text = self._extract_date_text(ancestor_text) or published_text
                if published_text:
                    break

            entries.append(
                feedparser.FeedParserDict(
                    title=title,
                    link=canonical_url,
                    summary="",
                    published=published_text,
                )
            )
            seen_urls.add(canonical_url)
            if len(entries) >= 12:
                break
        return entries

    def _feeds_to_ingest(self, companies: list[Company]) -> list[dict]:
        feeds = [dict(feed) for feed in NEWS_FEEDS]
        seen_urls = {feed["feed_url"] for feed in feeds}
        watchlist_ids = _watchlist_company_ids(self.session)
        ranked = sorted(companies, key=lambda company: (company.market_cap or 0), reverse=True)
        prioritized_ids = set(watchlist_ids)
        prioritized_ids.update(company.id for company in ranked[: self.settings.company_ir_top_company_limit])
        companies_by_id = {company.id: company for company in companies}

        for company_id in prioritized_ids:
            company = companies_by_id.get(company_id)
            if not company:
                continue
            topic_tags = ["company-pr"]
            sic = company.sic or ""
            if sic in {"2834", "2836"}:
                topic_tags.append("pharma" if sic == "2834" else "biotech")
            for ir_source in self._company_ir_sources(company):
                feed_url = str(ir_source.get("url") or "")
                if not feed_url or feed_url in seen_urls:
                    continue
                seen_urls.add(feed_url)
                feeds.append(
                    {
                        "name": f"{company.name} Investor Relations",
                        "feed_url": feed_url,
                        "source_kind": ir_source.get("kind", "rss"),
                        "entry_selectors": list(ir_source.get("entry_selectors") or []),
                        "entry_path_patterns": list(ir_source.get("entry_path_patterns") or []),
                        "source_weight": 0.98,
                        "topic_tags": topic_tags,
                        "source_type": "official_company_pr",
                        "is_official_source": True,
                        "seed_company_id": company.id,
                        "seed_company_name": company.name,
                    }
                )
        return feeds

    @staticmethod
    def _company_ir_sources(company: Company) -> list[dict[str, object]]:
        extra = company.extra_metadata or {}
        if isinstance(extra.get("ir_sources"), list):
            sources: list[dict[str, object]] = []
            for source in extra["ir_sources"]:
                if isinstance(source, dict) and source.get("url"):
                    sources.append(
                        {
                            "kind": source.get("kind", "rss"),
                            "url": source["url"],
                            "entry_selectors": list(source.get("entry_selectors") or []),
                            "entry_path_patterns": list(source.get("entry_path_patterns") or []),
                        }
                    )
            if sources:
                return sources

        sources: list[dict[str, object]] = []
        if extra.get("ir_feed_url"):
            sources.append({"kind": "rss", "url": str(extra["ir_feed_url"])})
        if extra.get("ir_news_page_url"):
            sources.append(
                {
                    "kind": "html_page",
                    "url": str(extra["ir_news_page_url"]),
                    "entry_selectors": list(extra.get("ir_entry_selectors") or []),
                    "entry_path_patterns": list(extra.get("ir_entry_path_patterns") or []),
                }
            )
        for source in COMPANY_IR_SOURCES.get((company.ticker or "").upper(), []):
            if isinstance(source, dict) and source.get("url"):
                sources.append(
                    {
                        "kind": source.get("kind", "rss"),
                        "url": source["url"],
                        "entry_selectors": list(source.get("entry_selectors") or []),
                        "entry_path_patterns": list(source.get("entry_path_patterns") or []),
                    }
                )
        if not sources and company.ticker:
            feed_url = COMPANY_IR_FEEDS.get((company.ticker or "").upper())
            if feed_url:
                sources.append({"kind": "rss", "url": feed_url})
        return sources

    @staticmethod
    def _extract_published_at_from_soup(soup: BeautifulSoup) -> datetime | None:
        meta_candidates = [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "article:published_time"}),
            ("meta", {"name": "pubdate"}),
            ("meta", {"name": "publish-date"}),
            ("meta", {"name": "date"}),
            ("meta", {"itemprop": "datePublished"}),
        ]
        for tag_name, attrs in meta_candidates:
            tag = soup.find(tag_name, attrs=attrs)
            if tag and tag.get("content"):
                try:
                    parsed = date_parser.parse(tag["content"])
                    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

        time_tag = soup.select_one("time[datetime]")
        if time_tag and time_tag.get("datetime"):
            try:
                parsed = date_parser.parse(time_tag["datetime"])
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        page_text = _clean_html_text(soup.get_text(" ", strip=True)[:1200])
        date_text = NewsService._extract_date_text(page_text)
        if date_text:
            try:
                parsed = date_parser.parse(date_text)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _extract_date_text(text: str) -> str | None:
        match = re.search(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2},\s+\d{4}\b",
            text,
            re.IGNORECASE,
        )
        return match.group(0) if match else None

    @staticmethod
    def _should_skip_entry(title: str) -> bool:
        lowered = title.lower()
        return any(keyword in lowered for keyword in ["webinar", "whitepaper", "sponsored", "advertisement"])

    @staticmethod
    def _infer_topics(title: str, text: str) -> list[str]:
        lowered = f"{title} {text}".lower()
        topic_map = {
            "regulatory": ["fda", "approval", "clearance", "warning letter"],
            "manufacturing": ["plant", "manufacturing", "facility"],
            "clinical": ["trial", "phase 1", "phase 2", "phase 3", "study"],
            "m&a": ["acquisition", "merger", "deal"],
            "finance": ["earnings", "guidance", "financing", "layoff"],
        }
        return [topic for topic, markers in topic_map.items() if any(marker in lowered for marker in markers)]

    @staticmethod
    def _company_aliases(companies: Iterable[Company]) -> list[tuple[str, int, str, bool]]:
        """Returns (normalized_alias, company_id, mention_value, requires_word_boundary)."""
        aliases: list[tuple[str, int, str, bool]] = []
        seen: set[tuple[str, int]] = set()
        for company in companies:
            candidates: list[tuple[str, str]] = [(company.name, company.name)]
            if company.ticker:
                candidates.append((company.ticker, company.ticker))
            # Include extra aliases from the model (drug names, subsidiaries)
            for extra in getattr(company, "aliases", None) or []:
                if extra:
                    candidates.append((extra, extra))
            for raw_alias, mention_value in candidates:
                normalized = _normalize_company_text(raw_alias)
                if not normalized:
                    continue
                key = (normalized, company.id)
                if key in seen:
                    continue
                seen.add(key)
                # Short aliases (1-2 chars like "A", "AI") need word-boundary matching
                requires_word_boundary = len(normalized) < 3
                aliases.append((normalized, company.id, mention_value, requires_word_boundary))
        aliases.sort(key=lambda item: (-len(item[0]), item[0], item[1]))
        return aliases

    @staticmethod
    def _detect_companies(text: str, aliases: list[tuple[str, int, str, bool]]) -> tuple[list[str], list[int]]:
        normalized_text = _normalize_company_text(text)
        padded_text = f" {normalized_text} "
        mentioned_companies: list[str] = []
        company_tag_ids: list[int] = []
        for alias, company_id, mention_value, requires_word_boundary in aliases:
            if not alias:
                continue
            if requires_word_boundary:
                # Use regex word boundary for short tickers to avoid false positives
                if not re.search(rf"\b{re.escape(alias)}\b", normalized_text):
                    continue
            else:
                if f" {alias} " not in padded_text:
                    continue
            if company_id not in company_tag_ids:
                if len(company_tag_ids) >= COMPANY_TAG_LIMIT:
                    continue
                company_tag_ids.append(company_id)
            if mention_value not in mentioned_companies:
                mentioned_companies.append(mention_value)
        return mentioned_companies, company_tag_ids

    def _effective_summary_status(self, item: NewsItem) -> str:
        return item.summary_status

    def _remaining_override_budget(self) -> int:
        if not self.settings.openai_api_key:
            return 0
        return SummaryBudgetService(self.session).remaining("override")

    def pending_queue_counts(self) -> dict[str, int]:
        watchlist_company_ids = _watchlist_company_ids(self.session)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.news_summary_backlog_days)
        counts = {"news_pending": 0, "news_pending_full_ai": 0, "news_pending_short_ai": 0}
        items = self.session.scalars(
            select(NewsItem)
            .where(NewsItem.summary_status.in_(["pending", "failed", "stale"]), NewsItem.summary_attempts < 3)
        ).all()
        for news_item in items:
            published_at = news_item.published_at if news_item.published_at.tzinfo else news_item.published_at.replace(tzinfo=timezone.utc)
            if published_at < cutoff:
                continue
            counts["news_pending"] += 1
            tier = self._summary_tier_for_news_item(
                news_item,
                automated=True,
                watchlist_company_ids=watchlist_company_ids,
            )
            counts[f"news_pending_{tier}"] += 1
        return counts

    def _summary_tier_for_news_item(
        self,
        news_item: NewsItem,
        *,
        automated: bool,
        watchlist_company_ids: set[int],
    ) -> str:
        if not automated:
            return "full_ai"
        if news_item.is_official_source or news_item.event_type in {"approval", "regulatory", "earnings", "acquisition"}:
            return "full_ai"
        if set(news_item.company_tag_ids or []).intersection(watchlist_company_ids):
            return "full_ai"
        return "short_ai"

    @staticmethod
    def _qualifies_for_priority_override(news_item: NewsItem, watchlist_company_ids: set[int]) -> bool:
        return bool(
            news_item.is_official_source
            or news_item.event_type in {"approval", "regulatory", "earnings", "acquisition", "leadership-change"}
            or set(news_item.company_tag_ids or []).intersection(watchlist_company_ids)
        )

    def _resolve_summary_tier(
        self,
        budget_service: SummaryBudgetService,
        *,
        preferred_tier: str,
        automated: bool,
    ) -> str | None:
        if not automated or not self.settings.openai_api_key:
            return preferred_tier
        if preferred_tier == "full_ai":
            if budget_service.remaining("news_full_ai") > 0:
                return "full_ai"
            if budget_service.remaining("news_short_ai") > 0:
                return "short_ai"
            return None
        if budget_service.remaining("news_short_ai") > 0:
            return "short_ai"
        return None

    @staticmethod
    def _select_automated_budget_kind(
        budget_service: SummaryBudgetService,
        *,
        primary_kind: str,
        allow_override: bool,
    ) -> str | None:
        if budget_service.has_capacity(primary_kind):
            return primary_kind
        if allow_override and budget_service.has_capacity("override"):
            return "override"
        return None

    def _model_for_summary(self, *, summary_tier: str, trigger: str) -> str:
        if trigger == "manual":
            return self.settings.openai_model_manual
        if summary_tier == "short_ai":
            return self.settings.openai_model_summary_short
        return self.settings.openai_model_summary_full

    @staticmethod
    def _summary_usage_kind(summary_tier: str) -> str:
        return "news_short_ai" if summary_tier == "short_ai" else "news_full_ai"

    def _summary_prompt_cache_key(self, news_item: NewsItem, *, summary_tier: str, model: str) -> str:
        event_group = news_item.event_type or "general"
        return f"summary:news:{summary_tier}:{event_group}:{self.settings.summary_prompt_version}:{model}"

    def _record_usage(self, budget_kind: str | None, tier_kind: str, usage: UsageMetrics) -> None:
        if not self.settings.openai_api_key or budget_kind is None:
            return
        budget_service = SummaryBudgetService(self.session)
        budget_service.record(
            budget_kind,
            1,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
            model=usage.model,
        )
        budget_service.record(tier_kind, 1)

    def _representative_news_items(self, items: list[NewsItem], *, sort_mode: str) -> list[NewsItem]:
        groups: dict[str, list[NewsItem]] = {}
        for item in items:
            groups.setdefault(item.dedupe_group_id or f"news:{item.id}", []).append(item)

        representatives: list[NewsItem] = []
        for group_items in groups.values():
            representative = max(
                group_items,
                key=lambda item: (
                    1 if item.is_official_source else 0,
                    item.composite_score,
                    item.published_at,
                ),
            )
            representatives.append(representative)
        return self._sort_news_items(representatives, sort_mode=sort_mode)

    def _sort_news_items(self, items: list[NewsItem], *, sort_mode: str, watchlist_match_ids: set[int] | None = None) -> list[NewsItem]:
        if sort_mode == "freshness":
            return sorted(items, key=lambda item: (item.published_at, item.composite_score), reverse=True)
        if sort_mode == "personal":
            watchlist_match_ids = watchlist_match_ids or set()
            return sorted(
                items,
                key=lambda item: personal_relevance_score(
                    composite_score=item.composite_score,
                    published_at=item.published_at,
                    is_official_source=bool(item.is_official_source),
                    watchlist_match=bool(set(item.company_tag_ids or []).intersection(watchlist_match_ids)),
                    event_type=item.event_type,
                ),
                reverse=True,
            )
        return sorted(items, key=lambda item: (item.composite_score, item.published_at), reverse=True)

    def _list_news_items(
        self,
        *,
        limit: int,
        offset: int,
        source_name: str | None = None,
        search: str | None = None,
        recent_days: int | None = None,
        watchlist_id: int | None = None,
        sort_mode: str = "importance",
    ) -> dict[str, list[NewsItem] | int]:
        rows = self.session.scalars(select(NewsItem).order_by(NewsItem.published_at.desc(), NewsItem.id.desc())).all()
        watchlist_match_ids: set[int] = set()
        if watchlist_id is not None:
            watchlist = self.session.get(Watchlist, watchlist_id)
            if watchlist:
                watchlist_match_ids = {int(company_id) for company_id in (watchlist.company_ids or [])}
                rows = [item for item in rows if set(item.company_tag_ids or []).intersection(watchlist_match_ids)]
            else:
                rows = []
        if source_name:
            rows = [item for item in rows if item.source_name == source_name]
        if search:
            pattern = search.lower()
            rows = [
                item for item in rows
                if pattern in (item.title or "").lower() or pattern in (item.content_text or item.excerpt or "").lower()
            ]
        if recent_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
            rows = [item for item in rows if item.published_at >= cutoff]

        representatives = self._representative_news_items(rows, sort_mode="importance")
        sorted_items = self._sort_news_items(representatives, sort_mode=sort_mode, watchlist_match_ids=watchlist_match_ids)
        total = len(sorted_items)
        return {"items": sorted_items[offset : offset + limit], "total": total}

    def _news_items_for_company(self, company: Company, *, sort_mode: str = "importance") -> list[NewsItem]:
        rows = self.session.scalars(select(NewsItem).order_by(NewsItem.published_at.desc(), NewsItem.id.desc())).all()
        filtered = [item for item in rows if company.id in set(item.company_tag_ids or [])]
        representatives = self._representative_news_items(filtered, sort_mode=sort_mode)
        return self._sort_news_items(representatives, sort_mode=sort_mode, watchlist_match_ids={company.id})
