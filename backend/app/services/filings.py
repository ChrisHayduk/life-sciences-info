from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Comment
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Filing
from app.schemas import FilingDetail, FilingListItem
from app.services.constants import ANNUAL_FORMS, FILING_SECTION_PATTERNS, INTERIM_FORMS, TARGET_FORMS
from app.services.html_pdf import render_html_to_pdf
from app.services.market_data import MarketDataClient
from app.services.pdf import build_pdf_from_text
from app.services.ranking import company_market_cap_percentiles, compute_filing_scores
from app.services.sec import SECClient
from app.services.storage import ObjectStore
from app.services.summarization import OpenAISummarizer

INLINE_XBRL_TAGS = {"ix:nonnumeric", "ix:nonfraction", "ix:continuation", "ix:footnote"}
DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "meta",
    "link",
    "title",
    "head",
    "iframe",
    "object",
}
DROP_TAG_PREFIXES = ("xbrli:", "xbrldi:", "link:", "dei:", "ixt:", "xsi:", "ix:header")
METADATA_TOKENS = {"true", "false", "fy", "q1", "q2", "q3", "q4", "p3m", "p6m", "p9m", "p12m"}
SECTION_ORDER = [
    "business",
    "risk_factors",
    "legal_proceedings",
    "md&a",
    "liquidity",
    "financial_statements",
    "subsequent_events",
]
ITEM_HEADER_RE = re.compile(r"(?im)^\s*(?:part\s+[ivx]+\s*)?item\s+\d+[a-z]?\.")
URL_ONLY_RE = re.compile(r"^(?:https?://\S+\s*)+$", re.IGNORECASE)
NAMESPACE_TOKEN_RE = re.compile(r"^[a-z][\w.-]*:[\w.-]+$", re.IGNORECASE)
DATE_TOKEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CIK_TOKEN_RE = re.compile(r"^\d{8,10}$")
MULTISPACE_RE = re.compile(r"[ \t]+")

ANNUAL_SECTION_REGEXES: dict[str, tuple[re.Pattern[str], ...]] = {
    "business": (
        re.compile(r"(?im)^\s*item\s*1\.\s*$[\s\n]*^\s*business\.?\s*$"),
    ),
    "risk_factors": (
        re.compile(r"(?im)^\s*item\s*1a\.\s*$[\s\n]*^\s*risk factors\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*3d\.\s*$[\s\n]*^\s*risk factors\.?\s*$"),
    ),
    "legal_proceedings": (
        re.compile(r"(?im)^\s*item\s*3\.\s*$[\s\n]*^\s*legal proceedings\.?\s*$"),
    ),
    "md&a": (
        re.compile(
            r"(?im)^\s*item\s*7\.\s*$[\s\n]*^\s*management[’']?s discussion and analysis of financial condition and results of operations\.?\s*$"
        ),
        re.compile(r"(?im)^\s*item\s*5\.\s*$[\s\n]*^\s*operating and financial review and prospects\.?\s*$"),
    ),
    "financial_statements": (
        re.compile(r"(?im)^\s*item\s*8\.\s*$[\s\n]*^\s*financial statements(?: and supplementary data)?\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*17\.\s*$[\s\n]*^\s*financial statements\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*18\.\s*$[\s\n]*^\s*financial statements\.?\s*$"),
    ),
}

INTERIM_SECTION_REGEXES: dict[str, tuple[re.Pattern[str], ...]] = {
    "financial_statements": (
        re.compile(r"(?im)^\s*item\s*1\.\s*financial statements(?: \(unaudited\))?\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*1\.\s*$[\s\n]*^\s*financial statements(?: \(unaudited\))?\.?\s*$"),
    ),
    "md&a": (
        re.compile(
            r"(?im)^\s*item\s*2\.\s*management[’']?s discussion and analysis of financial condition and results of operations\.?\s*$"
        ),
        re.compile(
            r"(?im)^\s*item\s*2\.\s*$[\s\n]*^\s*management[’']?s discussion and analysis of financial condition and results of operations\.?\s*$"
        ),
    ),
    "risk_factors": (
        re.compile(r"(?im)^\s*item\s*1a\.\s* risk factors\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*1a\.\s*$[\s\n]*^\s*risk factors\.?\s*$"),
    ),
    "legal_proceedings": (
        re.compile(r"(?im)^\s*item\s*1\.\s*legal proceedings\.?\s*$"),
        re.compile(r"(?im)^\s*item\s*1\.\s*$[\s\n]*^\s*legal proceedings\.?\s*$"),
    ),
}

