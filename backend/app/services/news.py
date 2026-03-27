from __future__ import annotations

import hashlib
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
from app.services.ranking import company_market_cap_percentiles, compute_news_scores
from app.services.summarization import OpenAISummarizer


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
        market_caps = company_market_cap_percentiles(self.session)
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
                mentioned = self._detect_companies(f"{title}\n{article_text}", company_aliases)
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
                    topic_tags=topic_tags,
                )
                self.session.add(news_item)
                self.session.flush()

                summary = self.summarizer.summarize(
                    kind="news",
                    title=title,
                    text=article_text,
                    company_name=", ".join(mentioned) if mentioned else None,
                    evidence_sections=topic_tags,
                )
                news_item.summary_json = summary.model_dump()
                news_item.summary_model = self.settings.openai_model if self.settings.openai_api_key else "fallback-local"
                news_item.summary_prompt_version = self.settings.summary_prompt_version
                news_item.summary_status = "complete"
                news_item.summary_attempts += 1

                company_scores = [
                    market_caps.get(company.id, 0.0)
                    for company in companies
                    if company.name in mentioned or (company.ticker and company.ticker in mentioned)
                ]
                market_score = max(company_scores) if company_scores else 0.0
                scores = compute_news_scores(news_item, company_market_cap_score=market_score)
                news_item.importance_score = float(scores["importance_score"])
                news_item.market_cap_score = float(scores["market_cap_score"])
                news_item.composite_score = float(scores["composite_score"])
                news_item.score_explanation = dict(scores["score_explanation"])
                inserted += 1

        self.session.commit()
        return inserted

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
            summary=summary.get("summary", ""),
            key_takeaways=summary.get("key_takeaways", []),
        )

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
    def _company_aliases(companies: Iterable[Company]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for company in companies:
            aliases[company.name.lower()] = company.name
            if company.ticker:
                aliases[company.ticker.lower()] = company.ticker
            normalized = company.name.lower().replace(",", "").replace(".", "")
            aliases[normalized] = company.name
        return aliases

    @staticmethod
    def _detect_companies(text: str, aliases: dict[str, str]) -> list[str]:
        lowered = text.lower()
        matches = []
        for alias, canonical in aliases.items():
            if alias and alias in lowered:
                matches.append(canonical)
        seen = []
        for match in matches:
            if match not in seen:
                seen.append(match)
        return seen[:10]

    def _news_items_for_company(self, company: Company) -> list[NewsItem]:
        aliases = {company.name}
        if company.ticker:
            aliases.add(company.ticker)

        rows = self.session.scalars(select(NewsItem).order_by(NewsItem.composite_score.desc())).all()
        return [item for item in rows if aliases.intersection(set(item.mentioned_companies or []))]
