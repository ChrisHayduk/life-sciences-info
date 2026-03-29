from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Comment
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Filing, FilingNewsLink, NewsItem, Watchlist
from app.schemas import FilingDetail, FilingListItem
from app.services.constants import (
    ANNUAL_FORMS,
    EIGHT_K_ITEM_TOPICS,
    FILING_SECTION_PATTERNS,
    INTERIM_FORMS,
    MATERIAL_EIGHT_K_ITEMS,
    TARGET_FORMS,
)
from app.services.html_pdf import render_html_to_pdf
from app.services.market_data import MarketDataClient
from app.services.pdf import build_pdf_from_text
from app.services.ranking import (
    company_market_cap_percentiles,
    compute_filing_scores,
    compute_pending_filing_scores,
    filing_priority_reason,
    freshness_bucket,
    personal_relevance_score,
    summary_priority_score,
)
from app.services.sec import SECClient
from app.services.storage import ObjectStore
from app.services.summary_budget import SummaryBudgetService
from app.services.summarization import OpenAISummarizer, UsageMetrics

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
COMPANY_FILING_TYPE_PRIORITY = {
    "10-K": 0,
    "20-F": 1,
    "40-F": 2,
    "10-Q": 3,
    "8-K": 4,
    "6-K": 5,
}
ITEM_HEADER_RE = re.compile(r"(?im)^\s*(?:part\s+[ivx]+\s*)?item\s+\d+[a-z]?\.")
URL_ONLY_RE = re.compile(r"^(?:https?://\S+\s*)+$", re.IGNORECASE)
NAMESPACE_TOKEN_RE = re.compile(r"^[a-z][\w.-]*:[\w.-]+$", re.IGNORECASE)
DATE_TOKEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CIK_TOKEN_RE = re.compile(r"^\d{8,10}$")
MULTISPACE_RE = re.compile(r"[ \t]+")
ITEM_NUMBER_RE = re.compile(r"\b\d\.\d{2}\b")

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
        "guidance",
        "approval",
        "partnership",
        "collaboration",
        "leadership",
        "financing",
    ]
    return any(keyword in lowered for keyword in keywords)


def extract_item_numbers(value: str | None) -> list[str]:
    return sorted(set(ITEM_NUMBER_RE.findall(value or "")))


def is_material_8k(item_numbers: list[str], title: str | None, text: str) -> bool:
    if any(item in MATERIAL_EIGHT_K_ITEMS for item in item_numbers):
        return True
    lowered = " ".join(filter(None, [title or "", text[:6000]])).lower()
    keywords = [
        "earnings",
        "guidance",
        "approval",
        "complete response letter",
        "partnership",
        "collaboration",
        "acquisition",
        "merger",
        "chief executive",
        "chief financial",
        "financing",
        "offering",
    ]
    return any(keyword in lowered for keyword in keywords)


def infer_filing_event_type(normalized_form_type: str, item_numbers: list[str], title: str | None, raw_text: str | None) -> str | None:
    if normalized_form_type in {"10-K", "20-F", "40-F"}:
        return "annual-report"
    if normalized_form_type == "10-Q":
        return "quarterly-report"
    if normalized_form_type == "6-K":
        lowered = " ".join(filter(None, [title or "", (raw_text or "")[:4000]])).lower()
        if "earnings" in lowered or "results" in lowered:
            return "earnings"
        if "approval" in lowered or "fda" in lowered:
            return "regulatory"
        if "partnership" in lowered or "collaboration" in lowered:
            return "material-agreement"
        return "foreign-issuer-update"
    if normalized_form_type == "8-K":
        for item in item_numbers:
            topic = EIGHT_K_ITEM_TOPICS.get(item)
            if topic:
                return topic
        return "current-event"
    return None


def filing_dedupe_group_id(company_id: int, filing: Filing | None = None, *, accession_number: str | None = None, event_type: str | None = None, filed_at: datetime | None = None) -> str:
    if accession_number:
        return f"filing:{accession_number}"
    date_key = (filed_at or filing.filed_at).date().isoformat() if (filed_at or (filing.filed_at if filing else None)) else "unknown"
    accession = accession_number or (filing.accession_number if filing else "unknown")
    return f"{company_id}:{event_type or 'filing'}:{date_key}:{accession}"