SUBSECTION_REGEXES: dict[str, tuple[re.Pattern[str], ...]] = {
    "liquidity": (
        re.compile(r"(?im)^\s*analysis of liquidity and capital resources\.?\s*$"),
        re.compile(r"(?im)^\s*liquidity and capital resources\.?\s*$"),
    ),
    "subsequent_events": (
        re.compile(r"(?im)^\s*subsequent events\.?\s*$"),
    ),
}


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
        _strip_html_noise(soup)
        text = soup.get_text("\n", strip=True)
        return _clean_extracted_text(text)
    return _clean_extracted_text(raw_bytes.decode("utf-8", errors="ignore"))


def parse_sections(text: str, form_type: str | None = None) -> dict[str, str]:
    cleaned_text = _clean_extracted_text(text)
    normalized_form = normalize_form_type(form_type or "")
    structured_sections = _parse_structured_sections(cleaned_text, normalized_form)
    if structured_sections:
        return structured_sections
    return _parse_heading_sections(cleaned_text)


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


def _strip_html_noise(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()
        style = MULTISPACE_RE.sub("", (tag.get("style") or "").lower())
        classes = " ".join(tag.get("class", [])).lower()
        is_hidden = (
            tag.get("hidden") is not None
            or tag.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "opacity:0" in style
            or ("position:absolute" in style and "left:-" in style)
            or "-sec-ix-hidden" in classes
        )

        if name in DROP_TAGS or any(name.startswith(prefix) for prefix in DROP_TAG_PREFIXES) or is_hidden:
            tag.decompose()
        elif name in INLINE_XBRL_TAGS:
            tag.unwrap()


def _clean_extracted_text(text: str) -> str:
    normalized = (
        text.replace("\r", "\n")
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    lines: list[str] = []
    previous = ""
    for raw_line in normalized.splitlines():
        line = MULTISPACE_RE.sub(" ", raw_line.strip())
        if not line or _is_noise_line(line):
            continue
        if line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def _is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if URL_ONLY_RE.fullmatch(line):
        return True
    if len(line) <= 4 and line.isdigit():
        return True
    if lowered in METADATA_TOKENS:
        return True

    tokens = line.split()
    if not tokens:
        return False
    namespace_tokens = sum(1 for token in tokens if NAMESPACE_TOKEN_RE.fullmatch(token))
    metadata_tokens = namespace_tokens + sum(
        1 for token in tokens if DATE_TOKEN_RE.fullmatch(token) or CIK_TOKEN_RE.fullmatch(token)
    )
    if namespace_tokens and len(tokens) == 1:
        return True
    if namespace_tokens >= 2 and metadata_tokens / len(tokens) >= 0.6:
        return True
    if line.lower().startswith(("http://fasb.org/", "https://fasb.org/", "http://xbrl.", "https://xbrl.")):
        return True
    return False


def _parse_structured_sections(text: str, normalized_form: str) -> dict[str, str]:
    regexes = ANNUAL_SECTION_REGEXES if normalized_form in ANNUAL_FORMS else INTERIM_SECTION_REGEXES
    heading_matches: dict[str, tuple[int, int]] = {}

    for section_name, patterns in regexes.items():
        selected = _select_best_match(text, patterns)
        if selected:
            heading_matches[section_name] = selected

    if not heading_matches:
        return {}

    ordered_sections = sorted(heading_matches.items(), key=lambda item: item[1][0])
    parsed_sections: dict[str, str] = {}
    for index, (section_name, (start, end)) in enumerate(ordered_sections):
        next_selected_start = ordered_sections[index + 1][1][0] if index + 1 < len(ordered_sections) else len(text)
        next_item_start = _find_next_item_boundary(text, end) or len(text)
        next_start = min(next_selected_start, next_item_start)
        body = _sanitize_section_body(text[end:next_start])
        if body:
            parsed_sections[section_name] = body

    for subsection_name, subsection_patterns in SUBSECTION_REGEXES.items():
        subsection_match = _select_best_match(text, subsection_patterns)
        if not subsection_match:
            continue
        subsection_start, subsection_end = subsection_match
        next_section_start = min(
            (start for _, (start, _) in ordered_sections if start > subsection_start),
            default=len(text),
        )
        subsection_body = _sanitize_section_body(text[subsection_end:next_section_start])
        if subsection_body:
            parsed_sections[subsection_name] = subsection_body

    return {name: parsed_sections[name] for name in SECTION_ORDER if name in parsed_sections}


def _parse_heading_sections(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        matched = _match_heading_line(line)
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    cleaned_sections = {
        name: _sanitize_section_body("\n".join(body_lines))
        for name, body_lines in sections.items()
        if body_lines
    }
    return {name: cleaned_sections[name] for name in SECTION_ORDER if cleaned_sections.get(name)}


def _match_heading_line(line: str) -> str | None:
    lowered = line.lower()
    if len(line) > 140:
        return None
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("business", [])) and _looks_like_heading(line):
        return "business"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("risk_factors", [])) and _looks_like_heading(line):
        return "risk_factors"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("md&a", [])) and _looks_like_heading(line):
        return "md&a"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("financial_statements", [])) and _looks_like_heading(line):
        return "financial_statements"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("legal_proceedings", [])) and _looks_like_heading(line):
        return "legal_proceedings"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("liquidity", [])) and _looks_like_heading(line):
        return "liquidity"
    if any(pattern in lowered for pattern in FILING_SECTION_PATTERNS.get("subsequent_events", [])) and _looks_like_heading(line):
        return "subsequent_events"
    return None


