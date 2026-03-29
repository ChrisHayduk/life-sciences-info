"""Clinical trial ingestion and query services."""

from __future__ import annotations

import contextlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import sleep
from typing import Any, Callable

import httpx
import psycopg
from psycopg.rows import dict_row
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ClinicalTrial, Company

logger = logging.getLogger(__name__)

CT_API_BASE = "https://clinicaltrials.gov/api/v2"
AACT_DEFAULT_HOST = "aact-db.ctti-clinicaltrials.org"
AACT_DEFAULT_PORT = 5432
AACT_DEFAULT_DBNAME = "aact"

PHASE_ORDER = {
    "Phase 3": 0,
    "Phase 2/Phase 3": 1,
    "Phase 2": 2,
    "Phase 1/Phase 2": 3,
    "Phase 1": 4,
    "Early Phase 1": 5,
    "Phase 4": 6,
    "Not Applicable": 7,
}

CURRENT_OR_UPCOMING_STATUSES = {
    "active, not recruiting",
    "available",
    "enrolling by invitation",
    "not yet recruiting",
    "recruiting",
}

LEGAL_SUFFIX_TOKENS = {
    "ag",
    "co",
    "company",
    "companies",
    "corp",
    "corporation",
    "gmbh",
    "holding",
    "holdings",
    "inc",
    "incorporated",
    "kgaa",
    "limited",
    "llc",
    "lp",
    "ltd",
    "nv",
    "plc",
    "sa",
    "sarl",
    "se",
    "spa",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_trial_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _compact_trial_name(value: str | None) -> str:
    return _normalize_trial_name(value).replace(" ", "")


def _core_compact_trial_name(value: str | None) -> str:
    tokens = _normalize_trial_name(value).split()
    trimmed = list(tokens)
    while trimmed and trimmed[-1] in LEGAL_SUFFIX_TOKENS:
        trimmed.pop()
    if not trimmed:
        trimmed = tokens
    return "".join(trimmed)


@dataclass(frozen=True)
class TrialAlias:
    original: str
    raw_lower: str
    compact: str
    core_compact: str
    tokens: tuple[str, ...]
    loose_pattern: str | None


@dataclass
class TrialPayload:
    nct_id: str
    title: str
    phase: str | None
    status: str
    conditions: list[str]
    interventions: list[str]
    sponsor: str | None
    sponsor_names: list[str]
    start_date: date | None
    primary_completion_date: date | None
    last_update_date: date | None
    enrollment: int | None
    study_type: str | None
    matched_alias: str | None
    extra_metadata: dict[str, Any]


class ClinicalTrialsAccessBlocked(RuntimeError):
    """Raised when ClinicalTrials.gov blocks the current client/request pattern."""


class TrialProviderConfigurationError(RuntimeError):
    """Raised when a trial data provider is not configured correctly."""


class TrialProvider:
    provider_name = "unknown"
    reason: str | None = None

    def is_configured(self) -> bool:
        return True

    def fetch_company_trials(self, company: Company, max_results: int | None = None) -> list[TrialPayload]:
        raise NotImplementedError

    def close(self) -> None:
        return None


class NoopTrialProvider(TrialProvider):
    def __init__(self, provider_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.reason = reason

    def is_configured(self) -> bool:
        return False

    def fetch_company_trials(self, company: Company, max_results: int | None = None) -> list[TrialPayload]:
        return []


class ClinicalTrialsGovApiProvider(TrialProvider):
    provider_name = "ctgov_api"

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=self.settings.source_fetch_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_http_client:
            with contextlib.suppress(Exception):
                self.http_client.close()

    def fetch_company_trials(self, company: Company, max_results: int | None = None) -> list[TrialPayload]:
        payloads: dict[str, TrialPayload] = {}
        alias_records = _build_trial_aliases(company)
        alias_names = [alias.original for alias in alias_records[:3]]
        limit = min(max_results or 50, 100)

        for index, sponsor_name in enumerate(alias_names):
            if index > 0 and self.settings.sec_rate_limit_delay_seconds > 0:
                sleep(self.settings.sec_rate_limit_delay_seconds)
            studies = self._search_studies(sponsor_name, max_results=limit)
            for study in studies:
                payload = self._payload_from_study(study, matched_alias=sponsor_name)
                if payload.nct_id not in payloads:
                    payloads[payload.nct_id] = payload
        return list(payloads.values())

    def _search_studies(self, sponsor_name: str, max_results: int = 50) -> list[dict]:
        params = {
            "query.spons": sponsor_name,
            "pageSize": min(max_results, 100),
            "fields": (
                "NCTId,BriefTitle,Phase,OverallStatus,Condition,InterventionName,"
                "LeadSponsorName,StartDate,PrimaryCompletionDate,LastUpdatePostDate,"
                "EnrollmentCount,StudyType"
            ),
        }
        response = self.http_client.get(f"{CT_API_BASE}/studies", params=params)
        if response.status_code == 403:
            raise ClinicalTrialsAccessBlocked("403 Forbidden")
        response.raise_for_status()
        data = response.json()
        return data.get("studies", [])

    def _payload_from_study(self, study: dict[str, Any], *, matched_alias: str) -> TrialPayload:
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        interventions_module = protocol.get("armsInterventionsModule", {})

        nct_id = id_module.get("nctId") or ""
        title = id_module.get("briefTitle") or "Untitled"
        phases = design_module.get("phases", [])
        phase = phases[0] if phases else None
        status = status_module.get("overallStatus", "Unknown")
        conditions = conditions_module.get("conditions", []) or []
        interventions = [item.get("name", "") for item in (interventions_module.get("interventions") or []) if item.get("name")]
        sponsor = (sponsor_module.get("leadSponsor") or {}).get("name")
        start_date = _parse_date((status_module.get("startDateStruct") or {}).get("date"))
        completion_date = _parse_date((status_module.get("primaryCompletionDateStruct") or {}).get("date"))
        last_update = _parse_date((status_module.get("lastUpdatePostDateStruct") or {}).get("date"))
        enrollment = (design_module.get("enrollmentInfo") or {}).get("count")
        study_type = design_module.get("studyType")

        return TrialPayload(
            nct_id=nct_id,
            title=title,
            phase=phase,
            status=status,
            conditions=conditions,
            interventions=interventions,
            sponsor=sponsor,
            sponsor_names=[sponsor] if sponsor else [],
            start_date=start_date,
            primary_completion_date=completion_date,
            last_update_date=last_update,
            enrollment=enrollment,
            study_type=study_type,
            matched_alias=matched_alias,
            extra_metadata={
                "source_provider": self.provider_name,
                "matched_alias": matched_alias,
                "source_snapshot_date": date.today().isoformat(),
            },
        )


class AACTCloudTrialProvider(TrialProvider):
    provider_name = "aact_cloud"

    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = get_settings()
        self.connection_factory = connection_factory or self._connect
        self.reason = None
        if not self.settings.aact_db_user or not self.settings.aact_db_password:
            self.reason = "AACT credentials are missing"

    def is_configured(self) -> bool:
        return self.reason is None

    def fetch_company_trials(self, company: Company, max_results: int | None = None) -> list[TrialPayload]:
        if not self.is_configured():
            raise TrialProviderConfigurationError(self.reason or "AACT provider is not configured")

        alias_records = _build_trial_aliases(company)
        if not alias_records:
            return []

        rows = self._query_rows(alias_records)
        source_snapshot_date = date.today().isoformat()
        payloads: list[TrialPayload] = []
        for row in rows:
            sponsor_names = [value for value in (row.get("sponsor_names") or []) if value]
            if not sponsor_names and row.get("lead_sponsor"):
                sponsor_names = [row["lead_sponsor"]]
            best_match = _pick_best_trial_match(sponsor_names, alias_records)
            if best_match["score"] <= 0:
                continue
            payloads.append(
                TrialPayload(
                    nct_id=row["nct_id"],
                    title=row.get("brief_title") or "Untitled",
                    phase=row.get("phase"),
                    status=row.get("overall_status") or "Unknown",
                    conditions=list(row.get("conditions") or []),
                    interventions=list(row.get("interventions") or []),
                    sponsor=row.get("lead_sponsor"),
                    sponsor_names=sponsor_names,
                    start_date=row.get("start_date"),
                    primary_completion_date=row.get("primary_completion_date"),
                    last_update_date=row.get("last_update_date"),
                    enrollment=row.get("enrollment"),
                    study_type=row.get("study_type"),
                    matched_alias=best_match["alias"],
                    extra_metadata={
                        "source_provider": self.provider_name,
                        "matched_alias": best_match["alias"],
                        "matched_sponsor_name": best_match["sponsor_name"],
                        "match_score": best_match["score"],
                        "source_snapshot_date": source_snapshot_date,
                        "sponsor_names": sponsor_names,
                    },
                )
            )
        return payloads

    def _connect(self):
        return psycopg.connect(
            host=self.settings.aact_db_host or AACT_DEFAULT_HOST,
            port=self.settings.aact_db_port or AACT_DEFAULT_PORT,
            dbname=self.settings.aact_db_name or AACT_DEFAULT_DBNAME,
            user=self.settings.aact_db_user,
            password=self.settings.aact_db_password,
            row_factory=dict_row,
            connect_timeout=10,
        )

    def _query_rows(self, alias_records: list[TrialAlias]) -> list[dict[str, Any]]:
        raw_aliases = [alias.raw_lower for alias in alias_records]
        compact_aliases = [alias.compact for alias in alias_records]
        loose_patterns = [alias.loose_pattern for alias in alias_records if alias.loose_pattern]
        if not loose_patterns:
            loose_patterns = ["%!no_trial_match!%"]

        recent_cutoff = date.today() - timedelta(days=self.settings.clinical_trials_recent_days)
        statuses = sorted(CURRENT_OR_UPCOMING_STATUSES)
        sql = """
            SELECT
                st.nct_id,
                st.brief_title,
                st.phase,
                st.overall_status,
                st.start_date,
                st.primary_completion_date,
                st.last_update_posted_date AS last_update_date,
                st.enrollment,
                st.study_type,
                COALESCE(
                    (
                        SELECT sp.name
                        FROM sponsors sp
                        WHERE sp.nct_id = st.nct_id
                          AND lower(coalesce(sp.lead_or_collaborator, '')) = 'lead'
                        ORDER BY sp.id
                        LIMIT 1
                    ),
                    (
                        SELECT sp.name
                        FROM sponsors sp
                        WHERE sp.nct_id = st.nct_id
                        ORDER BY sp.id
                        LIMIT 1
                    )
                ) AS lead_sponsor,
                ARRAY(
                    SELECT DISTINCT sp.name
                    FROM sponsors sp
                    WHERE sp.nct_id = st.nct_id
                      AND sp.name IS NOT NULL
                    ORDER BY sp.name
                ) AS sponsor_names,
                ARRAY(
                    SELECT DISTINCT c.name
                    FROM conditions c
                    WHERE c.nct_id = st.nct_id
                      AND c.name IS NOT NULL
                    ORDER BY c.name
                ) AS conditions,
                ARRAY(
                    SELECT DISTINCT i.name
                    FROM interventions i
                    WHERE i.nct_id = st.nct_id
                      AND i.name IS NOT NULL
                    ORDER BY i.name
                ) AS interventions
            FROM studies st
            WHERE (
                lower(coalesce(st.overall_status, '')) = ANY(%s)
                OR st.last_update_posted_date >= %s
                OR st.primary_completion_date >= %s
            )
              AND EXISTS (
                SELECT 1
                FROM sponsors sp_match
                WHERE sp_match.nct_id = st.nct_id
                  AND (
                    lower(trim(coalesce(sp_match.name, ''))) = ANY(%s)
                    OR regexp_replace(lower(coalesce(sp_match.name, '')), '[^a-z0-9]+', '', 'g') = ANY(%s)
                    OR lower(coalesce(sp_match.name, '')) LIKE ANY(%s)
                  )
              )
            ORDER BY st.last_update_posted_date DESC NULLS LAST, st.nct_id
        """
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        statuses,
                        recent_cutoff,
                        recent_cutoff,
                        raw_aliases,
                        compact_aliases,
                        loose_patterns,
                    ),
                )
                return list(cursor.fetchall())


