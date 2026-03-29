from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.services.constants import CORE_LIFE_SCIENCES_SIC
from app.services.sec import SECClient


def normalize_cik(cik: str | int | None) -> str:
    return f"{int(cik or 0):010d}"


def is_core_life_sciences(sic: str | None, *, allowlisted: bool = False, denylisted: bool = False) -> bool:
    if denylisted:
        return False
    if allowlisted:
        return True
    if not sic:
        return False
    return str(sic) in CORE_LIFE_SCIENCES_SIC


def describe_universe_reason(reason: str) -> str:
    labels = {
        "sic-allowlist": "Core life sciences SIC filter",
        "manual-allowlist": "Manual include override",
    }
    return labels.get(reason, reason.replace("-", " ").title())


class UniverseService:
    def __init__(
        self,
        session: Session,
        sec_client: SECClient | None = None,
        allowlist: Iterable[str] | None = None,
        denylist: Iterable[str] | None = None,
        only_tickers: Iterable[str] | None = None,
    ) -> None:
        self.session = session
        self._owns_sec_client = sec_client is None
        self.sec_client = sec_client or SECClient()
        self.allowlist = {value.upper() for value in (allowlist or [])}
        self.denylist = {value.upper() for value in (denylist or [])}
        self.only_tickers = {value.upper() for value in (only_tickers or [])}

    def close(self) -> None:
        if self._owns_sec_client:
            with contextlib.suppress(Exception):
                self.sec_client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def sync_universe(
        self,
        limit: int | None = None,
        progress_callback: Callable[[str], None] | None = None,
        progress_every: int = 100,
    ) -> int:
        count = 0
        ticker_rows = self.sec_client.get_company_tickers()
        if self.only_tickers:
            ticker_rows = [row for row in ticker_rows if ((row.get("ticker") or "").upper() in self.only_tickers)]
        target_rows = ticker_rows[:limit]
        total_rows = len(target_rows)

        if progress_callback:
            progress_callback(f"Universe sync starting: scanning {total_rows} SEC issuers")

        for index, row in enumerate(target_rows, start=1):
            cik = normalize_cik(row.get("cik") or row.get("cik_str"))
            ticker = (row.get("ticker") or "").upper() or None
            allowlisted = cik in self.allowlist or (ticker or "") in self.allowlist
            denylisted = cik in self.denylist or (ticker or "") in self.denylist

            submission = self.sec_client.get_company_submissions(cik)
            sic = str(submission.get("sic") or "") or None
            if is_core_life_sciences(sic, allowlisted=allowlisted, denylisted=denylisted):
                company = self.session.scalar(select(Company).where(Company.cik == cik))
                if company is None:
                    company = Company(cik=cik, name=row.get("name") or submission.get("name") or cik)
                    self.session.add(company)

                company.name = submission.get("name") or row.get("name") or company.name
                company.ticker = ticker
                company.exchange = row.get("exchange")
                company.sic = sic
                company.sic_description = submission.get("sicDescription") or CORE_LIFE_SCIENCES_SIC.get(sic)
                company.universe_reason = "manual-allowlist" if allowlisted else "sic-allowlist"
                company.is_active = True
                company.extra_metadata = {
                    "entityType": submission.get("entityType"),
                    "phone": submission.get("phone"),
                }

                count += 1

            if progress_callback and (index == total_rows or index % progress_every == 0):
                progress_callback(
                    f"Universe sync progress: scanned {index}/{total_rows} issuers, matched {count} covered companies"
                )

        self.session.commit()
        if progress_callback:
            progress_callback(f"Universe sync complete: matched {count} covered companies")
        return count
