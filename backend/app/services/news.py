from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, NewsItem
from app.schemas import NewsItemResponse
from app.services.constants import NEWS_FEEDS
from app.services.ranking import company_market_cap_percentiles, compute_news_scores, compute_pending_news_scores
from app.services.summary_budget import SummaryBudgetService
from app.services.summarization import OpenAISummarizer

COMPANY_TAG_LIMIT = 10
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
MULTISPACE_RE = re.compile(r"\s+")


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
    return BeautifulSoup(unescape(value or ""), "html.parser").get_text(" ", strip=True)


def _normalize_company_text(value: str) -> str:
    normalized = NON_ALNUM_RE.sub(" ", (value or "").lower())
    return MULTISPACE_RE.sub(" ", normalized).strip()


class NewsService:
    def __init__(
        self,
        session: Session,
        summarizer: OpenAISummarizer | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.session = session
        self.summarizer = summarizer or OpenAISummarizer()
        self.http_client = http_client or httpx.Client(timeout=get_settings().source_fetch_timeout_seconds, follow_redirects=True)
        self.settings = get_settings()

    def ingest_feeds(self) -> int:
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        company_aliases = self._company_aliases(companies)
        inserted = 0

        for feed in NEWS_FEEDS:
            parsed = feedparser.parse(feed["feed_url"])
            for entry in parsed.entries:
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
                article_text = self._fetch_article_text(canonical_url) or excerpt or title
                mentioned, company_tag_ids = self._detect_companies(f"{title}\n{article_text}", company_aliases)
                topic_tags = sorted(set(feed["topic_tags"] + self._infer_topics(title, article_text)))

                news_item = NewsItem(
                    source_name=feed["name"],
                    source_weight=feed["source_weight"],
                    feed_url=feed["feed_url"],
                    title=title,
                    canonical_url=canonical_url,
                    excerpt=excerpt,
                    content_text=article_text,
                    published_at=_published_at(entry),
                    article_hash=article_hash,
                    mentioned_companies=mentioned,
                    company_tag_ids=company_tag_ids,
                    topic_tags=topic_tags,
                )
                self.session.add(news_item)
                self.session.flush()
                news_item.summary_status = "pending"
                self._apply_scores(news_item, companies)
                inserted += 1

        self.session.commit()
        return inserted

    def summarize_pending(self, *, limit: int | None = None, automated: bool = True) -> dict[str, int]:
        budget_service = SummaryBudgetService(self.session)
        remaining_daily = budget_service.remaining("news") if automated and self.settings.openai_api_key else max(limit or 0, self.settings.max_news_summaries_per_run)
        if automated and self.settings.openai_api_key:
            effective_limit = min(limit or self.settings.max_news_summaries_per_run, self.settings.max_news_summaries_per_run, remaining_daily)
        else:
            effective_limit = limit or self.settings.max_news_summaries_per_run

        if effective_limit <= 0:
            return {"summarized": 0, "remaining_daily_budget": remaining_daily}

        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.news_summary_backlog_days)
        candidates = self.session.scalars(
            select(NewsItem)
            .where(NewsItem.summary_status.in_(["pending", "failed"]), NewsItem.summary_attempts < 3)
            .order_by(NewsItem.composite_score.desc(), NewsItem.published_at.desc())
        ).all()

        summarized = 0
        for news_item in candidates:
            published_at = news_item.published_at
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            if automated and published_at < cutoff:
                continue
            try:
                self._apply_summary(news_item, trigger="auto" if automated else "manual")
                self._apply_scores(news_item, companies)
            except Exception:
                news_item.summary_status = "failed"
                news_item.summary_attempts += 1
                continue
            summarized += 1
            if summarized >= effective_limit:
                break

        if automated and self.settings.openai_api_key:
            budget_service.record("news", summarized)
        self.session.commit()
        remaining = budget_service.remaining("news") if self.settings.openai_api_key else 0
        return {"summarized": summarized, "remaining_daily_budget": remaining}

    def list_news(self, limit: int = 50, recent_days: int | None = None) -> list[NewsItemResponse]:
        query = select(NewsItem).order_by(NewsItem.composite_score.desc(), NewsItem.published_at.desc())
        if recent_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
            query = query.where(NewsItem.published_at >= cutoff)
        rows = self.session.scalars(query.limit(limit)).all()
        return [self._to_response(item) for item in rows]

    def list_news_for_company(self, company: Company, limit: int = 20) -> list[NewsItemResponse]:
        matches = self._news_items_for_company(company)
        return [self._to_response(item) for item in matches[:limit]]

    def count_news_for_company(self, company: Company) -> int:
        return len(self._news_items_for_company(company))

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
            topic_tags=item.topic_tags or [],
            importance_score=item.importance_score,
            market_cap_score=item.market_cap_score,
            composite_score=item.composite_score,
            score_explanation=item.score_explanation or {},
            summary_status=item.summary_status,
            summary=summary.get("summary", ""),
            key_takeaways=summary.get("key_takeaways", []),
        )

    def _apply_summary(self, news_item: NewsItem, *, trigger: str) -> None:
        summary = self.summarizer.summarize(
            kind="news",
            title=news_item.title,
            text=news_item.content_text or news_item.excerpt or news_item.title,
            company_name=", ".join(news_item.mentioned_companies) if news_item.mentioned_companies else None,
            evidence_sections=news_item.topic_tags or [],
        )
        news_item.summary_json = summary.model_dump()
        news_item.summary_model = self.settings.openai_model if self.settings.openai_api_key else "fallback-local"
        news_item.summary_prompt_version = self.settings.summary_prompt_version
        news_item.summary_status = "complete"
        news_item.summary_attempts += 1
        news_item.extra_metadata = {**(news_item.extra_metadata or {}), "summary_trigger": trigger}

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

    def _fetch_article_text(self, url: str) -> str:
        if not url:
            return ""
        try:
            response = self.http_client.get(url)
            response.raise_for_status()
        except Exception:
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")
        if article:
            return article.get_text(" ", strip=True)
        paragraphs = [tag.get_text(" ", strip=True) for tag in soup.find_all("p")]
        return " ".join(paragraphs[:25])

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
    def _company_aliases(companies: Iterable[Company]) -> list[tuple[str, int, str]]:
        aliases: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int, str]] = set()
        for company in companies:
            candidates = [(company.name, company.name)]
            if company.ticker:
                candidates.append((company.ticker, company.ticker))
            for raw_alias, mention_value in candidates:
                normalized = _normalize_company_text(raw_alias)
                if not normalized:
                    continue
                entry = (normalized, company.id, mention_value)
                if entry in seen:
                    continue
                seen.add(entry)
                aliases.append(entry)
        aliases.sort(key=lambda item: (-len(item[0]), item[0], item[1]))
        return aliases

    @staticmethod
    def _detect_companies(text: str, aliases: list[tuple[str, int, str]]) -> tuple[list[str], list[int]]:
        normalized_text = f" {_normalize_company_text(text)} "
        mentioned_companies: list[str] = []
        company_tag_ids: list[int] = []
        for alias, company_id, mention_value in aliases:
            if not alias or f" {alias} " not in normalized_text:
                continue
            if company_id not in company_tag_ids:
                if len(company_tag_ids) >= COMPANY_TAG_LIMIT:
                    continue
                company_tag_ids.append(company_id)
            if mention_value not in mentioned_companies:
                mentioned_companies.append(mention_value)
        return mentioned_companies, company_tag_ids

    def _news_items_for_company(self, company: Company) -> list[NewsItem]:
        rows = self.session.scalars(select(NewsItem).order_by(NewsItem.composite_score.desc())).all()
        return [item for item in rows if company.id in set(item.company_tag_ids or [])]
