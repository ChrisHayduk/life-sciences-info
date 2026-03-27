"""ClinicalTrials.gov v2 API integration for clinical trial pipeline data."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClinicalTrial, Company

logger = logging.getLogger(__name__)

CT_API_BASE = "https://clinicaltrials.gov/api/v2"

# Phase ordering for display priority
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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


class ClinicalTrialsService:
    def __init__(self, session: Session, http_client: httpx.Client | None = None) -> None:
        self.session = session
        self.http_client = http_client or httpx.Client(timeout=30.0)

    def poll_trials_for_company(self, company: Company, max_results: int = 50) -> dict[str, int]:
        """Fetch trials from ClinicalTrials.gov where the company is a sponsor."""
        sponsor_names = [company.name]
        # Also search by aliases if available
        for alias in company.aliases or []:
            if alias and len(alias) > 3:
                sponsor_names.append(alias)

        new_count = 0
        updated_count = 0

        for sponsor_name in sponsor_names[:3]:  # Limit to avoid too many API calls
            try:
                studies = self._search_studies(sponsor_name, max_results=max_results)
            except Exception as exc:
                logger.warning("Failed to fetch trials for %s: %s", sponsor_name, exc)
                continue

            for study in studies:
                result = self._upsert_trial(study, company.id)
                if result == "new":
                    new_count += 1
                elif result == "updated":
                    updated_count += 1

        self.session.commit()
        return {"new": new_count, "updated": updated_count, "company_id": company.id}

    def poll_all_companies(self, limit: int | None = None) -> dict[str, int]:
        """Poll ClinicalTrials.gov for all active companies."""
        query = select(Company).where(Company.is_active.is_(True))
        companies = self.session.scalars(query).all()
        if limit:
            companies = companies[:limit]

        total_new = 0
        total_updated = 0
        for company in companies:
            result = self.poll_trials_for_company(company, max_results=20)
            total_new += result["new"]
            total_updated += result["updated"]

        return {"companies_polled": len(companies), "new_trials": total_new, "updated_trials": total_updated}

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
        """Return trials grouped by phase, sorted by phase priority."""
        trials = self.list_trials(company_id=company_id, limit=100)
        groups: dict[str, list[dict]] = {}
        for trial in trials:
            phase = trial.get("phase") or "Unknown"
            groups.setdefault(phase, []).append(trial)
        # Sort groups by phase priority
        sorted_groups = dict(sorted(groups.items(), key=lambda x: PHASE_ORDER.get(x[0], 99)))
        return sorted_groups

    def _search_studies(self, sponsor_name: str, max_results: int = 50) -> list[dict]:
        """Query the ClinicalTrials.gov v2 API."""
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
        response.raise_for_status()
        data = response.json()
        return data.get("studies", [])

    def _upsert_trial(self, study: dict, company_id: int) -> str:
        """Insert or update a clinical trial record. Returns 'new', 'updated', or 'unchanged'."""
        # Navigate the nested v2 API structure
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        interventions_module = protocol.get("armsInterventionsModule", {})

        nct_id = id_module.get("nctId")
        if not nct_id:
            return "unchanged"

        title = id_module.get("briefTitle", "Untitled")
        phases = design_module.get("phases", [])
        phase = phases[0] if phases else None
        status = status_module.get("overallStatus", "Unknown")
        conditions = conditions_module.get("conditions", [])
        interventions = [
            i.get("name", "") for i in (interventions_module.get("interventions") or [])
        ]
        sponsor = (sponsor_module.get("leadSponsor") or {}).get("name")
        start_date = _parse_date((status_module.get("startDateStruct") or {}).get("date"))
        completion_date = _parse_date(
            (status_module.get("primaryCompletionDateStruct") or {}).get("date")
        )
        last_update = _parse_date(
            (status_module.get("lastUpdatePostDateStruct") or {}).get("date")
        )
        enrollment = (design_module.get("enrollmentInfo") or {}).get("count")
        study_type = design_module.get("studyType")

        existing = self.session.scalar(
            select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id)
        )

        if existing:
            changed = False
            if existing.status != status:
                existing.status = status
                changed = True
            if existing.phase != phase:
                existing.phase = phase
                changed = True
            if existing.last_update_date != last_update:
                existing.last_update_date = last_update
                changed = True
            if existing.enrollment != enrollment:
                existing.enrollment = enrollment
                changed = True
            # Update company association if not set
            if not existing.company_id and company_id:
                existing.company_id = company_id
                changed = True
            return "updated" if changed else "unchanged"

        trial = ClinicalTrial(
            nct_id=nct_id,
            company_id=company_id,
            title=title,
            phase=phase,
            status=status,
            conditions=conditions,
            interventions=interventions,
            sponsor=sponsor,
            start_date=start_date,
            primary_completion_date=completion_date,
            last_update_date=last_update,
            enrollment=enrollment,
            study_type=study_type,
        )
        self.session.add(trial)
        return "new"

    @staticmethod
    def _to_response(trial: ClinicalTrial) -> dict[str, Any]:
        return {
            "id": trial.id,
            "nct_id": trial.nct_id,
            "company_id": trial.company_id,
            "title": trial.title,
            "phase": trial.phase,
            "status": trial.status,
            "conditions": trial.conditions or [],
            "interventions": trial.interventions or [],
            "sponsor": trial.sponsor,
            "start_date": trial.start_date.isoformat() if trial.start_date else None,
            "primary_completion_date": trial.primary_completion_date.isoformat() if trial.primary_completion_date else None,
            "last_update_date": trial.last_update_date.isoformat() if trial.last_update_date else None,
            "enrollment": trial.enrollment,
            "study_type": trial.study_type,
        }
