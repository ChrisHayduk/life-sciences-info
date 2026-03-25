from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Company
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.universe import UniverseService


def bootstrap(
    *,
    sync_limit: int | None,
    backfill_companies: int,
    max_filings_per_company: int | None,
    years_back: int | None,
    ingest_news: bool,
    build_digest: bool,
    focus_tickers: list[str] | None,
) -> None:
    init_db()
    session = SessionLocal()
    try:
        synced = UniverseService(session, only_tickers=focus_tickers).sync_universe(limit=sync_limit)
        print(f"Universe sync complete: {synced} companies", flush=True)

        companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        if focus_tickers:
            companies = [company for company in companies if (company.ticker or "").upper() in set(focus_tickers)]
        companies.sort(key=lambda company: company.market_cap or 0, reverse=True)

        filing_service = FilingService(session)
        selected = companies[:backfill_companies]
        for index, company in enumerate(selected, start=1):
            count = filing_service.backfill_company(
                company.id,
                max_filings=max_filings_per_company,
                years_back=years_back,
            )
            print(
                f"[{index}/{len(selected)}] Backfilled {count} filings for {company.name} ({company.ticker or company.cik})",
                flush=True,
            )

        if ingest_news:
            count = NewsService(session).ingest_feeds()
            print(f"News ingestion complete: {count} items", flush=True)

        if build_digest:
            digest = DigestService(session).build_weekly_digest()
            print(f"Weekly digest ready: {digest.id} {digest.title}", flush=True)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the life sciences intelligence platform locally.")
    parser.add_argument("--sync-limit", type=int, default=250, help="Limit SEC issuers scanned during universe sync.")
    parser.add_argument(
        "--backfill-companies",
        type=int,
        default=10,
        help="Number of covered companies to historical-backfill after syncing the universe.",
    )
    parser.add_argument(
        "--max-filings-per-company",
        type=int,
        default=8,
        help="Cap the number of most recent target filings pulled per company during bootstrap.",
    )
    parser.add_argument(
        "--years-back",
        type=int,
        default=None,
        help="Restrict filing backfill to the most recent N years, e.g. --years-back 3.",
    )
    parser.add_argument("--skip-news", action="store_true", help="Skip RSS/news ingestion.")
    parser.add_argument("--skip-digest", action="store_true", help="Skip weekly digest generation.")
    parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated ticker list for a fast starter bootstrap, e.g. PFE,MRK,AMGN,GILD,VRTX,REGN,ABT,MDT,ISRG,DHR",
    )
    args = parser.parse_args()
    focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]

    bootstrap(
        sync_limit=args.sync_limit,
        backfill_companies=args.backfill_companies,
        max_filings_per_company=args.max_filings_per_company,
        years_back=args.years_back,
        ingest_news=not args.skip_news,
        build_digest=not args.skip_digest,
        focus_tickers=focus_tickers or None,
    )


if __name__ == "__main__":
    main()
