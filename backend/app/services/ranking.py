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

FILING_FORM_BASE_SCORES = {
    "10-K": 95.0,
    "20-F": 95.0,
    "40-F": 95.0,
    "10-Q": 85.0,
    "8-K": 75.0,
    "6-K": 65.0,
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
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
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
    has_market_cap: bool = True,
    now: datetime | None = None,
    prior_filing: Filing | None = None,
) -> dict[str, float | str | dict]:
    llm_materiality = float((filing.summary_json or {}).get("importance_score", 0.0))
    novelty = novelty_score(filing.raw_text, prior_filing.raw_text if prior_filing else None)
    quantitative = quantitative_delta_score(filing.raw_text, prior_filing.raw_text if prior_filing else None)
    material = material_event_score(filing.raw_text)
    recency = recency_score(filing.filed_at, now=now)
    impact = round((0.25 * novelty) + (0.20 * quantitative) + (0.15 * material) + (0.15 * llm_materiality) + (0.25 * recency), 2)
    composite = round((0.20 * company_market_cap_score) + (0.50 * impact) + (0.30 * recency), 2)
    confidence = "high" if has_market_cap else "degraded"
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
                "recency": round(recency, 2),
            },
            "rationale": [
                "Composite = 0.20 market cap percentile + 0.50 impact score + 0.30 recency",
                "Impact = 0.25 novelty + 0.20 quantitative delta + 0.15 material events + 0.15 LLM materiality + 0.25 recency",
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
    weights = {"importance": 0.35, "source": 0.15, "market": 0.15, "recency": 0.35}
    if not news_item.mentioned_companies:
        weights = {"importance": 0.50, "source": 0.20, "market": 0.0, "recency": 0.30}
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
                "News score = 0.35 LLM importance + 0.15 source/topic + 0.15 company market-cap + 0.35 recency",
                "Weights renormalize when no covered company is mentioned.",
            ],
            "confidence": "high" if news_item.mentioned_companies else "medium",
        },
    }


def compute_pending_filing_scores(
    filing: Filing,
    *,
    company_market_cap_score: float,
    has_market_cap: bool = True,
    now: datetime | None = None,
) -> dict[str, float | str | dict]:
    form_score = FILING_FORM_BASE_SCORES.get(filing.normalized_form_type, 55.0)
    material = material_event_score(filing.raw_text)
    recency = recency_score(filing.filed_at, now=now)
    importance = round((0.60 * form_score) + (0.40 * material), 2)
    impact = round((0.35 * form_score) + (0.30 * material) + (0.35 * recency), 2)
    composite = round((0.35 * company_market_cap_score) + (0.40 * impact) + (0.25 * recency), 2)
    confidence = "high" if has_market_cap else "degraded"
    return {
        "market_cap_score": round(company_market_cap_score, 2),
        "importance_score": importance,
        "impact_score": impact,
        "composite_score": composite,
        "score_confidence": confidence,
        "score_explanation": {
            "components": {
                "market_cap": round(company_market_cap_score, 2),
                "form_weight": round(form_score, 2),
                "material_events": round(material, 2),
                "recency": round(recency, 2),
            },
            "rationale": [
                "Pending summary rank uses market cap, filing form weight, material keywords, and recency.",
            ],
            "confidence": confidence,
        },
    }


def compute_pending_news_scores(
    news_item: NewsItem,
    *,
    company_market_cap_score: float,
    now: datetime | None = None,
) -> dict[str, float | dict]:
    keyword_signal = material_event_score(f"{news_item.title or ''} {news_item.content_text or news_item.excerpt or ''}")
    recency = recency_score(news_item.published_at, now=now)
    importance = round((0.55 * keyword_signal) + (0.45 * (news_item.source_weight * 100.0)), 2)
    composite = round(
        (0.30 * importance)
        + (0.25 * (news_item.source_weight * 100.0))
        + (0.20 * company_market_cap_score)
        + (0.25 * recency),
        2,
    )
    return {
        "importance_score": importance,
        "market_cap_score": round(company_market_cap_score, 2),
        "composite_score": composite,
        "score_explanation": {
            "components": {
                "keyword_signal": round(keyword_signal, 2),
                "source_weight": round(news_item.source_weight * 100.0, 2),
                "market_cap_weight": round(company_market_cap_score, 2),
                "recency": round(recency, 2),
            },
            "rationale": [
                "Pending news rank uses source weight, keyword signal, company market cap, and recency.",
            ],
            "confidence": "medium",
        },
    }


def compute_company_trend(session: Session, company_id: int, filing_count: int = 4) -> dict:
    """Analyze recent filings to detect if a company's risk profile is trending."""
    filings = session.scalars(
        select(Filing)
        .where(Filing.company_id == company_id, Filing.summary_status == "complete")
        .order_by(Filing.filed_at.desc())
        .limit(filing_count)
    ).all()

    if len(filings) < 2:
        return {"direction": "insufficient_data", "trend_score": 0, "risk_trend": "stable", "opportunity_trend": "stable", "filings_analyzed": len(filings)}

    # Compute trends in composite scores
    scores = [f.composite_score for f in reversed(filings)]
    score_deltas = [scores[i] - scores[i - 1] for i in range(1, len(scores))]
    avg_delta = sum(score_deltas) / len(score_deltas) if score_deltas else 0

    # Count risk and opportunity flags across filings
    risk_counts = [len((f.summary_json or {}).get("risk_flags", [])) for f in reversed(filings)]
    opp_counts = [len((f.summary_json or {}).get("opportunity_flags", [])) for f in reversed(filings)]

    risk_deltas = [risk_counts[i] - risk_counts[i - 1] for i in range(1, len(risk_counts))]
    opp_deltas = [opp_counts[i] - opp_counts[i - 1] for i in range(1, len(opp_counts))]

    avg_risk_delta = sum(risk_deltas) / len(risk_deltas) if risk_deltas else 0
    avg_opp_delta = sum(opp_deltas) / len(opp_deltas) if opp_deltas else 0

    # Determine direction
    if avg_delta > 5:
        direction = "improving"
    elif avg_delta < -5:
        direction = "deteriorating"
    else:
        direction = "stable"

    risk_trend = "increasing" if avg_risk_delta > 0.5 else ("decreasing" if avg_risk_delta < -0.5 else "stable")
    opp_trend = "increasing" if avg_opp_delta > 0.5 else ("decreasing" if avg_opp_delta < -0.5 else "stable")

    return {
        "direction": direction,
        "trend_score": round(avg_delta, 2),
        "risk_trend": risk_trend,
        "opportunity_trend": opp_trend,
        "filings_analyzed": len(filings),
    }