def _looks_like_heading(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 18:
        return False
    if line.endswith(".") and len(words) > 4:
        return False
    title_cased = sum(1 for word in words if word[:1].isupper())
    return title_cased >= max(1, len(words) // 2)


def _select_best_match(text: str, patterns: Iterable[re.Pattern[str]]) -> tuple[int, int] | None:
    candidates: list[tuple[int, int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            score = _score_heading_match(text, match.start(), match.end())
            candidates.append((score, match.start(), match.end()))
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (item[0], item[1]))
    return best[1], best[2]


def _score_heading_match(text: str, start: int, end: int) -> int:
    before = text[max(0, start - 240) : start].lower()
    after = text[end : min(len(text), end + 900)]
    score = 0
    if "table of contents" in before or "table of contents" in after[:200].lower():
        score -= 8
    if re.match(r"\s*(?:part\s+[ivx]+\s*)?item\s+\d+[a-z]?\.", after, re.IGNORECASE):
        score -= 10
    if len(ITEM_HEADER_RE.findall(after[:250])) >= 4:
        score -= 4
    if len(re.findall(r"[.!?]", after[:900])) >= 3:
        score += 5
    if len(after.split()) >= 60:
        score += 4
    if start > len(text) * 0.1:
        score += 1
    return score


def _sanitize_section_body(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = MULTISPACE_RE.sub(" ", raw_line.strip())
        if not line or _is_noise_line(line):
            continue
        lines.append(line)
    if not lines:
        return ""
    body = "\n".join(lines).strip()
    if len(body) > 20000:
        body = body[:20000].rsplit(" ", 1)[0]
    return body


def _find_next_item_boundary(text: str, offset: int) -> int | None:
    match = ITEM_HEADER_RE.search(text, pos=max(offset, 0) + 1)
    return match.start() if match else None


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

    def reprocess_company_filings(self, company_id: int, limit: int | None = None) -> int:
        company = self.session.get(Company, company_id)
        if not company:
            raise ValueError(f"Unknown company id={company_id}")

        filings = self.session.scalars(
            select(Filing).where(Filing.company_id == company_id).order_by(Filing.filed_at.desc())
        ).all()
        updated = 0
        for filing in filings[: limit or None]:
            updated += int(self.reprocess_existing_filing(filing.id, commit=False))
        self.session.commit()
        return updated

    def reprocess_existing_filing(self, filing_id: int, *, commit: bool = True) -> bool:
        filing = self.session.get(Filing, filing_id)
        if not filing:
            raise ValueError(f"Unknown filing id={filing_id}")

        company = filing.company
        filing_doc = self.sec_client.download_primary_document(company.cik, filing.accession_number, filing.primary_document)
        raw_text = html_to_text(filing_doc.content, filing_doc.content_type)
        parsed_sections = parse_sections(raw_text, form_type=filing.form_type)
        raw_key, pdf_key, pdf_source = self._store_filing_artifacts(
            company=company,
            accession_number=filing.accession_number,
            primary_document=filing.primary_document,
            form_type=filing.form_type,
            filing_date=filing.filed_at.date().isoformat(),
            filing_doc=filing_doc,
            raw_text=raw_text,
            parsed_sections=parsed_sections,
        )

        filing.raw_text = raw_text
        filing.parsed_sections = parsed_sections
        filing.raw_artifact_key = raw_key
        filing.pdf_artifact_key = pdf_key
        filing.extra_metadata = {**(filing.extra_metadata or {}), "pdf_source": pdf_source}

        summary = self.summarizer.summarize(
            kind="filing",
            title=filing.title or f"{company.name} {filing.form_type}",
            text=self._summary_source_text(filing),
            company_name=company.name,
            evidence_sections=list(parsed_sections.keys()),
        )
        filing.summary_json = summary.model_dump()
        filing.summary_model = self.settings.openai_model if self.settings.openai_api_key else "fallback-local"
        filing.summary_prompt_version = self.settings.summary_prompt_version
        filing.summary_status = "complete"
        filing.summary_attempts += 1

        prior = self._prior_comparable_filing(company.id, filing)
        filing.prior_comparable_filing_id = prior.id if prior else None
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

        if commit:
            self.session.commit()
        return True

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
        parsed_sections = parse_sections(raw_text, form_type=form_type)
        raw_key, pdf_key, pdf_source = self._store_filing_artifacts(
            company=company,
            accession_number=accession_number,
            primary_document=primary_document,
            form_type=form_type,
            filing_date=filing_row.get("filingDate"),
            filing_doc=filing_doc,
            raw_text=raw_text,
            parsed_sections=parsed_sections,
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
                "pdf_source": pdf_source,
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

    def _store_filing_artifacts(
        self,
        *,
        company: Company,
        accession_number: str,
        primary_document: str | None,
        form_type: str,
        filing_date: str | None,
        filing_doc,
        raw_text: str,
        parsed_sections: dict[str, str],
    ) -> tuple[str, str, str]:
        raw_key = self.object_store.put_bytes(
            f"filings/raw/{company.cik}/{accession_number}-{primary_document or 'filing'}.txt",
            raw_text.encode("utf-8"),
            "text/plain",
        )
        pdf_source = "generated"
        if "pdf" in filing_doc.content_type.lower() or filing_doc.content.startswith(b"%PDF"):
            pdf_bytes = filing_doc.content
            pdf_source = "original"
        elif "html" in filing_doc.content_type.lower() and self.settings.enable_browser_pdf_rendering:
            try:
                pdf_bytes = render_html_to_pdf(
                    filing_doc.content,
                    source_url=filing_doc.source_url,
                    timeout_seconds=self.settings.browser_pdf_timeout_seconds,
                )
                pdf_source = "rendered-html"
            except Exception:
                pdf_sections = [(name, parsed_sections[name]) for name in SECTION_ORDER if name in parsed_sections]
                pdf_bytes = build_pdf_from_text(
                    f"{company.name} {form_type} filed {filing_date}",
                    raw_text[:60000],
                    sections=pdf_sections or None,
                )
                pdf_source = "generated-fallback"
        else:
            pdf_sections = [(name, parsed_sections[name]) for name in SECTION_ORDER if name in parsed_sections]
            pdf_bytes = build_pdf_from_text(
                f"{company.name} {form_type} filed {filing_date}",
                raw_text[:60000],
                sections=pdf_sections or None,
            )
        pdf_key = self.object_store.put_bytes(
            f"filings/pdf/{company.cik}/{accession_number}.pdf",
            pdf_bytes,
            "application/pdf",
        )
        return raw_key, pdf_key, pdf_source

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
        return (datetime.now(UTC) - relativedelta(years=years_back)).date()

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