def watchlist_company_ids(session: Session) -> set[int]:
    watchlists = session.scalars(select(Watchlist)).all()
    ids: set[int] = set()
    for watchlist in watchlists:
        ids.update(int(company_id) for company_id in (watchlist.company_ids or []))
    return ids


def _strip_html_noise(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for tag in list(soup.find_all(True)):
        if getattr(tag, "attrs", None) is None:
            continue
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
                created += int(self._ingest_filing_row(company, filing_row, ingest_origin="historical_backfill"))
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
                    created += int(self._ingest_filing_row(company, filing_row, ingest_origin="sec_poll"))
                except Exception:
                    continue
        self.session.commit()
        return created

    def reprocess_company_filings(
        self,
        company_id: int,
        limit: int | None = None,
        *,
        resummarize: bool = True,
        max_summaries: int = 5,
    ) -> int:
        """Reprocess filings for a company. Limits AI summarization to max_summaries
        to prevent budget spikes. Remaining filings are reprocessed for text/PDF
        but left in 'pending' summary status for scheduled pickup."""
        company = self.session.get(Company, company_id)
        if not company:
            raise ValueError(f"Unknown company id={company_id}")

        filing_ids = self.session.scalars(
            select(Filing.id).where(Filing.company_id == company_id).order_by(Filing.filed_at.desc())
        ).all()
        updated = 0
        summaries_done = 0
        for filing_id in filing_ids[: limit or None]:
            should_summarize = resummarize and summaries_done < max_summaries
            updated += int(self.reprocess_existing_filing(filing_id, commit=True, resummarize=should_summarize))
            if should_summarize:
                summaries_done += 1
            self.session.expunge_all()
        return updated

    def reprocess_existing_filing(self, filing_id: int, *, commit: bool = True, resummarize: bool = True) -> bool:
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
        filing.event_type = infer_filing_event_type(
            filing.normalized_form_type,
            filing.item_numbers or [],
            filing.title,
            raw_text,
        )
        filing.source_type = "official_filing"
        filing.is_official_source = True
        filing.dedupe_group_id = filing_dedupe_group_id(
            company.id,
            filing,
            event_type=filing.event_type,
        )
        filing.freshness_bucket = freshness_bucket(filing.filed_at)
        previous_summary_hash = (filing.extra_metadata or {}).get("summary_source_hash")
        summary_source_hash = hashlib.sha256(self._summary_source_text(filing).encode("utf-8")).hexdigest()
        filing.extra_metadata = {
            **(filing.extra_metadata or {}),
            "pdf_source": pdf_source,
            "summary_source_hash": summary_source_hash,
        }

        prior = self._prior_comparable_filing(company.id, filing)
        filing.prior_comparable_filing_id = prior.id if prior else None
        if resummarize:
            self._apply_summary(filing, company, prior_filing=prior, trigger="manual", summary_tier="full_ai")
        else:
            if not filing.summary_json:
                filing.summary_status = "pending"
                filing.summary_tier = "no_ai"
            elif (
                filing.summary_prompt_version != self.settings.summary_prompt_version
                or previous_summary_hash != summary_source_hash
            ):
                filing.summary_status = "stale"
            self._apply_scores(filing, company, prior_filing=prior)

        if commit:
            self.session.commit()
        return True

    def _ingest_filing_row(self, company: Company, filing_row: dict[str, Any], *, ingest_origin: str) -> bool:
        form_type = (filing_row.get("form") or "").upper()
        if not is_target_form(form_type):
            return False
        normalized_form_type = normalize_form_type(form_type)
        accession_number = filing_row.get("accessionNumber")
        if not accession_number:
            return False
        existing = self.session.scalar(select(Filing).where(Filing.accession_number == accession_number))
        if existing:
            return False

        primary_document = filing_row.get("primaryDocument")
        filing_doc = self.sec_client.download_primary_document(company.cik, accession_number, primary_document)
        raw_text = html_to_text(filing_doc.content, filing_doc.content_type)
        item_numbers = extract_item_numbers(filing_row.get("items"))

        if normalized_form_type == "6-K" and not is_periodic_6k(
            filing_row.get("primaryDocDescription"),
            raw_text,
            filing_row.get("items"),
        ):
            return False
        if normalized_form_type == "8-K" and not is_material_8k(
            item_numbers,
            filing_row.get("primaryDocDescription"),
            raw_text,
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

        event_type = infer_filing_event_type(
            normalized_form_type,
            item_numbers,
            filing_row.get("primaryDocDescription"),
            raw_text,
        )
        filing = Filing(
            company_id=company.id,
            accession_number=accession_number,
            form_type=form_type,
            normalized_form_type=normalized_form_type,
            title=filing_row.get("primaryDocDescription") or f"{company.name} {form_type}",
            description=filing_row.get("primaryDocDescription"),
            filed_at=self._parse_datetime(filing_row.get("acceptanceDateTime") or filing_row.get("filingDate")),
            period_end_date=self._parse_date(filing_row.get("reportDate")),
            is_amendment=form_type.endswith("/A"),
            is_periodic_equivalent=normalized_form_type != "8-K",
            filing_url=filing_urls["filing_url"],
            original_document_url=filing_urls["original_document_url"],
            source_json_url=None,
            primary_document=primary_document,
            raw_text=raw_text,
            parsed_sections=parsed_sections,
            raw_artifact_key=raw_key,
            pdf_artifact_key=pdf_key,
            item_numbers=item_numbers,
            source_type="official_filing",
            event_type=event_type,
            is_official_source=True,
            dedupe_group_id=filing_dedupe_group_id(
                company.id,
                accession_number=accession_number,
                event_type=event_type,
                filed_at=self._parse_datetime(filing_row.get("acceptanceDateTime") or filing_row.get("filingDate")),
            ),
            freshness_bucket=freshness_bucket(self._parse_datetime(filing_row.get("acceptanceDateTime") or filing_row.get("filingDate"))),
            extra_metadata={
                "items": filing_row.get("items"),
                "size": filing_row.get("size"),
                "filmNumber": filing_row.get("filmNumber"),
                "pdf_source": pdf_source,
                "ingest_origin": ingest_origin,
            },
        )
        self.session.add(filing)
        self.session.flush()

        self._refresh_market_cap(company)
        prior = self._prior_comparable_filing(company.id, filing)
        if prior:
            filing.prior_comparable_filing_id = prior.id
        filing.summary_status = "pending"
        filing.summary_tier = "no_ai"
        self._apply_scores(filing, company, prior_filing=prior)
        return True

    def summarize_pending(
        self,
        *,
        limit: int | None = None,
        automated: bool = True,
        include_historical: bool = False,
    ) -> dict[str, int]:
        budget_service = SummaryBudgetService(self.session)
        remaining_daily = (
            budget_service.remaining("filing")
            if automated and self.settings.openai_api_key
            else max(limit or 0, self.settings.max_filing_summaries_per_run)
        )
        remaining_override = budget_service.remaining("override") if automated and self.settings.openai_api_key else 0
        effective_limit = limit or self.settings.max_filing_summaries_per_run

        if effective_limit <= 0:
            return {
                "summarized": 0,
                "remaining_daily_budget": remaining_daily,
                "remaining_daily_budget_usd": round(budget_service.remaining_usd("filing"), 4) if self.settings.openai_api_key else 0.0,
            }

        raw_candidates = self.session.execute(
            select(Filing, Company)
            .join(Company, Filing.company_id == Company.id)
            .where(Filing.summary_status.in_(["pending", "failed", "stale"]), Filing.summary_attempts < 3)
        ).all()
        market_caps = company_market_cap_percentiles(self.session)
        watchlist_ids = watchlist_company_ids(self.session)
        candidates = sorted(
            raw_candidates,
            key=lambda row: summary_priority_score(row[0], market_caps.get(row[1].id, 0.0))
            + (20.0 if row[1].id in watchlist_ids else 0.0),
            reverse=True,
        )

        cutoff = datetime.now(UTC) - timedelta(days=self.settings.filing_summary_backlog_days)
        summarized = 0
        for filing, company in candidates:
            ingest_origin = (filing.extra_metadata or {}).get("ingest_origin")
            if automated and not include_historical and ingest_origin != "sec_poll":
                continue
            filed_at = filing.filed_at
            if filed_at.tzinfo is None:
                filed_at = filed_at.replace(tzinfo=UTC)
            if automated and filed_at < cutoff:
                continue
            is_override = self._qualifies_for_priority_override(filing, company.id in watchlist_ids)
            if automated and self.settings.openai_api_key:
                budget_kind = self._select_automated_budget_kind(
                    budget_service,
                    primary_kind="filing",
                    allow_override=is_override,
                )
                if budget_kind is None:
                    continue
            else:
                budget_kind = "filing"
            prior = self._prior_comparable_filing(company.id, filing)
            try:
                preferred_tier = self._summary_tier_for_filing(
                    filing,
                    automated=automated,
                    watchlist_match=company.id in watchlist_ids,
                )
                summary_tier = self._resolve_summary_tier(
                    budget_service,
                    preferred_tier=preferred_tier,
                    automated=automated,
                )
                if summary_tier is None:
                    continue
                self._apply_summary(
                    filing,
                    company,
                    prior_filing=prior,
                    trigger="auto" if automated else "manual",
                    summary_tier=summary_tier,
                    budget_kind=budget_kind,
                )
            except Exception:
                filing.summary_status = "failed"
                filing.summary_attempts += 1
                continue
            summarized += 1
            if summarized >= effective_limit:
                break

        self.session.commit()
        remaining = budget_service.remaining("filing") if self.settings.openai_api_key else 0
        return {
            "summarized": summarized,
            "remaining_daily_budget": remaining,
            "remaining_daily_budget_usd": round(budget_service.remaining_usd("filing"), 4) if self.settings.openai_api_key else 0.0,
        }

    def summarize_item(
        self,
        filing_id: int,
        *,
        consume_override_budget: bool = False,
        force: bool = False,
    ) -> dict[str, int | str]:
        filing = self.session.get(Filing, filing_id)
        if not filing:
            raise ValueError(f"Unknown filing id={filing_id}")
        if not force and filing.summary_status == "complete":
            return {"status": "already_complete", "remaining_override_budget": self._remaining_override_budget()}

        company = filing.company
        budget_service = SummaryBudgetService(self.session)
        if consume_override_budget and self.settings.openai_api_key and not budget_service.has_capacity("override"):
            raise RuntimeError("override_budget_exhausted")

        prior = self._prior_comparable_filing(company.id, filing)
        self._apply_summary(
            filing,
            company,
            prior_filing=prior,
            trigger="manual",
            summary_tier="full_ai",
            budget_kind="override" if consume_override_budget else None,
        )
        self.session.commit()
        return {"status": "summarized", "remaining_override_budget": self._remaining_override_budget()}

    def rerank_for_companies(self, company_ids: Iterable[int] | None = None) -> int:
        target_ids = sorted({int(company_id) for company_id in (company_ids or [])})
        if company_ids is not None and not target_ids:
            return 0

        company_query = select(Company).where(Company.is_active.is_(True))
        if target_ids:
            company_query = company_query.where(Company.id.in_(target_ids))
        companies = self.session.scalars(company_query).all()
        if not companies:
            return 0

        companies_by_id = {company.id: company for company in companies}
        filing_query = select(Filing).order_by(Filing.company_id.asc(), Filing.filed_at.asc(), Filing.id.asc())
        if target_ids:
            filing_query = filing_query.where(Filing.company_id.in_(target_ids))
        filings = self.session.scalars(filing_query).all()
        market_cap_scores = company_market_cap_percentiles(self.session)

        prior_by_group: dict[tuple[int, str], Filing] = {}
        updated = 0
        for filing in filings:
            company = companies_by_id.get(filing.company_id)
            if not company:
                continue
            group = comparable_group(filing.normalized_form_type)
            prior = prior_by_group.get((filing.company_id, group))
            filing.prior_comparable_filing_id = prior.id if prior else None
            self._apply_scores(filing, company, prior_filing=prior, market_cap_scores=market_cap_scores)
            prior_by_group[(filing.company_id, group)] = filing
            updated += 1

        self.session.commit()
        return updated

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

    def _apply_summary(
        self,
        filing: Filing,
        company: Company,
        *,
        prior_filing: Filing | None,
        trigger: str,
        summary_tier: str,
        budget_kind: str | None,
    ) -> None:
        summary_source_text = self._summary_source_text(filing, summary_tier=summary_tier)
        model = self._model_for_summary(summary_tier=summary_tier, trigger=trigger)
        prompt_cache_key = self._summary_prompt_cache_key(filing, summary_tier=summary_tier, model=model)
        if hasattr(self.summarizer, "summarize_with_usage"):
            result = self.summarizer.summarize_with_usage(
                kind="filing",
                title=filing.title or f"{company.name} {filing.form_type}",
                text=summary_source_text,
                company_name=company.name,
                evidence_sections=list((filing.parsed_sections or {}).keys()),
                form_type=filing.form_type,
                model=model,
                prompt_cache_key=prompt_cache_key,
            )
            summary = result.payload
            usage = result.usage
        else:
            summary = self.summarizer.summarize(
                kind="filing",
                title=filing.title or f"{company.name} {filing.form_type}",
                text=summary_source_text,
                company_name=company.name,
                evidence_sections=list((filing.parsed_sections or {}).keys()),
                form_type=filing.form_type,
            )
            usage = UsageMetrics(model=model if self.settings.openai_api_key else "fallback-local")

        filing.summary_json = summary.model_dump()
        filing.summary_model = usage.model
        filing.summary_prompt_version = self.settings.summary_prompt_version
        filing.summary_status = "complete"
        filing.summary_tier = summary_tier
        filing.summary_attempts += 1
        filing.extra_metadata = {
            **(filing.extra_metadata or {}),
            "summary_trigger": trigger,
            "summary_source_hash": hashlib.sha256(self._summary_source_text(filing, summary_tier="full_ai").encode("utf-8")).hexdigest(),
        }
        self._apply_scores(filing, company, prior_filing=prior_filing)
        self._record_usage(
            budget_kind,
            self._summary_usage_kind(summary_tier),
            usage,
        )

        # Generate diff analysis for periodic filings with a prior comparable
        if (
            prior_filing
            and prior_filing.summary_status == "complete"
            and filing.normalized_form_type not in ("8-K",)
            and self.settings.openai_api_key
        ):
            budget_service = SummaryBudgetService(self.session)
            if budget_service.has_capacity("diff"):
                try:
                    diff_model = self.settings.openai_model_diff
                    diff_prompt_cache_key = (
                        f"diff:{filing.normalized_form_type or filing.form_type}:{self.settings.summary_prompt_version}:{diff_model}"
                    )
                    if hasattr(self.summarizer, "summarize_diff_with_usage"):
                        diff_call = self.summarizer.summarize_diff_with_usage(
                            form_type=filing.form_type,
                            company_name=company.name,
                            current_text=self._summary_source_text(filing),
                            prior_text=self._summary_source_text(prior_filing),
                            model=diff_model,
                            prompt_cache_key=diff_prompt_cache_key,
                        )
                        diff_result = diff_call.payload
                        diff_usage = diff_call.usage
                    else:
                        diff_result = self.summarizer.summarize_diff(
                            form_type=filing.form_type,
                            company_name=company.name,
                            current_text=self._summary_source_text(filing),
                            prior_text=self._summary_source_text(prior_filing),
                        )
                        diff_usage = UsageMetrics(model=diff_model)
                    filing.diff_json = diff_result
                    filing.diff_status = "complete" if "summary" in diff_result else "failed"
                    if "summary" in diff_result:
                        budget_service.record(
                            "diff",
                            1,
                            prompt_tokens=diff_usage.prompt_tokens,
                            completion_tokens=diff_usage.completion_tokens,
                            reasoning_tokens=diff_usage.reasoning_tokens,
                            cached_input_tokens=diff_usage.cached_input_tokens,
                            estimated_cost_usd=diff_usage.estimated_cost_usd,
                            model=diff_usage.model,
                        )
                except Exception:
                    filing.diff_status = "failed"

    def _apply_scores(
        self,
        filing: Filing,
        company: Company,
        *,
        prior_filing: Filing | None,
        market_cap_scores: dict[int, float] | None = None,
    ) -> None:
        market_cap_scores = market_cap_scores or company_market_cap_percentiles(self.session)
        if filing.summary_status == "complete":
            scores = compute_filing_scores(
                filing,
                company_market_cap_score=market_cap_scores.get(company.id, 0.0),
                has_market_cap=company.market_cap is not None,
                prior_filing=prior_filing,
            )
        else:
            scores = compute_pending_filing_scores(
                filing,
                company_market_cap_score=market_cap_scores.get(company.id, 0.0),
                has_market_cap=company.market_cap is not None,
            )
        filing.market_cap_score = float(scores["market_cap_score"])
        filing.importance_score = float(scores["importance_score"])
        filing.impact_score = float(scores["impact_score"])
        filing.composite_score = float(scores["composite_score"])
        filing.score_confidence = str(scores["score_confidence"])
        filing.score_explanation = dict(scores["score_explanation"])
        filing.freshness_bucket = freshness_bucket(filing.filed_at)
        filing.priority_reason = filing_priority_reason(
            filing,
            company_market_cap_score=filing.market_cap_score,
            impact_score=filing.impact_score,
            recency=float((filing.score_explanation or {}).get("components", {}).get("recency", 0.0)),
        )

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

    def _summary_source_text(self, filing: Filing, *, summary_tier: str = "full_ai") -> str:
        section_text = []
        for section_name, section_body in filing.parsed_sections.items():
            limit = 1800 if summary_tier == "short_ai" else 3000
            section_text.append(f"[{section_name}]\n{section_body[:limit]}")
        if section_text:
            max_sections = 3 if summary_tier == "short_ai" else len(section_text)
            return "\n\n".join(section_text[:max_sections])
        return (filing.raw_text or "")[:8000 if summary_tier == "short_ai" else 18000]

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

    def list_filings(
        self,
        limit: int = 50,
        company_id: int | None = None,
        recent_days: int | None = None,
        watchlist_id: int | None = None,
        sort_mode: str = "importance",
    ) -> list[FilingListItem]:
        query = select(Filing, Company).join(Company, Filing.company_id == Company.id)
        watchlist_company_match: set[int] = set()
        if watchlist_id is not None:
            watchlist = self.session.get(Watchlist, watchlist_id)
            if watchlist:
                watchlist_company_match = {int(value) for value in (watchlist.company_ids or [])}
                query = query.where(Filing.company_id.in_(watchlist_company_match))
            else:
                return []
        if company_id:
            query = query.where(Filing.company_id == company_id)
            query = query.order_by(
                case(COMPANY_FILING_TYPE_PRIORITY, value=Filing.normalized_form_type, else_=99),
                Filing.filed_at.desc(),
                Filing.composite_score.desc(),
            )
        elif sort_mode == "freshness":
            query = query.order_by(Filing.filed_at.desc(), Filing.composite_score.desc())
        elif sort_mode == "personal":
            query = query.order_by(Filing.filed_at.desc(), Filing.composite_score.desc())
        else:
            query = query.order_by(Filing.composite_score.desc(), Filing.filed_at.desc())
        if recent_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=recent_days)
            query = query.where(Filing.filed_at >= cutoff)
        rows = self.session.execute(query.limit(limit * (3 if watchlist_company_match else 1))).all()
        if not company_id and sort_mode == "personal":
            rows = sorted(
                rows,
                key=lambda row: personal_relevance_score(
                    composite_score=row[0].composite_score,
                    published_at=row[0].filed_at,
                    is_official_source=True,
                    watchlist_match=row[1].id in watchlist_company_match if watchlist_company_match else False,
                    event_type=row[0].event_type,
                ),
                reverse=True,
            )
        return [self._to_list_item(filing, company) for filing, company in rows]

    def list_filings_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        company_id: int | None = None,
        form_type: str | None = None,
        search: str | None = None,
        sort_by: str = "composite_score",
        recent_days: int | None = None,
        watchlist_id: int | None = None,
        sort_mode: str | None = None,
    ) -> dict:
        query = select(Filing, Company).join(Company, Filing.company_id == Company.id)
        count_query = select(func.count()).select_from(Filing).join(Company, Filing.company_id == Company.id)
        watchlist_company_match: set[int] = set()

        if company_id:
            query = query.where(Filing.company_id == company_id)
            count_query = count_query.where(Filing.company_id == company_id)
        if watchlist_id is not None:
            watchlist = self.session.get(Watchlist, watchlist_id)
            if watchlist:
                watchlist_company_match = {int(value) for value in (watchlist.company_ids or [])}
                query = query.where(Filing.company_id.in_(watchlist_company_match))
                count_query = count_query.where(Filing.company_id.in_(watchlist_company_match))
            else:
                return {"items": [], "total": 0, "offset": offset, "limit": limit}
        if form_type:
            query = query.where(Filing.normalized_form_type == form_type)
            count_query = count_query.where(Filing.normalized_form_type == form_type)
        if search:
            pattern = f"%{search}%"
            search_filter = Filing.title.ilike(pattern) | Company.name.ilike(pattern) | Company.ticker.ilike(pattern)
            query = query.where(search_filter)
            count_query = count_query.where(Filing.title.ilike(pattern) | Company.name.ilike(pattern) | Company.ticker.ilike(pattern))
        if recent_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=recent_days)
            query = query.where(Filing.filed_at >= cutoff)
            count_query = count_query.where(Filing.filed_at >= cutoff)

        effective_sort = sort_mode or ("freshness" if sort_by == "filed_at" else "importance")
        if effective_sort == "freshness":
            query = query.order_by(Filing.filed_at.desc(), Filing.composite_score.desc())
        elif effective_sort == "personal":
            query = query.order_by(Filing.filed_at.desc(), Filing.composite_score.desc())
        else:
            query = query.order_by(Filing.composite_score.desc(), Filing.filed_at.desc())

        total = self.session.scalar(count_query) or 0
        rows = self.session.execute(query.offset(offset).limit(limit)).all()
        if effective_sort == "personal":
            rows = sorted(
                rows,
                key=lambda row: personal_relevance_score(
                    composite_score=row[0].composite_score,
                    published_at=row[0].filed_at,
                    is_official_source=True,
                    watchlist_match=row[1].id in watchlist_company_match if watchlist_company_match else False,
                    event_type=row[0].event_type,
                ),
                reverse=True,
            )
        items = [self._to_list_item(filing, company) for filing, company in rows]
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def get_filing_detail(self, filing_id: int) -> FilingDetail | None:
        row = self.session.execute(
            select(Filing, Company).join(Company, Filing.company_id == Company.id).where(Filing.id == filing_id)
        ).first()
        if not row:
            return None
        filing, company = row
        summary = filing.summary_json or {}
        base = self._to_list_item(filing, company)

        # Fetch related news via FilingNewsLink
        from app.services.news import NewsService
        related_news_items = self.session.scalars(
            select(NewsItem)
            .join(FilingNewsLink, FilingNewsLink.news_item_id == NewsItem.id)
            .where(FilingNewsLink.filing_id == filing_id)
            .order_by(FilingNewsLink.confidence.desc())
            .limit(5)
        ).all()
        news_service = NewsService(self.session)
        related_news = [news_service._to_response(n) for n in related_news_items]

        return FilingDetail(
            **base.model_dump(),
            parsed_sections=filing.parsed_sections or {},
            key_takeaways=summary.get("key_takeaways", []),
            material_changes=summary.get("material_changes", []),
            risk_flags=summary.get("risk_flags", []),
            opportunity_flags=summary.get("opportunity_flags", []),
            evidence_sections=summary.get("evidence_sections", []),
            entities=summary.get("entities", []),
            prior_comparable_filing_id=filing.prior_comparable_filing_id,
            prior_comparable_filing_url=(
                f"{self.settings.frontend_base_url}/filings/{filing.prior_comparable_filing_id}"
                if filing.prior_comparable_filing_id
                else None
            ),
            diff_json=filing.diff_json or {},
            diff_status=filing.diff_status or "pending",
            related_news=related_news,
        )

    def _to_list_item(self, filing: Filing, company: Company) -> FilingListItem:
        summary = filing.summary_json or {}
        summary_text = summary.get("summary") or self._fallback_summary(filing)
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
            summary_status=filing.summary_status,
            summary_tier=filing.summary_tier or "no_ai",
            source_type=filing.source_type or "official_filing",
            event_type=filing.event_type,
            priority_reason=filing.priority_reason or "",
            is_official_source=bool(filing.is_official_source),
            dedupe_group_id=filing.dedupe_group_id,
            freshness_bucket=filing.freshness_bucket or freshness_bucket(filing.filed_at),
            summary=summary_text,
            original_document_url=filing.original_document_url,
            pdf_download_url=(
                f"{self.settings.api_base_url}{self.settings.api_prefix}/artifacts/filings/{filing.id}/pdf"
                if filing.pdf_artifact_key
                else None
            ),
        )

    def _fallback_summary(self, filing: Filing) -> str:
        if filing.title and filing.normalized_form_type == "8-K":
            return filing.title
        if filing.event_type and filing.title and filing.normalized_form_type in {"8-K", "6-K"}:
            return f"{filing.event_type.replace('-', ' ').capitalize()}: {filing.title}"
        if filing.item_numbers and filing.normalized_form_type == "8-K":
            items = ", ".join(filing.item_numbers[:3])
            return f"Current event filing covering item {items}."
        for section_name in ("md&a", "business", "risk_factors", "legal_proceedings", "financial_statements"):
            section_text = (filing.parsed_sections or {}).get(section_name)
            if not section_text:
                continue
            section_lines = [line.strip() for line in section_text.splitlines() if line.strip()]
            snippet = ""
            for line in section_lines:
                if len(line.split()) <= 8 and _looks_like_heading(line):
                    continue
                snippet = line
                break
            if not snippet and section_lines:
                snippet = section_lines[0]
            if len(snippet) > 240:
                snippet = snippet[:237].rsplit(" ", 1)[0] + "..."
            return snippet
        description = filing.description or filing.title or ""
        return description[:240]

    @staticmethod
    def _qualifies_for_priority_override(filing: Filing, watchlist_match: bool) -> bool:
        return bool(
            watchlist_match
            or filing.normalized_form_type == "8-K"
            or filing.event_type in {"results-of-operations", "acquisition-disposition", "leadership-change", "material-agreement", "regulatory"}
        )

    @staticmethod
    def _summary_tier_for_filing(filing: Filing, *, automated: bool, watchlist_match: bool) -> str:
        if not automated:
            return "full_ai"
        if filing.normalized_form_type in {"10-K", "20-F", "40-F", "8-K"}:
            return "full_ai"
        if watchlist_match or filing.event_type in {"results-of-operations", "regulatory"}:
            return "full_ai"
        return "short_ai"

    def _remaining_override_budget(self) -> int:
        if not self.settings.openai_api_key:
            return 0
        return SummaryBudgetService(self.session).remaining("override")

    def pending_queue_counts(self, *, include_historical: bool = False) -> dict[str, int]:
        watchlist_ids = watchlist_company_ids(self.session)
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.filing_summary_backlog_days)
        counts = {"filings_pending": 0, "filings_pending_full_ai": 0, "filings_pending_short_ai": 0}
        rows = self.session.execute(
            select(Filing, Company)
            .join(Company, Filing.company_id == Company.id)
            .where(Filing.summary_status.in_(["pending", "failed", "stale"]), Filing.summary_attempts < 3)
        ).all()
        for filing, company in rows:
            ingest_origin = (filing.extra_metadata or {}).get("ingest_origin")
            if not include_historical and ingest_origin != "sec_poll":
                continue
            filed_at = filing.filed_at if filing.filed_at.tzinfo else filing.filed_at.replace(tzinfo=UTC)
            if filed_at < cutoff:
                continue
            counts["filings_pending"] += 1
            tier = self._summary_tier_for_filing(
                filing,
                automated=True,
                watchlist_match=company.id in watchlist_ids,
            )
            counts[f"filings_pending_{tier}"] += 1
        return counts

    def _resolve_summary_tier(
        self,
        budget_service: SummaryBudgetService,
        *,
        preferred_tier: str,
        automated: bool,
    ) -> str | None:
        if not automated or not self.settings.openai_api_key:
            return preferred_tier
        if preferred_tier == "full_ai":
            if budget_service.remaining("filing_full_ai") > 0:
                return "full_ai"
            if budget_service.remaining("filing_short_ai") > 0:
                return "short_ai"
            return None
        if budget_service.remaining("filing_short_ai") > 0:
            return "short_ai"
        return None

    @staticmethod
    def _select_automated_budget_kind(
        budget_service: SummaryBudgetService,
        *,
        primary_kind: str,
        allow_override: bool,
    ) -> str | None:
        if budget_service.has_capacity(primary_kind):
            return primary_kind
        if allow_override and budget_service.has_capacity("override"):
            return "override"
        return None

    def _model_for_summary(self, *, summary_tier: str, trigger: str) -> str:
        if trigger == "manual":
            return self.settings.openai_model_manual
        if summary_tier == "short_ai":
            return self.settings.openai_model_summary_short
        return self.settings.openai_model_summary_full

    @staticmethod
    def _summary_usage_kind(summary_tier: str) -> str:
        return "filing_short_ai" if summary_tier == "short_ai" else "filing_full_ai"

    def _summary_prompt_cache_key(self, filing: Filing, *, summary_tier: str, model: str) -> str:
        form_group = filing.normalized_form_type or filing.form_type or "filing"
        return f"summary:filing:{summary_tier}:{form_group}:{self.settings.summary_prompt_version}:{model}"

    def _record_usage(self, budget_kind: str | None, tier_kind: str, usage: UsageMetrics) -> None:
        if not self.settings.openai_api_key or budget_kind is None:
            return
        budget_service = SummaryBudgetService(self.session)
        budget_service.record(
            budget_kind,
            1,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
            model=usage.model,
        )
        budget_service.record(tier_kind, 1)
