from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Filing
from app.schemas import FilingDetail, FilingListItem
from app.services.constants import ANNUAL_FORMS, FILING_SECTION_PATTERNS, INTERIM_FORMS, TARGET_FORMS
from app.services.market_data import MarketDataClient
from app.services.pdf import build_pdf_from_text
from app.services.ranking import company_market_cap_percentiles, compute_filing_scores
from app.services.sec import SECClient
from app.services.storage import ObjectStore
from app.services.summarization import OpenAISummarizer


def normalize_form_type(form_type: str) -> str:
    form_type = (form_type or "").upper().strip()
    return form_type[:-2] if form_type.endswith("/A") else form_type


def comparable_group(form_type: str) -> str:
    normalized = normalize_form_type(form_type)
    if normalized in {"10-K", "20-F", "40-F"}:
        return "annual"
    return "interim"


def is_target_form(form_type: str) -> bool:
    return form_type.upper() in TARGET_FORMS


def html_to_text(raw_bytes: bytes, content_type: str) -> str:
    if "html" in content_type.lower():
        soup = BeautifulSoup(raw_bytes, "html.parser")
        return soup.get_text("\n", strip=True)
    return raw_bytes.decode("utf-8", errors="ignore")


def parse_sections(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sections: dict[str, list[str]] = {name: [] for name in FILING_SECTION_PATTERNS}
    current = None
    for line in lines:
        lowered = line.lower()
        matched = None
        for section_name, patterns in FILING_SECTION_PATTERNS.items():
            if any(pattern in lowered for pattern in patterns):
                matched = section_name
                break
        if matched:
            current = matched
            sections[current].append(line)
            continue
        if current:
            sections[current].append(line)
    return {key: "\n".join(value) for key, value in sections.items() if value}


def is_periodic_6k(title: str | None, text: str, items: str | None = None) -> bool:
    lowered = " ".join(filter(None, [title or "", items or "", text[:8000]])).lower()
    keywords = [
        "quarterly results",
        "quarterly report",
        "interim results",
        "interim report",
        "annual report",
        "financial results",
        "earnings release",
        "results for the quarter",
        "six months ended",
    ]
    return any(keyword in lowered for keyword in keywords)


class FilingService:
    def __init__(
        self,
        session: Session,
        sec_client: SECClient | None = None,
        summarizer: OpenAISummarizer | None = None,
        market_data_client: MarketDataClient | None = None,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.session = session
        self.sec_client = sec_client or SECClient()
        self.summarizer = summarizer or OpenAISummarizer()
        self.market_data_client = market_data_client or MarketDataClient()
        self.object_store = object_store or ObjectStore()
        self.settings = get_settings()

    def backfill_company(
        self,
        company_id: int,
        max_filings: int | None = None,
        since_date: date | None = None,
        years_back: int | None = None,
    ) -> int:
        company = self.session.get(Company, company_id)
        if not company:
            raise ValueError(f"Unknown company id={company_id}")

        filings = self.sec_client.iter_company_filings(company.cik)
        created = 0
        cutoff_date = since_date or self._cutoff_date(years_back)
        target_rows = sorted(filings, key=lambda item: item.get("filingDate") or "", reverse=True)
        if cutoff_date:
            filtered_rows = []
            for filing_row in target_rows:
                filing_date = self._parse_date(filing_row.get("filingDate"))
                if filing_date and filing_date >= cutoff_date:
                    filtered_rows.append(filing_row)
            target_rows = filtered_rows
        if max_filings is not None:
            target_rows = target_rows[:max_filings]
        for filing_row in target_rows:
            try:
                created += int(self._ingest_filing_row(company, filing_row))
            except Exception:
                continue
        self.session.commit()
        return created

    def poll_new_filings(self) -> int:
        created = 0
        companies = self.session.scalars(select(Company).where(Company.is_active.is_(True))).all()
        for company in companies:
            submissions = self.sec_client.get_company_submissions(company.cik)
            recent_rows = self.sec_client._rows_from_columnar(submissions.get("filings", {}).get("recent", {}))
            for filing_row in recent_rows:
                try:
                    created += int(self._ingest_filing_row(company, filing_row))
                except Exception:
                    continue
        self.session.commit()
        return created

    def _ingest_filing_row(self, company: Company, filing_row: dict[str, Any]) -> bool:
        form_type = (filing_row.get("form") or "").upper()
        if not is_target_form(form_type):
            return False
        accession_number = filing_row.get("accessionNumber")
        if not accession_number:
            return False
        existing = self.session.scalar(select(Filing).where(Filing.accession_number == accession_number))
        if existing:
            return False

        primary_document = filing_row.get("primaryDocument")
        filing_doc = self.sec_client.download_primary_document(company.cik, accession_number, primary_document)
        raw_text = html_to_text(filing_doc.content, filing_doc.content_type)

        if normalize_form_type(form_type) == "6-K" and not is_periodic_6k(
            filing_row.get("primaryDocDescription"),
            raw_text,
            filing_row.get("items"),
        ):
            return False

        filing_urls = self.sec_client.build_filing_urls(company.cik, accession_number, primary_document)
        parsed_sections = parse_sections(raw_text)
        raw_key = self.object_store.put_bytes(
            f"filings/raw/{company.cik}/{accession_number}-{primary_document or 'filing'}.txt",
            raw_text.encode("utf-8"),
            "text/plain",
        )
        pdf_bytes = build_pdf_from_text(
            f"{company.name} {form_type} filed {filing_row.get('filingDate')}",
            raw_text[:60000],
        )
        pdf_key = self.object_store.put_bytes(
            f"filings/pdf/{company.cik}/{accession_number}.pdf",
            pdf_bytes,
            "application/pdf",
        )

        filing = Filing(
            company_id=company.id,
            accession_number=accession_number,
            form_type=form_type,
            normalized_form_type=normalize_form_type(form_type),
            title=filing_row.get("primaryDocDescription") or f"{company.name} {form_type}",
            description=filing_row.get("primaryDocDescription"),
            filed_at=self._parse_datetime(filing_row.get("acceptanceDateTime") or filing_row.get("filingDate")),
            period_end_date=self._parse_date(filing_row.get("reportDate")),
            is_amendment=form_type.endswith("/A"),
            is_periodic_equivalent=True,
            filing_url=filing_urls["filing_url"],
            original_document_url=filing_urls["original_document_url"],
            source_json_url=None,
            primary_document=primary_document,
            raw_text=raw_text,
            parsed_sections=parsed_sections,
            raw_artifact_key=raw_key,
            pdf_artifact_key=pdf_key,
            extra_metadata={
                "items": filing_row.get("items"),
                "size": filing_row.get("size"),
                "filmNumber": filing_row.get("filmNumber"),
            },
        )
        self.session.add(filing)
        self.session.flush()

        self._refresh_market_cap(company)
        prior = self._prior_comparable_filing(company.id, filing)
        if prior:
            filing.prior_comparable_filing_id = prior.id

        summary = self.summarizer.summarize(
            kind="filing",
            title=filing.title or f"{company.name} {form_type}",
            text=self._summary_source_text(filing),
            company_name=company.name,
            evidence_sections=list(parsed_sections.keys()),
        )
        filing.summary_json = summary.model_dump()
        filing.summary_model = self.settings.openai_model if self.settings.openai_api_key else "fallback-local"
        filing.summary_prompt_version = self.settings.summary_prompt_version
        filing.summary_status = "complete"
        filing.summary_attempts += 1

        market_cap_scores = company_market_cap_percentiles(self.session)
        scores = compute_filing_scores(
            filing,
            company_market_cap_score=market_cap_scores.get(company.id, 0.0),
            prior_filing=prior,
        )
        filing.market_cap_score = float(scores["market_cap_score"])
        filing.importance_score = float(scores["importance_score"])
        filing.impact_score = float(scores["impact_score"])
        filing.composite_score = float(scores["composite_score"])
        filing.score_confidence = str(scores["score_confidence"])
        filing.score_explanation = dict(scores["score_explanation"])
        return True

    def _refresh_market_cap(self, company: Company) -> None:
        try:
            market = self.market_data_client.fetch_market_cap(company.ticker)
        except Exception:
            return
        company.market_cap = market["market_cap"]
        company.market_cap_source = market["source"]
        company.market_cap_updated_at = market["as_of"]

    def _prior_comparable_filing(self, company_id: int, filing: Filing) -> Filing | None:
        group = comparable_group(filing.normalized_form_type)
        filings = self.session.scalars(
            select(Filing)
            .where(Filing.company_id == company_id, Filing.filed_at < filing.filed_at)
            .order_by(Filing.filed_at.desc())
        ).all()
        for candidate in filings:
            if comparable_group(candidate.normalized_form_type) == group:
                return candidate
        return None

    def _summary_source_text(self, filing: Filing) -> str:
        section_text = []
        for section_name, section_body in filing.parsed_sections.items():
            section_text.append(f"[{section_name}]\n{section_body[:3000]}")
        return "\n\n".join(section_text) if section_text else (filing.raw_text or "")[:18000]

    @staticmethod
    def _parse_datetime(raw_value: str | None) -> datetime:
        if not raw_value:
            return datetime.utcnow()
        if raw_value.isdigit() and len(raw_value) >= 14:
            return datetime.strptime(raw_value[:14], "%Y%m%d%H%M%S")
        return date_parser.parse(raw_value)

    @staticmethod
    def _parse_date(raw_value: str | None) -> date | None:
        if not raw_value:
            return None
        return date_parser.parse(raw_value).date()

    @staticmethod
    def _cutoff_date(years_back: int | None) -> date | None:
        if not years_back:
            return None
        return (datetime.utcnow() - relativedelta(years=years_back)).date()

    def list_filings(self, limit: int = 50, company_id: int | None = None) -> list[FilingListItem]:
        query = select(Filing, Company).join(Company, Filing.company_id == Company.id).order_by(Filing.composite_score.desc())
        if company_id:
            query = query.where(Filing.company_id == company_id)
        rows = self.session.execute(query.limit(limit)).all()
        return [self._to_list_item(filing, company) for filing, company in rows]

    def get_filing_detail(self, filing_id: int) -> FilingDetail | None:
        row = self.session.execute(
            select(Filing, Company).join(Company, Filing.company_id == Company.id).where(Filing.id == filing_id)
        ).first()
        if not row:
            return None
        filing, company = row
        summary = filing.summary_json or {}
        base = self._to_list_item(filing, company)
        return FilingDetail(
            **base.model_dump(),
            parsed_sections=filing.parsed_sections or {},
            key_takeaways=summary.get("key_takeaways", []),
            material_changes=summary.get("material_changes", []),
            risk_flags=summary.get("risk_flags", []),
            opportunity_flags=summary.get("opportunity_flags", []),
            evidence_sections=summary.get("evidence_sections", []),
            prior_comparable_filing_id=filing.prior_comparable_filing_id,
            prior_comparable_filing_url=(
                f"{self.settings.frontend_base_url}/filings/{filing.prior_comparable_filing_id}"
                if filing.prior_comparable_filing_id
                else None
            ),
        )

    def _to_list_item(self, filing: Filing, company: Company) -> FilingListItem:
        summary = filing.summary_json or {}
        return FilingListItem(
            id=filing.id,
            company_id=company.id,
            company_name=company.name,
            ticker=company.ticker,
            accession_number=filing.accession_number,
            form_type=filing.form_type,
            normalized_form_type=filing.normalized_form_type,
            filed_at=filing.filed_at,
            title=filing.title,
            importance_score=filing.importance_score,
            market_cap_score=filing.market_cap_score,
            impact_score=filing.impact_score,
            composite_score=filing.composite_score,
            score_explanation=filing.score_explanation or {},
            summary=summary.get("summary", ""),
            original_document_url=filing.original_document_url,
            pdf_download_url=(
                f"{self.settings.api_base_url}{self.settings.api_prefix}/artifacts/filings/{filing.id}/pdf"
                if filing.pdf_artifact_key
                else None
            ),
        )
