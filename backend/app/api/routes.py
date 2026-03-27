from __future__ import annotations

from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Company, Digest, Filing, NewsItem
from app.schemas import AdminActionResponse, CompanyDetailResponse, CompanyResponse, DashboardResponse
from app.jobs import run_resummarize_item
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.market_caps import MarketCapService
from app.services.news import NewsService
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
    digests = digest_service.list_digests(limit=1)
    return DashboardResponse(
        top_filings=filing_service.list_filings(limit=5, recent_days=365),
        top_news=news_service.list_news(limit=5, recent_days=30),
        latest_digest=digests[0] if digests else None,
        counts={
            "companies": session.scalar(select(func.count()).select_from(Company)) or 0,
            "filings": session.scalar(select(func.count()).select_from(Filing)) or 0,
            "news_items": session.scalar(select(func.count()).select_from(NewsItem)) or 0,
            "digests": session.scalar(select(func.count()).select_from(Digest)) or 0,
        },
    )


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(session: Session = Depends(get_session)) -> list[CompanyResponse]:
    companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
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

    return CompanyDetailResponse(
        **base.model_dump(),
        market_cap_updated_at=company.market_cap_updated_at,
        filings_count=filings_count,
        news_count=news_count,
        recent_filings=recent_filings,
        recent_news=recent_news,
    )


@router.get("/filings")
def list_filings(company_id: int | None = None, limit: int = 50, session: Session = Depends(get_session)):
    return FilingService(session).list_filings(limit=limit, company_id=company_id)


@router.get("/filings/{filing_id}")
def filing_detail(filing_id: int, session: Session = Depends(get_session)):
    filing = FilingService(session).get_filing_detail(filing_id)
    if not filing:
        raise HTTPException(status_code=404, detail="Filing not found")
    return filing


@router.get("/news")
def list_news(limit: int = 50, session: Session = Depends(get_session)):
    return NewsService(session).list_news(limit=limit)


@router.get("/digests")
def list_digests(limit: int = 20, session: Session = Depends(get_session)):
    return DigestService(session).list_digests(limit=limit)


@router.get("/digests/{digest_id}")
def digest_detail(digest_id: int, session: Session = Depends(get_session)):
    digest = DigestService(session).get_digest(digest_id)
    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    return digest


@router.get("/artifacts/filings/{filing_id}/pdf")
def filing_pdf(filing_id: int, session: Session = Depends(get_session)):
    filing = session.get(Filing, filing_id)
    if not filing or not filing.pdf_artifact_key:
        raise HTTPException(status_code=404, detail="PDF not found")
    store = ObjectStore()
    payload = store.get_bytes(filing.pdf_artifact_key)
    return Response(content=payload, media_type="application/pdf")


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
def admin_refresh_market_caps(count: int | None = None, session: Session = Depends(get_session)) -> AdminActionResponse:
    companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
    companies.sort(key=lambda company: company.market_cap or 0, reverse=True)
    selected = companies[:count] if count else companies
    result = MarketCapService(session).refresh_market_caps(selected)
    return AdminActionResponse(
        status="ok",
        message=f"Refreshed market caps for {result['refreshed']} companies; {result['failed']} failed.",
    )


@router.post("/admin/poll-filings", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_poll_filings(session: Session = Depends(get_session)) -> AdminActionResponse:
    count = FilingService(session).poll_new_filings()
    return AdminActionResponse(status="ok", message=f"Discovered {count} new filings.")


@router.post("/admin/ingest-news", response_model=AdminActionResponse, dependencies=[Depends(require_admin_token)])
def admin_ingest_news(session: Session = Depends(get_session)) -> AdminActionResponse:
    count = NewsService(session).ingest_feeds()
    return AdminActionResponse(status="ok", message=f"Ingested {count} news items.")


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
