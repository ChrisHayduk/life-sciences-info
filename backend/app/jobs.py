from __future__ import annotations

import argparse
import contextlib
import logging

from sqlalchemy import select

from app.db import SessionLocal, ensure_db_indexes, init_db
from app.models import Company
from app.services.clinical_trials import ClinicalTrialsService
from app.services.digests import DigestService
from app.services.filings import FilingService
from app.services.market_caps import MarketCapService
from app.services.news import NewsService
from app.services.regulatory_events import RegulatoryEventService
from app.services.universe import UniverseService

logger = logging.getLogger(__name__)


def _with_session(callback):
    init_db()
    session = SessionLocal()
    try:
        return callback(session)
    finally:
        session.close()


def _close_if_possible(value) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def run_sync_universe(
    limit: int | None = None,
    progress_callback=None,
    progress_every: int = 100,
) -> int:
    def _run(session):
        service = UniverseService(session)
        try:
            return service.sync_universe(
                limit=limit,
                progress_callback=progress_callback,
                progress_every=progress_every,
            )
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def _load_active_companies(session, focus_tickers: list[str] | None = None) -> list[Company]:
    companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
    if focus_tickers:
        focus = {ticker.upper() for ticker in focus_tickers}
        companies = [company for company in companies if (company.ticker or "").upper() in focus]
    return sorted(companies, key=lambda company: (-(company.market_cap or 0), company.name, company.ticker or company.cik))


def run_refresh_market_caps(
    *,
    count: int | None = None,
    focus_tickers: list[str] | None = None,
    progress_callback=None,
    progress_every: int = 100,
) -> dict[str, int | str | None]:
    def _run(session):
        market_service = MarketCapService(session)
        filing_service = FilingService(session)
        news_service = NewsService(session)
        try:
            companies = _load_active_companies(session, focus_tickers=focus_tickers)
            selected = companies[:count] if count else companies
            result = market_service.refresh_market_caps(
                selected,
                progress_callback=progress_callback,
                progress_every=progress_every,
            )
            selected_company_ids = [int(company.id) for company in selected]
            reranked_filings = filing_service.rerank_for_companies(selected_company_ids)
            reranked_news = news_service.rerank_for_companies(selected_company_ids)
            return {
                "companies": int(result.get("companies") or 0),
                "refreshed": int(result.get("refreshed") or 0),
                "failed": int(result.get("failed") or 0),
                "last_error": result.get("last_error"),
                "reranked_filings": reranked_filings,
                "reranked_news": reranked_news,
            }
        finally:
            _close_if_possible(news_service)
            _close_if_possible(filing_service)
            _close_if_possible(market_service)

    return _with_session(_run)


def run_backfill_company(
    company_id: int,
    max_filings: int | None = None,
    since_date=None,
    years_back: int | None = None,
) -> int:
    def _run(session):
        service = FilingService(session)
        try:
            return service.backfill_company(
                company_id,
                max_filings=max_filings,
                since_date=since_date,
                years_back=years_back,
            )
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_backfill_top_companies(
    *,
    count: int,
    max_filings: int | None = None,
    since_date=None,
    years_back: int | None = None,
    focus_tickers: list[str] | None = None,
) -> int:
    def _run(session):
        companies = _load_active_companies(session, focus_tickers=focus_tickers)
        selected = companies[:count]
        filing_service = FilingService(session)
        try:
            created = 0
            for company in selected:
                created += filing_service.backfill_company(
                    company.id,
                    max_filings=max_filings,
                    since_date=since_date,
                    years_back=years_back,
                )
            return created
        finally:
            _close_if_possible(filing_service)

    return _with_session(_run)


