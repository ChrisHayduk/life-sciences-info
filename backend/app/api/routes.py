from __future__ import annotations

from contextlib import contextmanager, suppress
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.jobs import (
    run_build_daily_digest,
    run_ensure_db_indexes,
    run_ingest_news,
    run_poll_regulatory_events,
    run_poll_sec_filings,
    run_poll_trials,
    run_refresh_market_caps,
    run_resummarize_item,
    run_retag_news_companies,
    run_send_daily_digest_email,
    run_summarize_pending,
)
from app.models import ClinicalTrial, Company, Digest, Filing, NewsItem, RegulatoryEvent, SummaryUsage, Watchlist
from app.schemas import (
    AdminActionResponse,
    CompanyDetailResponse,
    CompanyResponse,
    DashboardResponse,
    SummaryBudgetOverview,
    SummaryBudgetSnapshot,
    WatchlistBriefingResponse,
)
from app.services.clinical_trials import ClinicalTrialsService
from app.services.catalysts import CatalystService
from app.services.events import event_stream
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.regulatory_events import RegulatoryEventService
from app.services.ranking import compute_company_trend
from app.services.storage import ObjectStore
from app.services.summary_budget import SummaryBudgetService
from app.services.universe import UniverseService, describe_universe_reason
from app.services.watchlists import WatchlistService

router = APIRouter()


def _normalize_origin(value: str | None) -> str | None:
    from urllib.parse import urlparse

    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    stripped = value.strip().rstrip("/")
    return stripped or None


def _sse_cors_headers(request: Request) -> dict[str, str]:
    origin = _normalize_origin(request.headers.get("origin"))
    settings = get_settings()
    allowed = {_normalize_origin(item) for item in settings.cors_origins}
    allowed.add(_normalize_origin(settings.frontend_base_url))
    allowed = {item for item in allowed if item}

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if origin and (origin in allowed or (origin.endswith(".vercel.app") and (_normalize_origin(settings.frontend_base_url) or "").endswith(".vercel.app"))):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return headers


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


def _close_if_possible(value) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


@contextmanager
def _service_scope(*services):
    try:
        yield services[0] if len(services) == 1 else services
    finally:
        for service in reversed(services):
            _close_if_possible(service)


