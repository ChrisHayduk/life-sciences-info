from __future__ import annotations

from app.config import get_settings
from app.models import ClinicalTrial, Company
from app.services.clinical_trials import AACTCloudTrialProvider, ClinicalTrialsService, TrialProvider


class FakeTrialProvider(TrialProvider):
    provider_name = "fake_provider"

    def __init__(self, payloads_by_company=None, failing_company_ids=None, configured=True, reason="") -> None:
        self.payloads_by_company = payloads_by_company or {}
        self.failing_company_ids = set(failing_company_ids or [])
        self._configured = configured
        self.reason = reason

    def is_configured(self) -> bool:
        return self._configured

    def fetch_company_trials(self, company: Company, max_results: int | None = None):
        if company.id in self.failing_company_ids:
            raise RuntimeError("provider failure")
        return list(self.payloads_by_company.get(company.id, []))


def _trial_payload(**overrides):
    payload = {
        "nct_id": "NCT00000001",
        "title": "Apex Bio Phase 2 Trial",
        "phase": "Phase 2",
        "status": "Recruiting",
        "conditions": ["Oncology"],
        "interventions": ["AB-101"],
        "sponsor": "Apex Bio, Inc.",
        "sponsor_names": ["Apex Bio, Inc."],
        "start_date": None,
        "primary_completion_date": None,
        "last_update_date": None,
        "enrollment": 120,
        "study_type": "Interventional",
        "matched_alias": "Apex Bio",
        "extra_metadata": {"source_provider": "aact_cloud", "matched_alias": "Apex Bio"},
    }
    payload.update(overrides)
    from app.services.clinical_trials import TrialPayload

    return TrialPayload(**payload)


def test_service_skips_when_aact_provider_is_unconfigured(db_session, company, monkeypatch):
    monkeypatch.setenv("CLINICAL_TRIALS_PROVIDER", "aact_cloud")
    monkeypatch.setenv("AACT_DB_USER", "")
    monkeypatch.setenv("AACT_DB_PASSWORD", "")
    get_settings.cache_clear()

    service = ClinicalTrialsService(db_session)
    result = service.poll_all_companies(limit=10)

    assert result["provider"] == "aact_cloud"
    assert result["skipped"] == 1
    assert result["companies_scanned"] == 0


def test_aact_provider_maps_rows_and_prefers_sponsor_aliases(db_session, monkeypatch):
    monkeypatch.setenv("AACT_DB_USER", "demo-user")
    monkeypatch.setenv("AACT_DB_PASSWORD", "demo-pass")
    get_settings.cache_clear()
    company = Company(
        cik="0000002000",
        ticker="ABIO",
        name="Apex Bio, Inc.",
        aliases=["Apex Bio"],
        extra_metadata={"trial_sponsor_aliases": ["Apex Biotherapeutics"]},
        is_active=True,
    )
    db_session.add(company)
    db_session.commit()

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __init__(self, rows):
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor(self.rows)

    provider = AACTCloudTrialProvider(connection_factory=lambda: FakeConnection([
        {
            "nct_id": "NCT00000077",
            "brief_title": "Apex Biotherapeutics Study",
            "phase": "Phase 3",
            "overall_status": "Recruiting",
            "start_date": None,
            "primary_completion_date": None,
            "last_update_date": None,
            "enrollment": 200,
            "study_type": "Interventional",
            "lead_sponsor": "Apex Biotherapeutics",
            "sponsor_names": ["Apex Biotherapeutics", "Collaborator Labs"],
            "conditions": ["Rare disease"],
            "interventions": ["AB-301"],
        }
    ]))

    payloads = provider.fetch_company_trials(company)

    assert len(payloads) == 1
    assert payloads[0].nct_id == "NCT00000077"
    assert payloads[0].matched_alias == "Apex Biotherapeutics"
    assert payloads[0].extra_metadata["source_provider"] == "aact_cloud"
    assert payloads[0].conditions == ["Rare disease"]


