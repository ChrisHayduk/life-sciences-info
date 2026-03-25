from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Filing, NewsItem

MATERIAL_EVENT_KEYWORDS = {
    "approval": 1.0,
    "fda": 0.8,
    "phase 3": 0.9,
    "guidance": 0.8,
    "acquisition": 0.8,
    "manufacturing": 0.6,
    "warning letter": 0.9,
    "restructuring": 0.7,
    "layoff": 0.6,
    "commercial launch": 0.8,
}


def company_market_cap_percentiles(session: Session) -> dict[int, float]:
    companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
    ranked = [company for company in companies if company.market_cap]
    ranked.sort(key=lambda company: company.market_cap or 0)
    if not ranked:
        return {}
    if len(ranked) == 1:
        return {ranked[0].id: 100.0}
    total = len(ranked) - 1
    return {company.id: (index / total) * 100.0 for index, company in enumerate(ranked)}


def novelty_score(current_text: str | None, prior_text: str | None) -> float:
    if not current_text:
        return 0.0
    if not prior_text:
        return 65.0
    ratio = SequenceMatcher(None, current_text[:15000], prior_text[:15000]).ratio()
    return round((1 - ratio) * 100.0, 2)


def _extract_numbers(text: str | None) -> list[float]:
    if not text:
        return []
    values = []
    for raw in re.findall(r"\$?\b\d+(?:\.\d+)?%?\b", text):
        normalized = raw.replace("$", "").replace("%", "")
        try:
            values.append(float(normalized))
        except ValueError:
            continue
    return values[:200]


def quantitative_delta_score(current_text: str | None, prior_text: str | None) -> float:
    current_values = _extract_numbers(current_text)
    prior_values = _extract_numbers(prior_text)
    if not current_values:
        return 10.0
    if not prior_values:
        return 55.0
    current_mean = sum(current_values) / len(current_values)
    prior_mean = sum(prior_values) / len(prior_values)
    if prior_mean == 0:
        return 60.0
    delta = abs(current_mean - prior_mean) / max(abs(prior_mean), 1.0)
    return round(min(delta * 100.0, 100.0), 2)


def material_event_score(text: str | None) -> float:
    if not text:
        return 0.0
    lowered = text.lower()
    score = sum(weight for keyword, weight in MATERIAL_EVENT_KEYWORDS.items() if keyword in lowered)
    return round(min(score * 30.0, 100.0), 2)


def recency_score(published_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age_hours = max((now - published_at).total_seconds() / 3600.0, 0.0)
    if age_hours <= 24:
        return 100.0
    if age_hours <= 72:
        return 80.0
    if age_hours <= 168:
        return 60.0
    return max(10.0, 60.0 - math.log(age_hours, 2) * 5.0)


def compute_filing_scores(
    filing: Filing,
    *,
    company_market_cap_score: float,
    prior_filing: Filing | None = None,
) -> dict[str, float | str | dict]:
    llm_materiality = float((filing.summary_json or {}).get("importance_score", 0.0))
    novelty = novelty_score(filing.raw_text, prior_filing.raw_text if prior_filing else None)
    quantitative = quantitative_delta_score(filing.raw_text, prior_filing.raw_text if prior_filing else None)
    material = material_event_score(filing.raw_text)
    impact = round((0.30 * novelty) + (0.25 * quantitative) + (0.20 * material) + (0.25 * llm_materiality), 2)
    composite = round((0.35 * company_market_cap_score) + (0.65 * impact), 2)
    confidence = "high" if company_market_cap_score else "degraded"
    return {
        "market_cap_score": round(company_market_cap_score, 2),
        "importance_score": round(llm_materiality, 2),
        "impact_score": impact,
        "composite_score": composite,
        "score_confidence": confidence,
        "score_explanation": {
            "components": {
                "market_cap": round(company_market_cap_score, 2),
                "novelty": novelty,
                "quantitative_delta": quantitative,
                "material_events": material,
                "llm_materiality": round(llm_materiality, 2),
            },
            "rationale": [
                "Composite = 0.35 market cap percentile + 0.65 impact score",
                "Impact = 0.30 novelty + 0.25 quantitative delta + 0.20 material events + 0.25 LLM materiality",
            ],
            "confidence": confidence,
        },
    }


def compute_news_scores(
    news_item: NewsItem,
    *,
    company_market_cap_score: float,
    now: datetime | None = None,
) -> dict[str, float | dict]:
    importance = float((news_item.summary_json or {}).get("importance_score", 0.0))
    recency = recency_score(news_item.published_at, now=now)
    weights = {"importance": 0.50, "source": 0.20, "market": 0.20, "recency": 0.10}
    if not news_item.mentioned_companies:
        weights = {"importance": 0.625, "source": 0.25, "market": 0.0, "recency": 0.125}
    composite = round(
        (weights["importance"] * importance)
        + (weights["source"] * (news_item.source_weight * 100.0))
        + (weights["market"] * company_market_cap_score)
        + (weights["recency"] * recency),
        2,
    )
    return {
        "importance_score": round(importance, 2),
        "market_cap_score": round(company_market_cap_score, 2),
        "composite_score": composite,
        "score_explanation": {
            "components": {
                "llm_importance": round(importance, 2),
                "source_weight": round(news_item.source_weight * 100.0, 2),
                "market_cap_weight": round(company_market_cap_score, 2),
                "recency": round(recency, 2),
            },
            "rationale": [
                "News score = 0.50 LLM importance + 0.20 source/topic + 0.20 company market-cap + 0.10 recency",
                "Weights renormalize when no covered company is mentioned.",
            ],
            "confidence": "high" if news_item.mentioned_companies else "medium",
        },
    }
