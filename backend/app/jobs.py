from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Company
from app.models import Filing as FilingModel
from app.models import NewsItem as NewsItemModel
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.news import NewsService
from app.services.universe import UniverseService


def _with_session(callback):
    init_db()
    session = SessionLocal()
    try:
        return callback(session)
    finally:
        session.close()


def run_sync_universe(
    limit: int | None = None,
    progress_callback=None,
    progress_every: int = 100,
) -> int:
    return _with_session(
        lambda session: UniverseService(session).sync_universe(
            limit=limit,
            progress_callback=progress_callback,
            progress_every=progress_every,
        )
    )


def run_backfill_company(
    company_id: int,
    max_filings: int | None = None,
    since_date=None,
    years_back: int | None = None,
) -> int:
    return _with_session(
        lambda session: FilingService(session).backfill_company(
            company_id,
            max_filings=max_filings,
            since_date=since_date,
            years_back=years_back,
        )
    )


def run_backfill_top_companies(
    *,
    count: int,
    max_filings: int | None = None,
    since_date=None,
    years_back: int | None = None,
    focus_tickers: list[str] | None = None,
) -> int:
    def _run(session):
        companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        if focus_tickers:
            focus = {ticker.upper() for ticker in focus_tickers}
            companies = [company for company in companies if (company.ticker or "").upper() in focus]
        companies.sort(key=lambda company: company.market_cap or 0, reverse=True)
        selected = companies[:count]
        filing_service = FilingService(session)
        created = 0
        for company in selected:
            created += filing_service.backfill_company(
                company.id,
                max_filings=max_filings,
                since_date=since_date,
                years_back=years_back,
            )
        return created

    return _with_session(_run)


def run_poll_sec_filings() -> int:
    return _with_session(lambda session: FilingService(session).poll_new_filings())


def run_ingest_news() -> int:
    return _with_session(lambda session: NewsService(session).ingest_feeds())


def run_build_weekly_digest() -> int:
    digest = _with_session(lambda session: DigestService(session).build_weekly_digest())
    return digest.id


def run_resummarize_item(kind: str, item_id: int) -> int:
    def _run(session):
        if kind == "filing":
            filing_service = FilingService(session)
            filing = session.get(FilingModel, item_id)
            if not filing:
                raise ValueError(f"Unknown filing id={item_id}")
            company = filing.company
            summary = filing_service.summarizer.summarize(
                kind="filing",
                title=filing.title or f"{company.name} {filing.form_type}",
                text=filing_service._summary_source_text(filing),
                company_name=company.name,
                evidence_sections=list((filing.parsed_sections or {}).keys()),
            )
            filing.summary_json = summary.model_dump()
            filing.summary_status = "complete"
            filing.summary_attempts += 1
            session.commit()
            return item_id

        if kind != "news":
            raise ValueError("kind must be 'filing' or 'news'")

        news_service = NewsService(session)
        news_item = session.get(NewsItemModel, item_id)
        if not news_item:
            raise ValueError(f"Unknown news id={item_id}")
        summary = news_service.summarizer.summarize(
            kind="news",
            title=news_item.title,
            text=news_item.content_text or news_item.excerpt or news_item.title,
            company_name=", ".join(news_item.mentioned_companies),
            evidence_sections=news_item.topic_tags,
        )
        news_item.summary_json = summary.model_dump()
        news_item.summary_status = "complete"
        news_item.summary_attempts += 1
        session.commit()
        return item_id

    return _with_session(_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one-off platform jobs for deployment or maintenance.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_universe_parser = subparsers.add_parser("sync-universe", help="Refresh the covered company universe.")
    sync_universe_parser.add_argument("--limit", type=int, default=None)
    sync_universe_parser.add_argument("--progress-every", type=int, default=100)

    backfill_parser = subparsers.add_parser("backfill-company", help="Backfill filings for one company.")
    backfill_parser.add_argument("company_id", type=int)
    backfill_parser.add_argument("--max-filings", type=int, default=None)
    backfill_parser.add_argument("--years-back", type=int, default=None)

    backfill_top_parser = subparsers.add_parser(
        "backfill-top-companies",
        help="Backfill filings for the top covered companies by market cap.",
    )
    backfill_top_parser.add_argument("--count", type=int, default=25)
    backfill_top_parser.add_argument("--max-filings", type=int, default=None)
    backfill_top_parser.add_argument("--years-back", type=int, default=None)
    backfill_top_parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated tickers to constrain the target set, e.g. PFE,MRK,AMGN",
    )

    subparsers.add_parser("poll-sec-filings", help="Poll covered companies for newly filed periodic reports.")
    subparsers.add_parser("ingest-news", help="Pull configured news feeds and summarize new items.")
    subparsers.add_parser("build-weekly-digest", help="Build the current weekly digest.")

    resummarize_parser = subparsers.add_parser("resummarize", help="Re-summarize a filing or news item.")
    resummarize_parser.add_argument("kind", choices=["filing", "news"])
    resummarize_parser.add_argument("item_id", type=int)

    args = parser.parse_args()
    if args.command == "sync-universe":
        count = run_sync_universe(
            limit=args.limit,
            progress_every=args.progress_every,
            progress_callback=lambda message: print(message, flush=True),
        )
        print(f"Universe sync complete: {count} companies", flush=True)
        return
    if args.command == "backfill-company":
        count = run_backfill_company(
            args.company_id,
            max_filings=args.max_filings,
            years_back=args.years_back,
        )
        print(f"Backfilled {count} filings for company {args.company_id}", flush=True)
        return
    if args.command == "backfill-top-companies":
        focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]
        count = run_backfill_top_companies(
            count=args.count,
            max_filings=args.max_filings,
            years_back=args.years_back,
            focus_tickers=focus_tickers or None,
        )
        print(f"Backfilled {count} filings across the selected company set", flush=True)
        return
    if args.command == "poll-sec-filings":
        count = run_poll_sec_filings()
        print(f"Discovered {count} new filings", flush=True)
        return
    if args.command == "ingest-news":
        count = run_ingest_news()
        print(f"Ingested {count} news items", flush=True)
        return
    if args.command == "build-weekly-digest":
        digest_id = run_build_weekly_digest()
        print(f"Built digest {digest_id}", flush=True)
        return
    item_id = run_resummarize_item(args.kind, args.item_id)
    print(f"Re-summarized {args.kind} {item_id}", flush=True)


if __name__ == "__main__":
    main()
