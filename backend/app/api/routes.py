from __future__ import annotations

from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.jobs import (
    run_ingest_news,
    run_poll_sec_filings,
    run_refresh_market_caps,
    run_resummarize_item,
    run_retag_news_companies,
    run_summarize_pending,
)
from app.models import ClinicalTrial, Company, Digest, Filing, NewsItem, SummaryUsage
from app.schemas import AdminActionResponse, CompanyDetailResponse, CompanyResponse, DashboardResponse
from app.services.clinical_trials import ClinicalTrialsService
from app.services.events import event_stream
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.ranking import compute_company_trend
from app.services.storage import ObjectStore
from app.services.universe import UniverseService, describe_universe_reason

router = APIRouter()


def build_company_response(company: Company) -> CompanyResponse:
    return CompanyResponse(
        id=company.id,
        cik=company.cik,
        ticker=company.ticker,
        name=company.name,
        exchange=company.exchange,
        sic=company.sic,
        sic_description=company.sic_description,
        market_cap=company.market_cap,
        market_cap_currency=company.market_cap_currency,
        market_cap_source=company.market_cap_source,
        universe_reason=company.universe_reason,
        universe_reason_label=describe_universe_reason(company.universe_reason),
        is_active=company.is_active,
    )


def require_admin_token(
    x_admin_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = get_settings().admin_api_token
    if not expected:
        return
    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()
    presented = x_admin_token or bearer_token
    if not presented or not compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    filing_service = FilingService(session)
    news_service = NewsService(session)
    digest_service = DigestService(session)
    trials_service = ClinicalTrialsService(session)
    digests = digest_service.list_digests(limit=1)
    recent_trials = trials_service.list_trials(limit=5)
    return DashboardResponse(
        top_filings=filing_service.list_filings(limit=5, recent_days=365),
        top_news=news_service.list_news(limit=5, recent_days=30),
        recent_trials=recent_trials,
        latest_digest=digests[0] if digests else None,
        counts={
            "companies": session.scalar(select(func.count()).select_from(Company)) or 0,
            "filings": session.scalar(select(func.count()).select_from(Filing)) or 0,
            "news_items": session.scalar(select(func.count()).select_from(NewsItem)) or 0,
            "clinical_trials": session.scalar(select(func.count()).select_from(ClinicalTrial)) or 0,
            "digests": session.scalar(select(func.count()).select_from(Digest)) or 0,
        },
    )


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    search: str | None = None,
    session: Session = Depends(get_session),
) -> list[CompanyResponse]:
    query = select(Company).where(Company.is_active.is_(True))
    if search:
        pattern = f"%{search}%"
        query = query.where(
            Company.name.ilike(pattern) | Company.ticker.ilike(pattern)
        )
    companies = session.scalars(query).all()
    companies.sort(key=lambda company: company.market_cap or 0, reverse=True)
    return [build_company_response(company) for company in companies]


@router.get("/companies/{company_id}", response_model=CompanyDetailResponse)
def company_detail(company_id: int, session: Session = Depends(get_session)) -> CompanyDetailResponse:
    company = session.get(Company, company_id)
    if not company or not company.is_active:
        raise HTTPException(status_code=404, detail="Company not found")

    filing_service = FilingService(session)
    news_service = NewsService(session)
    recent_filings = filing_service.list_filings(limit=20, company_id=company.id)
    recent_news = news_service.list_news_for_company(company, limit=20)
    base = build_company_response(company)

    filings_count = session.scalar(select(func.count()).select_from(Filing).where(Filing.company_id == company.id)) or 0
    news_count = news_service.count_news_for_company(company)

    trend = compute_company_trend(session, company.id)
    trials_service = ClinicalTrialsService(session)
    pipeline = trials_service.list_trials_for_company_grouped(company.id)

    return CompanyDetailResponse(
        **base.model_dump(),
        market_cap_updated_at=company.market_cap_updated_at,
        filings_count=filings_count,
        news_count=news_count,
        recent_filings=recent_filings,
        recent_news=recent_news,
        trend=trend,
        pipeline=pipeline,
    )


@router.get("/filings")
def list_filings(
    company_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    form_type: str | None = None,
    search: str | None = None,
    sort_by: str = "composite_score",
    session: Session = Depends(get_session),
):
    result = FilingService(session).list_filings_paginated(
        limit=limit, offset=offset, company_id=company_id,
        form_type=form_type, search=search, sort_by=sort_by,
    )
    return result


@router.get("/filings/{filing_id}")
def filing_detail(filing_id: int, session: Session = Depends(get_session)):
    filing = FilingService(session).get_filing_detail(filing_id)
    if not filing:
        raise HTTPException(status_code=404, detail="Filing not found")
    return filing