def run_poll_sec_filings() -> dict[str, int]:
    def _run(session):
        service = FilingService(session)
        try:
            new_filings = service.poll_new_filings()
            summary_result = service.summarize_pending(limit=service.settings.max_filing_summaries_per_run, automated=True)
            return {
                "new_items": new_filings,
                "summarized": int(summary_result["summarized"]),
                "remaining_daily_budget": int(summary_result["remaining_daily_budget"]),
                "remaining_daily_budget_usd": float(summary_result.get("remaining_daily_budget_usd") or 0.0),
            }
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_ingest_news() -> dict[str, int]:
    def _run(session):
        service = NewsService(session)
        try:
            new_items = service.ingest_feeds()
            summary_result = service.summarize_pending(limit=service.settings.max_news_summaries_per_run, automated=True)
            return {
                "new_items": new_items,
                "summarized": int(summary_result["summarized"]),
                "remaining_daily_budget": int(summary_result["remaining_daily_budget"]),
                "remaining_daily_budget_usd": float(summary_result.get("remaining_daily_budget_usd") or 0.0),
            }
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_poll_regulatory_events(*, limit: int | None = None) -> dict[str, int]:
    def _run(session):
        service = RegulatoryEventService(session)
        try:
            return service.poll_fda_advisory_calendar(limit=limit)
        finally:
            _close_if_possible(service)

    result = _with_session(_run)
    return {
        "scanned": int(result["scanned"]),
        "inserted": int(result["inserted"]),
        "updated": int(result["updated"]),
        "tagged": int(result["tagged"]),
    }


def run_poll_trials(*, limit: int | None = None, focus_tickers: list[str] | None = None) -> dict[str, int | str]:
    def _run(session):
        companies = _load_active_companies(session, focus_tickers=focus_tickers)
        selected = companies[:limit] if limit else companies
        service = ClinicalTrialsService(session)
        try:
            return service.poll_companies(selected)
        finally:
            _close_if_possible(service)

    result = _with_session(_run)
    return {
        "provider": str(result["provider"]),
        "companies_scanned": int(result["companies_scanned"]),
        "companies_succeeded": int(result["companies_succeeded"]),
        "companies_failed": int(result["companies_failed"]),
        "new_trials": int(result["new_trials"]),
        "updated_trials": int(result["updated_trials"]),
        "pruned_trials": int(result.get("pruned_trials") or 0),
        "partial": int(result.get("partial") or 0),
        "skipped": int(result.get("skipped") or 0),
    }


def run_retag_news_companies(
    *,
    limit: int | None = None,
    recent_days: int | None = None,
    focus_tickers: list[str] | None = None,
) -> dict[str, int]:
    def _run(session):
        service = NewsService(session)
        try:
            return service.retag_company_news(
                limit=limit,
                recent_days=recent_days,
                focus_tickers=focus_tickers,
            )
        finally:
            _close_if_possible(service)

    result = _with_session(_run)
    return {
        "scanned": int(result["scanned"]),
        "updated": int(result["updated"]),
        "reranked": int(result["reranked"]),
    }


def run_build_weekly_digest() -> int:
    def _run(session):
        service = DigestService(session)
        try:
            return service.build_weekly_digest()
        finally:
            _close_if_possible(service)

    digest = _with_session(_run)
    return digest.id


def run_build_daily_digest() -> int:
    def _run(session):
        service = DigestService(session)
        try:
            return service.build_daily_digest()
        finally:
            _close_if_possible(service)

    digest = _with_session(_run)
    return digest.id


def run_send_daily_digest_email(*, force: bool = False) -> dict[str, int | bool | str | None]:
    def _run(session):
        service = DigestService(session)
        try:
            return service.send_daily_digest_email(force=force)
        finally:
            _close_if_possible(service)

    result = _with_session(_run)
    if result["delivery_status"] == "failed":
        logger.error("Daily digest email delivery failed for digest %s: %s", result["digest_id"], result["error"])
    else:
        logger.info(
            "Daily digest email job completed for digest %s with status=%s built=%s",
            result["digest_id"],
            result["delivery_status"],
            result["built"],
        )
    return result


def run_ensure_db_indexes() -> dict[str, int | list[str]]:
    created = ensure_db_indexes()
    return {"count": len(created), "indexes": created}