def _build_trial_aliases(company: Company) -> list[TrialAlias]:
    values: list[tuple[str, str]] = []
    trial_aliases = (company.extra_metadata or {}).get("trial_sponsor_aliases") or []
    if isinstance(trial_aliases, str):
        trial_aliases = [item.strip() for item in trial_aliases.split(",") if item.strip()]
    for value in trial_aliases:
        values.append(("trial_specific", str(value)))
    values.append(("canonical", company.name))
    for alias in company.aliases or []:
        values.append(("general", str(alias)))

    seen: set[str] = set()
    aliases: list[TrialAlias] = []
    for source, original in values:
        cleaned = original.strip()
        if not cleaned:
            continue
        normalized = _normalize_trial_name(cleaned)
        compact = normalized.replace(" ", "")
        if not compact or compact in seen:
            continue
        if source == "general" and len(compact) < 6 and len(normalized.split()) == 1:
            continue
        if source == "general" and company.ticker and cleaned.upper() == (company.ticker or "").upper():
            continue
        seen.add(compact)
        core = _core_compact_trial_name(cleaned)
        tokens = tuple(_normalize_trial_name(cleaned).split())
        loose_pattern = None
        if tokens:
            token_phrase = " ".join(tokens)
            if len(tokens) >= 2 or len(token_phrase) >= 10:
                loose_pattern = f"%{token_phrase}%"
        aliases.append(
            TrialAlias(
                original=cleaned,
                raw_lower=cleaned.strip().casefold(),
                compact=compact,
                core_compact=core,
                tokens=tokens,
                loose_pattern=loose_pattern,
            )
        )
    return aliases