def test_aact_provider_rejects_false_positive_sponsor_matches(db_session, monkeypatch):
    monkeypatch.setenv("AACT_DB_USER", "demo-user")
    monkeypatch.setenv("AACT_DB_PASSWORD", "demo-pass")
    get_settings.cache_clear()
    company = Company(cik="0000002001", ticker="BEAM", name="Beam Therapeutics, Inc.", aliases=["Beam"], is_active=True)
    db_session.add(company)
    db_session.commit()

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            return [
                {
                    "nct_id": "NCT00000123",
                    "brief_title": "Sunbeam Research Study",
                    "phase": "Phase 1",
                    "overall_status": "Recruiting",
                    "start_date": None,
                    "primary_completion_date": None,
                    "last_update_date": None,
                    "enrollment": 50,
                    "study_type": "Interventional",
                    "lead_sponsor": "Sunbeam Research LLC",
                    "sponsor_names": ["Sunbeam Research LLC"],
                    "conditions": ["Dermatology"],
                    "interventions": ["SB-001"],
                }
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    provider = AACTCloudTrialProvider(connection_factory=lambda: FakeConnection())

    payloads = provider.fetch_company_trials(company)

    assert payloads == []


def test_poll_companies_upserts_and_prunes_trials_per_company(db_session, company):
    existing = ClinicalTrial(
        nct_id="NCT00000001",
        company_id=company.id,
        title="Old trial",
        phase="Phase 1",
        status="Recruiting",
        conditions=["Legacy"],
        interventions=["OLD"],
        sponsor=company.name,
        study_type="Interventional",
        extra_metadata={"source_provider": "legacy"},
    )
    stale = ClinicalTrial(
        nct_id="NCT00000099",
        company_id=company.id,
        title="Stale trial",
        phase="Phase 1",
        status="Completed",
        conditions=[],
        interventions=[],
        sponsor=company.name,
        study_type="Interventional",
        extra_metadata={"source_provider": "legacy"},
    )
    db_session.add_all([existing, stale])
    db_session.commit()

    provider = FakeTrialProvider({
        company.id: [
            _trial_payload(title="Updated trial title", nct_id="NCT00000001"),
            _trial_payload(nct_id="NCT00000002", title="New trial", interventions=["NEW"]),
        ]
    })
    service = ClinicalTrialsService(db_session, provider=provider)

    result = service.poll_companies([company])

    assert result["companies_succeeded"] == 1
    assert result["new_trials"] == 1
    assert result["updated_trials"] == 1
    assert result["pruned_trials"] == 1
    trials = db_session.query(ClinicalTrial).filter(ClinicalTrial.company_id == company.id).order_by(ClinicalTrial.nct_id).all()
    assert [trial.nct_id for trial in trials] == ["NCT00000001", "NCT00000002"]
    assert trials[0].title == "Updated trial title"


def test_failed_company_sync_leaves_existing_trials_untouched(db_session):
    first = Company(cik="0000003000", ticker="ABIO", name="Apex Bio", is_active=True)
    second = Company(cik="0000003001", ticker="BMED", name="Beta Med", is_active=True)
    db_session.add_all([first, second])
    db_session.commit()
    old_trial = ClinicalTrial(
        nct_id="NCT00000999",
        company_id=second.id,
        title="Existing beta trial",
        phase="Phase 2",
        status="Recruiting",
        conditions=[],
        interventions=[],
        sponsor="Beta Med",
        study_type="Interventional",
        extra_metadata={"source_provider": "legacy"},
    )
    db_session.add(old_trial)
    db_session.commit()

    provider = FakeTrialProvider(
        payloads_by_company={first.id: [_trial_payload(nct_id="NCT00001000", title="Fresh Apex Trial")]},
        failing_company_ids={second.id},
    )
    service = ClinicalTrialsService(db_session, provider=provider)

    result = service.poll_companies([first, second])

    assert result["companies_succeeded"] == 1
    assert result["companies_failed"] == 1
    assert result["partial"] == 1
    preserved = db_session.query(ClinicalTrial).filter(ClinicalTrial.company_id == second.id).one()
    assert preserved.nct_id == "NCT00000999"


def test_ctgov_provider_can_still_be_selected(db_session, monkeypatch):
    monkeypatch.setenv("CLINICAL_TRIALS_PROVIDER", "ctgov_api")
    get_settings.cache_clear()

    service = ClinicalTrialsService(db_session)

    assert service._trial_provider().provider_name == "ctgov_api"
    service._trial_provider().http_client.close()