def run_summarize_pending(
    kind: str,
    *,
    limit: int | None = None,
    include_historical: bool = False,
    automated: bool = False,
) -> dict[str, int]:
    def _run(session):
        filing_service = None
        news_service = None
        if kind == "filing":
            filing_service = FilingService(session)
            try:
                return filing_service.summarize_pending(
                    limit=limit,
                    automated=automated,
                    include_historical=include_historical,
                )
            finally:
                _close_if_possible(filing_service)
        if kind == "news":
            news_service = NewsService(session)
            try:
                return news_service.summarize_pending(limit=limit, automated=automated)
            finally:
                _close_if_possible(news_service)
        raise ValueError("kind must be 'filing' or 'news'")

    result = _with_session(_run)
    return {
        "summarized": int(result["summarized"]),
        "remaining_daily_budget": int(result["remaining_daily_budget"]),
        "remaining_daily_budget_usd": float(result.get("remaining_daily_budget_usd") or 0.0),
    }


def run_resummarize_item(kind: str, item_id: int) -> int:
    def _run(session):
        if kind == "filing":
            service = FilingService(session)
            try:
                service.summarize_item(item_id, consume_override_budget=False, force=True)
                return item_id
            finally:
                _close_if_possible(service)

        if kind != "news":
            raise ValueError("kind must be 'filing' or 'news'")

        service = NewsService(session)
        try:
            service.summarize_item(item_id, consume_override_budget=False, force=True)
            return item_id
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_reprocess_filing(item_id: int) -> int:
    def _run(session):
        service = FilingService(session)
        try:
            service.reprocess_existing_filing(item_id)
            return item_id
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_reprocess_company_filings(company_id: int, limit: int | None = None) -> int:
    def _run(session):
        service = FilingService(session)
        try:
            return service.reprocess_company_filings(company_id, limit=limit)
        finally:
            _close_if_possible(service)

    return _with_session(_run)