def _match_score(sponsor_name: str, alias: TrialAlias) -> int:
    raw_lower = sponsor_name.strip().casefold()
    if raw_lower == alias.raw_lower:
        return 320
    compact = _compact_trial_name(sponsor_name)
    if compact and compact == alias.compact:
        return 300
    core = _core_compact_trial_name(sponsor_name)
    if core and core == alias.core_compact:
        return 240

    sponsor_tokens = tuple(_normalize_trial_name(sponsor_name).split())
    if alias.tokens and sponsor_tokens[: len(alias.tokens)] == alias.tokens:
        return 180
    if len(alias.tokens) >= 2 and all(token in sponsor_tokens for token in alias.tokens):
        return 150
    return 0


def _pick_best_trial_match(sponsor_names: list[str], aliases: list[TrialAlias]) -> dict[str, Any]:
    best = {"score": 0, "alias": None, "sponsor_name": None}
    for sponsor_name in sponsor_names:
        for alias in aliases:
            score = _match_score(sponsor_name, alias)
            if score > best["score"]:
                best = {"score": score, "alias": alias.original, "sponsor_name": sponsor_name}
    return best


class ClinicalTrialsService:
    def __init__(
        self,
        session: Session,
        http_client: httpx.Client | None = None,
        provider: TrialProvider | None = None,
        aact_connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.http_client = http_client
        self._provider_override = provider
        self._aact_connection_factory = aact_connection_factory
        self._provider: TrialProvider | None = None

    def close(self) -> None:
        provider = self._provider
        if self._provider_override is None and provider is not None:
            with contextlib.suppress(Exception):
                provider.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def poll_trials_for_company(self, company: Company, max_results: int = 50) -> dict[str, int]:
        provider = self._trial_provider()
        if not provider.is_configured():
            logger.warning("Skipping clinical trial sync for provider %s: %s", provider.provider_name, provider.reason)
            return {
                "new": 0,
                "updated": 0,
                "pruned": 0,
                "company_id": company.id,
                "success": 0,
                "provider": provider.provider_name,
            }
        try:
            payloads = provider.fetch_company_trials(company, max_results=max_results)
            result = self._sync_company_trials(company, payloads, provider_name=provider.provider_name)
            self.session.commit()
            return {
                "new": result["inserted"],
                "updated": result["updated"],
                "pruned": result["pruned"],
                "company_id": company.id,
                "success": 1,
                "provider": provider.provider_name,
            }
        except ClinicalTrialsAccessBlocked as exc:
            self.session.rollback()
            logger.warning("Clinical trial provider %s blocked %s: %s", provider.provider_name, company.name, exc)
            return {
                "new": 0,
                "updated": 0,
                "pruned": 0,
                "company_id": company.id,
                "success": 0,
                "blocked": 1,
                "provider": provider.provider_name,
            }
        except Exception as exc:  # pragma: no cover - runtime provider behavior
            self.session.rollback()
            logger.warning("Failed to sync trials for %s via %s: %s", company.name, provider.provider_name, exc)
            return {
                "new": 0,
                "updated": 0,
                "pruned": 0,
                "company_id": company.id,
                "success": 0,
                "provider": provider.provider_name,
            }

    def poll_companies(self, companies: list[Company]) -> dict[str, Any]:
        provider = self._trial_provider()
        if not provider.is_configured():
            logger.warning("Skipping clinical trial sync for provider %s: %s", provider.provider_name, provider.reason)
            return {
                "provider": provider.provider_name,
                "companies_scanned": 0,
                "companies_succeeded": 0,
                "companies_failed": 0,
                "new_trials": 0,
                "updated_trials": 0,
                "pruned_trials": 0,
                "partial": 0,
                "skipped": 1,
            }

        totals = {
            "provider": provider.provider_name,
            "companies_scanned": 0,
            "companies_succeeded": 0,
            "companies_failed": 0,
            "new_trials": 0,
            "updated_trials": 0,
            "pruned_trials": 0,
            "partial": 0,
            "skipped": 0,
        }
        for company in companies:
            totals["companies_scanned"] += 1
            result = self.poll_trials_for_company(company, max_results=1000 if provider.provider_name == "aact_cloud" else 20)
            totals["new_trials"] += int(result.get("new") or 0)
            totals["updated_trials"] += int(result.get("updated") or 0)
            totals["pruned_trials"] += int(result.get("pruned") or 0)
            if result.get("success"):
                totals["companies_succeeded"] += 1
            else:
                totals["companies_failed"] += 1
                totals["partial"] = 1
                if result.get("blocked"):
                    break
        return totals

    def poll_all_companies(
        self,
        limit: int | None = None,
        focus_tickers: list[str] | None = None,
    ) -> dict[str, Any]:
        query = select(Company).where(Company.is_active.is_(True))
        companies = self.session.scalars(query).all()
        if focus_tickers:
            focus = {ticker.upper() for ticker in focus_tickers}
            companies = [company for company in companies if (company.ticker or "").upper() in focus]
        companies.sort(key=lambda company: company.market_cap or 0, reverse=True)
        if limit:
            companies = companies[:limit]
        return self.poll_companies(companies)

    def list_trials(
        self,
        company_id: int | None = None,
        phase: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = select(ClinicalTrial)
        if company_id:
            query = query.where(ClinicalTrial.company_id == company_id)
        if phase:
            query = query.where(ClinicalTrial.phase == phase)
        if status:
            query = query.where(ClinicalTrial.status == status)
        query = query.order_by(ClinicalTrial.last_update_date.desc().nullslast()).limit(limit)
        trials = self.session.scalars(query).all()
        return [self._to_response(trial) for trial in trials]

    def list_trials_for_company_grouped(self, company_id: int) -> dict[str, list[dict]]:
        trials = self.list_trials(company_id=company_id, limit=100)
        groups: dict[str, list[dict]] = {}
        for trial in trials:
            phase = trial.get("phase") or "Unknown"
            groups.setdefault(phase, []).append(trial)
        return dict(sorted(groups.items(), key=lambda item: PHASE_ORDER.get(item[0], 99)))

    def list_trials_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        company_id: int | None = None,
        phase: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        query = select(ClinicalTrial)
        count_query = select(func.count()).select_from(ClinicalTrial)
        if company_id:
            query = query.where(ClinicalTrial.company_id == company_id)
            count_query = count_query.where(ClinicalTrial.company_id == company_id)
        if phase:
            query = query.where(ClinicalTrial.phase == phase)
            count_query = count_query.where(ClinicalTrial.phase == phase)
        if status:
            query = query.where(ClinicalTrial.status == status)
            count_query = count_query.where(ClinicalTrial.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.where(ClinicalTrial.title.ilike(pattern))
            count_query = count_query.where(ClinicalTrial.title.ilike(pattern))
        total = self.session.scalar(count_query) or 0
        query = query.order_by(ClinicalTrial.last_update_date.desc().nullslast()).offset(offset).limit(limit)
        trials = self.session.scalars(query).all()
        return {
            "items": [self._to_response(trial) for trial in trials],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def _trial_provider(self) -> TrialProvider:
        if self._provider_override is not None:
            return self._provider_override
        if self._provider is not None:
            return self._provider

        provider_name = self.settings.clinical_trials_provider
        if provider_name == "none":
            self._provider = NoopTrialProvider("none", "Clinical trial syncing is disabled")
        elif provider_name == "ctgov_api":
            self._provider = ClinicalTrialsGovApiProvider(http_client=self.http_client)
        else:
            self._provider = AACTCloudTrialProvider(connection_factory=self._aact_connection_factory)
        return self._provider

    def _sync_company_trials(self, company: Company, payloads: list[TrialPayload], *, provider_name: str) -> dict[str, int]:
        existing = {
            trial.nct_id: trial
            for trial in self.session.scalars(select(ClinicalTrial).where(ClinicalTrial.company_id == company.id)).all()
        }
        inserted = 0
        updated = 0
        seen_nct_ids: set[str] = set()

        for payload in payloads:
            seen_nct_ids.add(payload.nct_id)
            trial = existing.get(payload.nct_id)
            if trial is None:
                self.session.add(
                    ClinicalTrial(
                        nct_id=payload.nct_id,
                        company_id=company.id,
                        title=payload.title,
                        phase=payload.phase,
                        status=payload.status,
                        conditions=payload.conditions,
                        interventions=payload.interventions,
                        sponsor=payload.sponsor,
                        start_date=payload.start_date,
                        primary_completion_date=payload.primary_completion_date,
                        last_update_date=payload.last_update_date,
                        enrollment=payload.enrollment,
                        study_type=payload.study_type,
                        extra_metadata={**payload.extra_metadata, "source_provider": provider_name},
                    )
                )
                inserted += 1
                continue

            changed = False
            for field_name in (
                "title",
                "phase",
                "status",
                "conditions",
                "interventions",
                "sponsor",
                "start_date",
                "primary_completion_date",
                "last_update_date",
                "enrollment",
                "study_type",
            ):
                new_value = getattr(payload, field_name)
                if getattr(trial, field_name) != new_value:
                    setattr(trial, field_name, new_value)
                    changed = True
            merged_metadata = {**(trial.extra_metadata or {}), **payload.extra_metadata, "source_provider": provider_name}
            if trial.extra_metadata != merged_metadata:
                trial.extra_metadata = merged_metadata
                changed = True
            if changed:
                updated += 1

        prune_candidates = [
            trial
            for nct_id, trial in existing.items()
            if nct_id not in seen_nct_ids
        ]
        pruned = 0
        for trial in prune_candidates:
            self.session.delete(trial)
            pruned += 1

        return {"inserted": inserted, "updated": updated, "pruned": pruned}

    def _to_response(self, trial: ClinicalTrial) -> dict[str, Any]:
        company_name = None
        ticker = None
        if trial.company_id:
            company = self.session.get(Company, trial.company_id)
            if company:
                company_name = company.name
                ticker = company.ticker
        return {
            "id": trial.id,
            "nct_id": trial.nct_id,
            "company_id": trial.company_id,
            "company_name": company_name,
            "ticker": ticker,
            "title": trial.title,
            "phase": trial.phase,
            "status": trial.status,
            "conditions": trial.conditions or [],
            "interventions": trial.interventions or [],
            "sponsor": trial.sponsor,
            "start_date": trial.start_date,
            "primary_completion_date": trial.primary_completion_date,
            "last_update_date": trial.last_update_date,
            "enrollment": trial.enrollment,
            "study_type": trial.study_type,
        }