def _summary_budget_overview(session: Session) -> SummaryBudgetOverview:
    budget = SummaryBudgetService(session)
    spend_by_model = {
        model: payload
        for model, payload in budget.spend_by_model_since(1).items()
    }
    recent_rows = budget.rows_since(7)
    total_used_usd = (
        budget.used_cost_today("filing")
        + budget.used_cost_today("news")
        + budget.used_cost_today("override")
        + budget.used_cost_today("diff")
        + budget.used_cost_today("digest")
    )
    total_limit_usd = (
        budget.budget_usd_for_kind("filing")
        + budget.budget_usd_for_kind("news")
        + budget.budget_usd_for_kind("override")
        + budget.budget_usd_for_kind("diff")
        + budget.budget_usd_for_kind("digest")
    )
    total_cost_7d = sum(float(row.estimated_cost_usd or 0.0) for row in recent_rows)
    return SummaryBudgetOverview(
        filing=SummaryBudgetSnapshot(**budget.snapshot("filing")),
        news=SummaryBudgetSnapshot(**budget.snapshot("news")),
        override=SummaryBudgetSnapshot(**budget.snapshot("override")),
        diff=SummaryBudgetSnapshot(**budget.snapshot("diff")),
        digest=SummaryBudgetSnapshot(**budget.snapshot("digest")),
        total_used_usd=round(total_used_usd, 4),
        total_limit_usd=round(total_limit_usd, 4),
        total_remaining_usd=round(max(total_limit_usd - total_used_usd, 0.0), 4),
        seven_day_average_usd=round(total_cost_7d / 7.0, 4),
        spend_by_model=spend_by_model,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    with _service_scope(
        FilingService(session),
        NewsService(session),
        DigestService(session),
        ClinicalTrialsService(session),
        RegulatoryEventService(session),
        WatchlistService(session),
    ) as services:
        filing_service, news_service, digest_service, trials_service, regulatory_service, watchlist_service = services
        digests = digest_service.list_digests(limit=1)
        recent_trials = trials_service.list_trials(limit=5)
        latest_filings = filing_service.list_filings(limit=5, recent_days=1, sort_mode="freshness")
        latest_news = news_service.list_news(limit=5, recent_days=1, sort_mode="freshness")
        important_filings = filing_service.list_filings(limit=5, recent_days=90, sort_mode="importance")
        important_news = news_service.list_news(limit=5, recent_days=14, sort_mode="importance")
        filing_queue_counts = filing_service.pending_queue_counts()
        news_queue_counts = news_service.pending_queue_counts()
        return DashboardResponse(
            latest_filings=latest_filings,
            latest_news=latest_news,
            important_filings=important_filings,
            important_news=important_news,
            top_filings=important_filings,
            top_news=important_news,
            watchlist_highlights=watchlist_service.build_dashboard_highlights(limit_watchlists=3, limit_items=3),
            upcoming_regulatory_events=regulatory_service.list_timeline_events(
                limit=6,
                include_past_days=14,
                upcoming_days=180,
            ),
            recent_trials=recent_trials,
            latest_digest=digests[0] if digests else None,
            counts={
                "companies": session.scalar(select(func.count()).select_from(Company)) or 0,
                "filings": session.scalar(select(func.count()).select_from(Filing)) or 0,
                "news_items": session.scalar(select(func.count()).select_from(NewsItem)) or 0,
                "regulatory_events": session.scalar(select(func.count()).select_from(RegulatoryEvent)) or 0,
                "clinical_trials": session.scalar(select(func.count()).select_from(ClinicalTrial)) or 0,
                "digests": session.scalar(select(func.count()).select_from(Digest)) or 0,
            },
            ai_budget=_summary_budget_overview(session),
            queue_counts={**filing_queue_counts, **news_queue_counts},
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

    with _service_scope(
        FilingService(session),
        NewsService(session),
        WatchlistService(session),
        CatalystService(session),
        ClinicalTrialsService(session),
    ) as services:
        filing_service, news_service, watchlist_service, catalyst_service, trials_service = services
        recent_filings = filing_service.list_filings(limit=20, company_id=company.id)
        recent_news = news_service.list_news_for_company(company, limit=20)
        base = build_company_response(company)

        filings_count = session.scalar(select(func.count()).select_from(Filing).where(Filing.company_id == company.id)) or 0
        news_count = news_service.count_news_for_company(company)

        trend = compute_company_trend(session, company.id)
        pipeline = trials_service.list_trials_for_company_grouped(company.id)
        timeline = watchlist_service.build_company_timeline(company.id, limit=25)
        latest_filing = max(recent_filings, key=lambda item: (item.filed_at, item.composite_score), default=None)
        latest_news = max(recent_news, key=lambda item: (item.published_at, item.composite_score), default=None)
        latest_trial_items = trials_service.list_trials(company_id=company.id, limit=1)
        latest_trial = latest_trial_items[0] if latest_trial_items else None
        catalysts = catalyst_service.build_company_catalysts(company.id, limit=6)
        business_summary = ""
        change_summary: list[str] = []
        catalyst_summary = catalyst_service.summarize_catalysts(catalysts, limit=4)
        if latest_filing:
            filing_row = session.get(Filing, latest_filing.id)
            business_summary = (
                ((filing_row.parsed_sections or {}).get("business") or "")[:420].strip()
                if filing_row
                else ""
            )
            summary_json = (filing_row.summary_json or {}) if filing_row else {}
            change_summary = (summary_json.get("material_changes") or summary_json.get("key_takeaways") or [])[:4]
        if not business_summary:
            business_summary = company.sic_description or "Covered public life sciences issuer."

        return CompanyDetailResponse(
            **base.model_dump(),
            market_cap_updated_at=company.market_cap_updated_at,
            filings_count=filings_count,
            news_count=news_count,
            recent_filings=recent_filings,
            recent_news=recent_news,
            timeline=timeline,
            latest_filing=latest_filing,
            latest_news=latest_news,
            latest_trial=latest_trial,
            business_summary=business_summary,
            change_summary=change_summary,
            catalyst_summary=catalyst_summary[:4],
            catalysts=catalysts,
            trend=trend,
            pipeline=pipeline,
        )


@router.get("/companies/{company_id}/timeline")
def company_timeline(company_id: int, limit: int = 30, session: Session = Depends(get_session)):
    company = session.get(Company, company_id)
    if not company or not company.is_active:
        raise HTTPException(status_code=404, detail="Company not found")
    with _service_scope(WatchlistService(session)) as watchlist_service:
        return watchlist_service.build_company_timeline(company_id, limit=limit)


@router.get("/filings")
def list_filings(
    company_id: int | None = None,
    watchlist_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    form_type: str | None = None,
    search: str | None = None,
    sort_by: str = "composite_score",
    recent_days: int | None = None,
    sort_mode: str | None = None,
    session: Session = Depends(get_session),
):
    with _service_scope(FilingService(session)) as filing_service:
        result = filing_service.list_filings_paginated(
            limit=limit, offset=offset, company_id=company_id,
            form_type=form_type, search=search, sort_by=sort_by,
            recent_days=recent_days, watchlist_id=watchlist_id, sort_mode=sort_mode,
        )
        return result


@router.get("/filings/{filing_id}")
def filing_detail(filing_id: int, session: Session = Depends(get_session)):
    with _service_scope(FilingService(session)) as filing_service:
        filing = filing_service.get_filing_detail(filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        return filing


@router.post("/filings/{filing_id}/summarize", response_model=AdminActionResponse)
def summarize_filing_on_demand(filing_id: int, session: Session = Depends(get_session)) -> AdminActionResponse:
    with _service_scope(FilingService(session)) as filing_service:
        try:
            result = filing_service.summarize_item(
                filing_id,
                consume_override_budget=True,
                force=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "override_budget_exhausted":
                raise HTTPException(status_code=429, detail="Daily manual summary budget exhausted") from exc
            raise
        return AdminActionResponse(
            status="ok",
            message=(
                "Filing summary refreshed."
                if result["status"] == "summarized"
                else "Filing already has a current summary."
            ),
        )


@router.get("/news")
def list_news(
    limit: int = 50,
    offset: int = 0,
    source_name: str | None = None,
    search: str | None = None,
    sort_by: str = "composite_score",
    recent_days: int | None = None,
    watchlist_id: int | None = None,
    sort_mode: str | None = None,
    session: Session = Depends(get_session),
):
    with _service_scope(NewsService(session)) as news_service:
        result = news_service.list_news_paginated(
            limit=limit, offset=offset, source_name=source_name,
            search=search, sort_by=sort_by,
            recent_days=recent_days, watchlist_id=watchlist_id, sort_mode=sort_mode,
        )
        return result


@router.get("/regulatory-events")
def list_regulatory_events(
    company_id: int | None = None,
    limit: int = 20,
    include_past_days: int = 14,
    upcoming_days: int = 180,
    session: Session = Depends(get_session),
):
    company_ids = [company_id] if company_id is not None else None
    with _service_scope(RegulatoryEventService(session)) as regulatory_service:
        return regulatory_service.list_timeline_events(
            company_ids=company_ids,
            limit=limit,
            include_past_days=include_past_days,
            upcoming_days=upcoming_days,
        )


@router.post("/news/{news_id}/summarize", response_model=AdminActionResponse)
def summarize_news_on_demand(news_id: int, session: Session = Depends(get_session)) -> AdminActionResponse:
    with _service_scope(NewsService(session)) as news_service:
        try:
            result = news_service.summarize_item(
                news_id,
                consume_override_budget=True,
                force=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "override_budget_exhausted":
                raise HTTPException(status_code=429, detail="Daily manual summary budget exhausted") from exc
            raise
        return AdminActionResponse(
            status="ok",
            message=(
                "News summary refreshed."
                if result["status"] == "summarized"
                else "News item already has a current summary."
            ),
        )


@router.get("/digests")
def list_digests(limit: int = 20, session: Session = Depends(get_session)):
    with _service_scope(DigestService(session)) as digest_service:
        return digest_service.list_digests(limit=limit)


@router.get("/digests/{digest_id}")
def digest_detail(digest_id: int, session: Session = Depends(get_session)):
    with _service_scope(DigestService(session)) as digest_service:
        digest = digest_service.get_digest(digest_id)
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
    with _service_scope(ClinicalTrialsService(session)) as trials_service:
        return trials_service.list_trials_paginated(
            company_id=company_id, phase=phase, status=status,
            search=search, limit=limit, offset=offset,
        )


@router.get("/artifacts/filings/{filing_id}/pdf")
def filing_pdf(filing_id: int, session: Session = Depends(get_session)):
    filing = session.get(Filing, filing_id)
    if not filing or not filing.pdf_artifact_key:
        raise HTTPException(status_code=404, detail="PDF not found")
    with _service_scope(ObjectStore()) as store:
        payload = store.get_bytes(filing.pdf_artifact_key)
    return Response(content=payload, media_type="application/pdf")


@router.get("/events/stream")
async def events_sse(request: Request):
    """Server-Sent Events endpoint for real-time notifications."""
    if not get_settings().enable_event_stream:
        return Response(status_code=204, headers=_sse_cors_headers(request))
    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        headers=_sse_cors_headers(request),
    )


@router.post("/admin/sync-universe", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_sync_universe(limit: int | None = None, session: Session = Depends(get_session)) -> AdminActionResponse:
    with _service_scope(UniverseService(session)) as universe_service:
        count = universe_service.sync_universe(limit=limit)
        return AdminActionResponse(status="ok", message=f"Universe sync completed for {count} companies.")


@router.post("/admin/backfill-company/{company_id}", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_backfill_company(
    company_id: int,
    max_filings: int | None = None,
    years_back: int | None = None,
    session: Session = Depends(get_session),
) -> AdminActionResponse:
    with _service_scope(FilingService(session)) as filing_service:
        count = filing_service.backfill_company(company_id, max_filings=max_filings, years_back=years_back)
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
            f"{result['remaining_daily_budget']} filing summaries remain today "
            f"(${result['remaining_daily_budget_usd']:.2f} filing budget left)."
        ),
    )


@router.post("/admin/ingest-news", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_ingest_news(session: Session = Depends(get_session)) -> AdminActionResponse:
    result = run_ingest_news()
    return AdminActionResponse(
        status="ok",
        message=(
            f"Ingested {result['new_items']} news items, summarized {result['summarized']}, "
            f"{result['remaining_daily_budget']} news summaries remain today "
            f"(${result['remaining_daily_budget_usd']:.2f} news budget left)."
        ),
    )


@router.post("/admin/poll-regulatory-events", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_poll_regulatory_events(limit: int | None = None) -> AdminActionResponse:
    result = run_poll_regulatory_events(limit=limit)
    return AdminActionResponse(
        status="ok",
        message=(
            f"Synced {result['inserted']} new and {result['updated']} updated FDA events; "
            f"{result['tagged']} tagged to covered companies."
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


@router.post("/admin/ensure-db-indexes", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_ensure_db_indexes() -> AdminActionResponse:
    result = run_ensure_db_indexes()
    return AdminActionResponse(
        status="ok",
        message=(
            f"Ensured {result['count']} database indexes."
            + (f" {', '.join(result['indexes'])}" if result["indexes"] else "")
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
            f"{result['remaining_daily_budget']} daily budget remains "
            f"(${result['remaining_daily_budget_usd']:.2f} left)."
        ),
    )


@router.post("/admin/build-weekly-digest", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_build_digest(session: Session = Depends(get_session)) -> AdminActionResponse:
    with _service_scope(DigestService(session)) as digest_service:
        digest = digest_service.build_weekly_digest()
        return AdminActionResponse(status="ok", message=f"Built digest {digest.id}.")


@router.post("/admin/build-daily-digest", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_build_daily_digest() -> AdminActionResponse:
    digest_id = run_build_daily_digest()
    return AdminActionResponse(status="ok", message=f"Built daily digest {digest_id}.")


@router.post("/admin/send-daily-digest-email", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_send_daily_digest_email(force: bool = False) -> AdminActionResponse:
    result = run_send_daily_digest_email(force=force)
    if result["delivery_status"] == "failed":
        raise HTTPException(
            status_code=502,
            detail=f"Daily digest {result['digest_id']} email delivery failed: {result['error']}",
        )
    return AdminActionResponse(
        status="ok",
        message=(
            f"Daily digest {result['digest_id']} {result['delivery_status']}."
            f" built={result['built']}"
        ),
    )


@router.post("/admin/re-summarize/{kind}/{item_id}", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_resummarize(kind: str, item_id: int) -> AdminActionResponse:
    if kind not in {"filing", "news"}:
        raise HTTPException(status_code=400, detail="kind must be 'filing' or 'news'")
    run_resummarize_item(kind, item_id)
    return AdminActionResponse(status="ok", message=f"Re-summarization triggered for {kind} {item_id}.")


@router.post("/admin/poll-trials", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_poll_trials(limit: int | None = None, focus_tickers: str = "") -> AdminActionResponse:
    tickers = [ticker.strip().upper() for ticker in focus_tickers.split(",") if ticker.strip()]
    result = run_poll_trials(limit=limit, focus_tickers=tickers or None)
    if result["skipped"]:
        return AdminActionResponse(
            status="ok",
            message=f"Skipped trial sync for provider {result['provider']}; provider is not configured.",
        )
    return AdminActionResponse(
        status="ok",
        message=(
            f"Provider {result['provider']}: scanned {result['companies_scanned']} companies; "
            f"{result['companies_succeeded']} succeeded, {result['companies_failed']} failed; "
            f"{result['new_trials']} new trials, {result['updated_trials']} updated, "
            f"{result['pruned_trials']} pruned."
            + (" Run was partial." if result["partial"] else "")
        ),
    )


@router.get("/watchlists")
def list_watchlists(session: Session = Depends(get_session)):
    with _service_scope(WatchlistService(session)) as watchlist_service:
        return watchlist_service.list_watchlists()


@router.post("/watchlists")
def create_watchlist(
    name: str,
    description: str = "",
    company_ids: str = "",
    form_types: str = "",
    topic_tags: str = "",
    session: Session = Depends(get_session),
):
    watchlist = Watchlist(
        name=name,
        description=description or None,
        company_ids=[int(x) for x in company_ids.split(",") if x.strip()],
        form_types=[x.strip() for x in form_types.split(",") if x.strip()],
        topic_tags=[x.strip() for x in topic_tags.split(",") if x.strip()],
    )
    session.add(watchlist)
    session.commit()
    session.refresh(watchlist)
    return watchlist


@router.post("/watchlists/starter")
def create_starter_watchlists(session: Session = Depends(get_session)):
    with _service_scope(WatchlistService(session)) as watchlist_service:
        return watchlist_service.ensure_starter_watchlists()


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: int, session: Session = Depends(get_session)):
    watchlist = session.get(Watchlist, watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return watchlist


@router.post("/watchlists/{watchlist_id}/companies")
def add_companies_to_watchlist(watchlist_id: int, company_ids: str, session: Session = Depends(get_session)):
    ids = [int(value) for value in company_ids.split(",") if value.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="company_ids is required")
    with _service_scope(WatchlistService(session)) as watchlist_service:
        try:
            return watchlist_service.add_companies(watchlist_id, ids)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/watchlists/{watchlist_id}/briefing", response_model=WatchlistBriefingResponse)
def watchlist_briefing(watchlist_id: int, limit: int = 30, session: Session = Depends(get_session)):
    with _service_scope(WatchlistService(session)) as watchlist_service:
        try:
            return watchlist_service.build_watchlist_briefing(watchlist_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/watchlists/{watchlist_id}/feed", response_model=WatchlistBriefingResponse)
def watchlist_feed(watchlist_id: int, limit: int = 30, session: Session = Depends(get_session)):
    return watchlist_briefing(watchlist_id, limit=limit, session=session)


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
            "reasoning_tokens": row.reasoning_tokens,
            "cached_input_tokens": row.cached_input_tokens,
            "total_tokens": row.prompt_tokens + row.completion_tokens,
            "estimated_cost_usd": round(row.estimated_cost_usd, 4),
            "model_breakdown": row.model_breakdown or {},
        })

    total_calls = sum(r.count for r in rows)
    total_tokens = sum(r.prompt_tokens + r.completion_tokens for r in rows)
    total_cost = sum(r.estimated_cost_usd for r in rows)
    budget_service = SummaryBudgetService(session)
    spend_by_model = budget_service.spend_by_model_since(days)

    return {
        "period_days": days,
        "daily": daily_stats,
        "totals": {
            "calls": total_calls,
            "tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 4),
        },
        "budget": {
            "today": _summary_budget_overview(session).model_dump(),
            "rolling_average_usd": round(total_cost / max(days, 1), 4),
        },
        "by_model": spend_by_model,
    }