def run_refresh_all_data(
    *,
    sync_limit: int | None = None,
    progress_every: int = 100,
    company_count: int | None = None,
    max_filings: int | None = None,
    years_back: int | None = None,
    focus_tickers: list[str] | None = None,
    include_news: bool = True,
    build_digest: bool = True,
) -> dict[str, int]:
    def _sync(session):
        universe_service = UniverseService(session, only_tickers=focus_tickers)
        try:
            synced = universe_service.sync_universe(
                limit=sync_limit,
                progress_callback=lambda message: print(message, flush=True),
                progress_every=progress_every,
            )
            return synced
        finally:
            _close_if_possible(universe_service)

    synced = _with_session(_sync)

    market_cap_result = run_refresh_market_caps(
        focus_tickers=focus_tickers,
        progress_callback=lambda message: print(message, flush=True),
        progress_every=progress_every,
    )
    regulatory_result = run_poll_regulatory_events()
    print(
        f"Regulatory event sync complete: {regulatory_result['inserted']} new, "
        f"{regulatory_result['updated']} updated, "
        f"{regulatory_result['tagged']} tagged to covered companies",
        flush=True,
    )

    def _select(session):
        companies = _load_active_companies(session, focus_tickers=focus_tickers)
        selected = companies[:company_count] if company_count else companies
        return [
            {
                "id": company.id,
                "name": company.name,
                "ticker": company.ticker,
                "cik": company.cik,
            }
            for company in selected
        ]

    selected = _with_session(_select)

    reprocessed_total = 0
    backfilled_total = 0
    for index, company in enumerate(selected, start=1):
        def _refresh_company(session):
            filing_service = FilingService(session)
            try:
                reprocessed = filing_service.reprocess_company_filings(company["id"], resummarize=False)
                added = filing_service.backfill_company(
                    company["id"],
                    max_filings=max_filings,
                    years_back=years_back,
                )
                return reprocessed, added
            finally:
                _close_if_possible(filing_service)

        reprocessed, added = _with_session(_refresh_company)
        reprocessed_total += reprocessed
        backfilled_total += added
        rebuild_label = (
            f"{reprocessed} rebuilt"
            if reprocessed
            else "0 rebuilt (no existing filings to rebuild)"
        )
        print(
            f"[{index}/{len(selected)}] Refreshed {company['name']} ({company['ticker'] or company['cik']}): "
            f"{rebuild_label}, {added} added",
            flush=True,
        )

    news_count = 0
    if include_news:
        news_result = run_ingest_news()
        news_count = int(news_result["new_items"])
        print(
            f"News ingestion complete: {news_count} items, "
            f"{news_result['summarized']} summarized, "
            f"{news_result['remaining_daily_budget']} daily budget remaining "
            f"(${news_result['remaining_daily_budget_usd']:.2f})",
            flush=True,
        )

    digest_count = 0
    if build_digest:
        def _digest(session):
            service = DigestService(session)
            try:
                return service.build_weekly_digest()
            finally:
                _close_if_possible(service)

        digest = _with_session(_digest)
        digest_count = 1 if digest else 0
        print(f"Weekly digest ready: {digest.id} {digest.title}", flush=True)

    return {
        "companies": len(selected),
        "synced_companies": synced,
        "market_cap_companies": int(market_cap_result["companies"] or 0),
        "refreshed_market_caps": int(market_cap_result["refreshed"] or 0),
        "failed_market_caps": int(market_cap_result["failed"] or 0),
        "reranked_filings": int(market_cap_result["reranked_filings"] or 0),
        "reranked_news": int(market_cap_result["reranked_news"] or 0),
        "regulatory_events": int(regulatory_result["inserted"] or 0) + int(regulatory_result["updated"] or 0),
        "reprocessed_filings": reprocessed_total,
        "new_filings": backfilled_total,
        "news_items": news_count,
        "digests": digest_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one-off platform jobs for deployment or maintenance.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_universe_parser = subparsers.add_parser("sync-universe", help="Refresh the covered company universe.")
    sync_universe_parser.add_argument("--limit", type=int, default=None)
    sync_universe_parser.add_argument("--progress-every", type=int, default=100)

    refresh_market_caps_parser = subparsers.add_parser(
        "refresh-market-caps",
        help="Refresh company market caps for all active issuers or a top subset.",
    )
    refresh_market_caps_parser.add_argument("--all", action="store_true")
    refresh_market_caps_parser.add_argument("--count", type=int, default=None)
    refresh_market_caps_parser.add_argument("--progress-every", type=int, default=100)
    refresh_market_caps_parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated tickers to constrain the target set, e.g. PFE,MRK,AMGN",
    )

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
    poll_regulatory_parser = subparsers.add_parser(
        "poll-regulatory-events",
        help="Pull official FDA advisory-calendar events and tag covered companies.",
    )
    poll_regulatory_parser.add_argument("--limit", type=int, default=None)
    poll_trials_parser = subparsers.add_parser(
        "poll-trials",
        help="Pull trial data for covered companies using the configured trial provider.",
    )
    poll_trials_parser.add_argument("--limit", type=int, default=None)
    poll_trials_parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated tickers to constrain the target set, e.g. MRK,PFE,AMGN",
    )
    subparsers.add_parser(
        "ensure-db-indexes",
        help="Create one-time production indexes that support low-memory queue and news queries.",
    )
    retag_news_parser = subparsers.add_parser(
        "retag-news-companies",
        help="Normalize explicit company tags for stored news items and rerank affected stories.",
    )
    retag_news_parser.add_argument("--all", action="store_true")
    retag_news_parser.add_argument("--limit", type=int, default=None)
    retag_news_parser.add_argument("--recent-days", type=int, default=None)
    retag_news_parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated tickers to constrain the retagging pass, e.g. MRK,PFE,AMGN",
    )
    subparsers.add_parser("build-weekly-digest", help="Build the current weekly digest.")
    subparsers.add_parser("build-daily-digest", help="Build the most recent daily digest.")
    send_daily_digest_email_parser = subparsers.add_parser(
        "send-daily-digest-email",
        help="Build or reuse the most recent daily digest and email it if configured.",
    )
    send_daily_digest_email_parser.add_argument("--force", action="store_true")

    summarize_pending_parser = subparsers.add_parser(
        "summarize-pending",
        help="Summarize pending filings or news with quota-aware ranking.",
    )
    summarize_pending_parser.add_argument("kind", choices=["filing", "news"])
    summarize_pending_parser.add_argument("--limit", type=int, default=None)
    summarize_pending_parser.add_argument("--include-historical", action="store_true")

    resummarize_parser = subparsers.add_parser("resummarize", help="Re-summarize a filing or news item.")
    resummarize_parser.add_argument("kind", choices=["filing", "news"])
    resummarize_parser.add_argument("item_id", type=int)

    reprocess_filing_parser = subparsers.add_parser("reprocess-filing", help="Re-download and rebuild one filing.")
    reprocess_filing_parser.add_argument("item_id", type=int)

    reprocess_company_parser = subparsers.add_parser(
        "reprocess-company-filings",
        help="Re-download and rebuild stored filings for one company.",
    )
    reprocess_company_parser.add_argument("company_id", type=int)
    reprocess_company_parser.add_argument("--limit", type=int, default=None)

    refresh_all_parser = subparsers.add_parser(
        "refresh-all-data",
        help="Resync companies, rebuild stored filings, backfill missing filings, and optionally refresh news/digests.",
    )
    refresh_all_parser.add_argument("--sync-limit", type=int, default=None)
    refresh_all_parser.add_argument("--progress-every", type=int, default=100)
    refresh_all_parser.add_argument("--company-count", type=int, default=None)
    refresh_all_parser.add_argument("--max-filings", type=int, default=None)
    refresh_all_parser.add_argument("--years-back", type=int, default=None)
    refresh_all_parser.add_argument(
        "--focus-tickers",
        default="",
        help="Comma-separated tickers to constrain the refresh set, e.g. MRK,PFE,AMGN",
    )
    refresh_all_parser.add_argument("--skip-news", action="store_true")
    refresh_all_parser.add_argument("--skip-digest", action="store_true")

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
    if args.command == "refresh-market-caps":
        if args.all and args.count is not None:
            raise SystemExit("Use either --all or --count, not both")
        focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]
        result = run_refresh_market_caps(
            count=None if args.all else args.count,
            focus_tickers=focus_tickers or None,
            progress_every=args.progress_every,
            progress_callback=lambda message: print(message, flush=True),
        )
        print(
            "Market cap refresh complete: "
            f"{result['companies']} companies, "
            f"{result['refreshed']} refreshed, "
            f"{result['failed']} failed, "
            f"{result['reranked_filings']} filings reranked, "
            f"{result['reranked_news']} news items reranked",
            flush=True,
        )
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
        result = run_poll_sec_filings()
        print(
            f"Discovered {result['new_items']} new filings, "
            f"summarized {result['summarized']}, "
            f"{result['remaining_daily_budget']} daily budget remaining "
            f"(${result['remaining_daily_budget_usd']:.2f})",
            flush=True,
        )
        return
    if args.command == "ingest-news":
        result = run_ingest_news()
        print(
            f"Ingested {result['new_items']} news items, "
            f"summarized {result['summarized']}, "
            f"{result['remaining_daily_budget']} daily budget remaining "
            f"(${result['remaining_daily_budget_usd']:.2f})",
            flush=True,
        )
        return
    if args.command == "poll-regulatory-events":
        result = run_poll_regulatory_events(limit=args.limit)
        print(
            f"Synced {result['inserted']} new and {result['updated']} updated FDA events; "
            f"{result['tagged']} tagged to covered companies",
            flush=True,
        )
        return
    if args.command == "poll-trials":
        focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]
        result = run_poll_trials(limit=args.limit, focus_tickers=focus_tickers or None)
        if result["skipped"]:
            print(
                f"Skipped trial sync for provider {result['provider']}; provider is not configured.",
                flush=True,
            )
            return
        print(
            f"Provider {result['provider']}: scanned {result['companies_scanned']} companies; "
            f"{result['companies_succeeded']} succeeded, {result['companies_failed']} failed; "
            f"{result['new_trials']} new trials, {result['updated_trials']} updated, "
            f"{result['pruned_trials']} pruned"
            + ("; run was partial" if result["partial"] else ""),
            flush=True,
        )
        return
    if args.command == "ensure-db-indexes":
        result = run_ensure_db_indexes()
        print(
            f"Database indexes ready: {result['count']} ensured"
            + (f" ({', '.join(result['indexes'])})" if result["indexes"] else ""),
            flush=True,
        )
        return
    if args.command == "retag-news-companies":
        focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]
        result = run_retag_news_companies(
            limit=args.limit,
            recent_days=args.recent_days,
            focus_tickers=focus_tickers or None,
        )
        print(
            f"Retagged company links for {result['updated']} of {result['scanned']} news items; "
            f"{result['reranked']} reranked",
            flush=True,
        )
        return
    if args.command == "summarize-pending":
        result = run_summarize_pending(
            args.kind,
            limit=args.limit,
            include_historical=args.include_historical,
            automated=False,
        )
        print(
            f"Summarized {result['summarized']} pending {args.kind} items; "
            f"{result['remaining_daily_budget']} daily budget remaining "
            f"(${result['remaining_daily_budget_usd']:.2f})",
            flush=True,
        )
        return
    if args.command == "build-weekly-digest":
        digest_id = run_build_weekly_digest()
        print(f"Built digest {digest_id}", flush=True)
        return
    if args.command == "build-daily-digest":
        digest_id = run_build_daily_digest()
        print(f"Built daily digest {digest_id}", flush=True)
        return
    if args.command == "send-daily-digest-email":
        result = run_send_daily_digest_email(force=args.force)
        if result["delivery_status"] == "failed":
            raise SystemExit(
                f"Daily digest {result['digest_id']} email delivery failed: {result['error']}"
            )
        print(
            f"Daily digest {result['digest_id']} status={result['delivery_status']} built={result['built']}",
            flush=True,
        )
        return
    if args.command == "reprocess-filing":
        item_id = run_reprocess_filing(args.item_id)
        print(f"Reprocessed filing {item_id}", flush=True)
        return
    if args.command == "reprocess-company-filings":
        count = run_reprocess_company_filings(args.company_id, limit=args.limit)
        print(f"Reprocessed {count} filings for company {args.company_id}", flush=True)
        return
    if args.command == "refresh-all-data":
        focus_tickers = [ticker.strip().upper() for ticker in args.focus_tickers.split(",") if ticker.strip()]
        result = run_refresh_all_data(
            sync_limit=args.sync_limit,
            progress_every=args.progress_every,
            company_count=args.company_count,
            max_filings=args.max_filings,
            years_back=args.years_back,
            focus_tickers=focus_tickers or None,
            include_news=not args.skip_news,
            build_digest=not args.skip_digest,
        )
        print(
            "Refresh complete: "
            f"{result['companies']} companies, "
            f"{result['refreshed_market_caps']} refreshed market caps, "
            f"{result['failed_market_caps']} failed market caps, "
            f"{result['reranked_filings']} reranked filings, "
            f"{result['reranked_news']} reranked news items, "
            f"{result['reprocessed_filings']} rebuilt filings, "
            f"{result['new_filings']} new filings, "
            f"{result['news_items']} news items",
            flush=True,
        )
        return
    item_id = run_resummarize_item(args.kind, args.item_id)
    print(f"Re-summarized {args.kind} {item_id}", flush=True)


if __name__ == "__main__":
    main()
