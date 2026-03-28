from __future__ import annotations

import httpx

from app.models import Company
from app.services.clinical_trials import ClinicalTrialsAccessBlocked, ClinicalTrialsService


def test_clinical_trials_service_sets_contact_user_agent(db_session, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "LifeSciencesIntel/1.0 (contact: test@example.com)")
    monkeypatch.setenv("SOURCE_FETCH_TIMEOUT_SECONDS", "12")
    from app.config import get_settings

    get_settings.cache_clear()
    service = ClinicalTrialsService(db_session)
    try:
        assert service.http_client.headers["User-Agent"] == "LifeSciencesIntel/1.0 (contact: test@example.com)"
        assert service.http_client.headers["Accept"] == "application/json"
        assert service.http_client.timeout.connect == 12
    finally:
        service.http_client.close()


def test_poll_all_companies_aborts_after_provider_block(db_session, monkeypatch):
    first = Company(cik="0000001000", ticker="ABIO", name="Apex Bio", is_active=True)
    second = Company(cik="0000001001", ticker="BMED", name="Beta Med", is_active=True)
    db_session.add_all([first, second])
    db_session.commit()

    service = ClinicalTrialsService(db_session, http_client=httpx.Client())
    seen: list[str] = []

    def fake_search(sponsor_name: str, max_results: int = 50):
        seen.append(sponsor_name)
        raise ClinicalTrialsAccessBlocked("403 Forbidden")

    monkeypatch.setattr(service, "_search_studies", fake_search)

    result = service.poll_all_companies()

    assert result["companies_polled"] == 1
    assert result["blocked"] == 1
    assert result["new_trials"] == 0
    assert result["updated_trials"] == 0
    assert seen == ["Apex Bio"]
    service.http_client.close()