@router.get("/news")
def list_news(
    limit: int = 50,
    offset: int = 0,
    source_name: str | None = None,
    search: str | None = None,
    sort_by: str = "composite_score",
    session: Session = Depends(get_session),
):
    result = NewsService(session).list_news_paginated(
        limit=limit, offset=offset, source_name=source_name,
        search=search, sort_by=sort_by,
    )
    return result


@router.get("/digests")
def list_digests(limit: int = 20, session: Session = Depends(get_session)):
    return DigestService(session).list_digests(limit=limit)


@router.get("/digests/{digest_id}")
def digest_detail(digest_id: int, session: Session = Depends(get_session)):
    digest = DigestService(session).get_digest(digest_id)
    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    return digest


@router.get("/trials")
def list_trials(
    company_id: int | None = None,
    phase: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    return ClinicalTrialsService(session).list_trials_paginated(
        company_id=company_id, phase=phase, status=status,
        search=search, limit=limit, offset=offset,
    )


@router.get("/artifacts/filings/{filing_id}/pdf")
def filing_pdf(filing_id: int, session: Session = Depends(get_session)):
    filing = session.get(Filing, filing_id)
    if not filing or not filing.pdf_artifact_key:
        raise HTTPException(status_code=404, detail="PDF not found")
    store = ObjectStore()
    payload = store.get_bytes(filing.pdf_artifact_key)
    return Response(content=payload, media_type="application/pdf")


@router.get("/events/stream")
async def events_sse():
    """Server-Sent Events endpoint for real-time notifications."""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/admin/sync-universe", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_sync_universe(limit: int | None = None, session: Session = Depends(get_session)) -> AdminActionResponse:
    count = UniverseService(session).sync_universe(limit=limit)
    return AdminActionResponse(status="ok", message=f"Universe sync completed for {count} companies.")


@router.post("/admin/backfill-company/{company_id}", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_backfill_company(
    company_id: int,
    max_filings: int | None = None,
    years_back: int | None = None,
    session: Session = Depends(get_session),
) -> AdminActionResponse:
    count = FilingService(session).backfill_company(company_id, max_filings=max_filings, years_back=years_back)
    return AdminActionResponse(status="ok", message=f"Backfilled {count} filings for company {company_id}.")


@router.post("/admin/refresh-market-caps", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_refresh_market_caps(count: int | None = None) -> AdminActionResponse:
    result = run_refresh_market_caps(count=count)
    return AdminActionResponse(
        status="ok",
        message=(
            f"Refreshed market caps for {result['refreshed']} companies; {result['failed']} failed. "
            f"Reranked {result['reranked_filings']} filings and {result['reranked_news']} news items."
        ),
    )


@router.post("/admin/poll-filings", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_poll_filings(session: Session = Depends(get_session)) -> AdminActionResponse:
    result = run_poll_sec_filings()
    return AdminActionResponse(
        status="ok",
        message=(
            f"Discovered {result['new_items']} new filings, summarized {result['summarized']}, "
            f"{result['remaining_daily_budget']} filing summaries remain today."
        ),
    )


@router.post("/admin/ingest-news", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_ingest_news(session: Session = Depends(get_session)) -> AdminActionResponse:
    result = run_ingest_news()
    return AdminActionResponse(
        status="ok",
        message=(
            f"Ingested {result['new_items']} news items, summarized {result['summarized']}, "
            f"{result['remaining_daily_budget']} news summaries remain today."
        ),
    )


@router.post("/admin/retag-news-companies", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_retag_news_companies(
    limit: int | None = None,
    recent_days: int | None = None,
    focus_tickers: str = "",
) -> AdminActionResponse:
    tickers = [ticker.strip().upper() for ticker in focus_tickers.split(",") if ticker.strip()]
    result = run_retag_news_companies(limit=limit, recent_days=recent_days, focus_tickers=tickers or None)
    return AdminActionResponse(
        status="ok",
        message=(
            f"Retagged company links for {result['updated']} of {result['scanned']} news items; "
            f"{result['reranked']} reranked."
        ),
    )


@router.post("/admin/summarize-pending/{kind}", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_summarize_pending(kind: str, limit: int | None = None, include_historical: bool = False) -> AdminActionResponse:
    if kind not in {"filing", "news"}:
        raise HTTPException(status_code=400, detail="kind must be 'filing' or 'news'")
    result = run_summarize_pending(kind, limit=limit, include_historical=include_historical, automated=False)
    return AdminActionResponse(
        status="ok",
        message=(
            f"Summarized {result['summarized']} pending {kind} items; "
            f"{result['remaining_daily_budget']} daily budget remains."
        ),
    )


@router.post("/admin/build-weekly-digest", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_build_digest(session: Session = Depends(get_session)) -> AdminActionResponse:
    digest = DigestService(session).build_weekly_digest()
    return AdminActionResponse(status="ok", message=f"Built digest {digest.id}.")


@router.post("/admin/re-summarize/{kind}/{item_id}", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_resummarize(kind: str, item_id: int) -> AdminActionResponse:
    if kind not in {"filing", "news"}:
        raise HTTPException(status_code=400, detail="kind must be 'filing' or 'news'")
    run_resummarize_item(kind, item_id)
    return AdminActionResponse(status="ok", message=f"Re-summarization triggered for {kind} {item_id}.")


@router.post("/admin/poll-trials", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_poll_trials(limit: int | None = None, session: Session = Depends(get_session)) -> AdminActionResponse:
    result = ClinicalTrialsService(session).poll_all_companies(limit=limit)
    return AdminActionResponse(
        status="ok",
        message=(
            f"Polled {result['companies_polled']} companies; "
            f"{result['new_trials']} new trials, {result['updated_trials']} updated."
        ),
    )


# ── Watchlist endpoints ──

from app.models import Watchlist


@router.get("/watchlists")
def list_watchlists(session: Session = Depends(get_session)):
    return session.scalars(select(Watchlist).order_by(Watchlist.created_at.desc())).all()


@router.post("/watchlists")
def create_watchlist(
    name: str,
    company_ids: str = "",
    form_types: str = "",
    topic_tags: str = "",
    session: Session = Depends(get_session),
):
    watchlist = Watchlist(
        name=name,
        company_ids=[int(x) for x in company_ids.split(",") if x.strip()],
        form_types=[x.strip() for x in form_types.split(",") if x.strip()],
        topic_tags=[x.strip() for x in topic_tags.split(",") if x.strip()],
    )
    session.add(watchlist)
    session.commit()
    session.refresh(watchlist)
    return watchlist


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: int, session: Session = Depends(get_session)):
    watchlist = session.get(Watchlist, watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return watchlist


@router.get("/watchlists/{watchlist_id}/feed")
def watchlist_feed(watchlist_id: int, limit: int = 30, session: Session = Depends(get_session)):
    """Return filings and news matching a watchlist's criteria."""
    watchlist = session.get(Watchlist, watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    filing_service = FilingService(session)
    news_service = NewsService(session)

    filings = []
    news = []
    for cid in (watchlist.company_ids or []):
        filings.extend(filing_service.list_filings(limit=10, company_id=cid))
        news.extend(news_service.list_news_for_company_by_id(cid, limit=10))

    # Deduplicate and sort by composite score
    seen_filing_ids: set[int] = set()
    unique_filings = []
    for f in sorted(filings, key=lambda x: x.composite_score, reverse=True):
        if f.id not in seen_filing_ids:
            seen_filing_ids.add(f.id)
            unique_filings.append(f)

    seen_news_ids: set[int] = set()
    unique_news = []
    for n in sorted(news, key=lambda x: x.composite_score, reverse=True):
        if n.id not in seen_news_ids:
            seen_news_ids.add(n.id)
            unique_news.append(n)

    return {
        "watchlist": watchlist,
        "filings": unique_filings[:limit],
        "news": unique_news[:limit],
    }


@router.delete("/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: int, session: Session = Depends(get_session)):
    watchlist = session.get(Watchlist, watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    session.delete(watchlist)
    session.commit()
    return {"status": "ok", "message": f"Watchlist {watchlist_id} deleted."}


# ── Usage stats ──

@router.get("/admin/usage-stats", dependencies=[Depends(require_admin_token)])
def admin_usage_stats(days: int = 7, session: Session = Depends(get_session)):
    """Return AI usage statistics for the last N days."""
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    rows = session.scalars(
        select(SummaryUsage)
        .where(SummaryUsage.usage_date >= cutoff)
        .order_by(SummaryUsage.usage_date.desc(), SummaryUsage.kind)
    ).all()

    daily_stats = []
    for row in rows:
        daily_stats.append({
            "date": row.usage_date.isoformat(),
            "kind": row.kind,
            "count": row.count,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "total_tokens": row.prompt_tokens + row.completion_tokens,
            "estimated_cost_usd": round(row.estimated_cost_usd, 4),
        })

    total_calls = sum(r.count for r in rows)
    total_tokens = sum(r.prompt_tokens + r.completion_tokens for r in rows)
    total_cost = sum(r.estimated_cost_usd for r in rows)

    return {
        "period_days": days,
        "daily": daily_stats,
        "totals": {
            "calls": total_calls,
            "tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 4),
        },
    }
