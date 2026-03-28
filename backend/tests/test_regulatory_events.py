from __future__ import annotations

import httpx

from app.models import RegulatoryEvent
from app.services.regulatory_events import FDA_ADVISORY_CALENDAR_JSON_URL, RegulatoryEventService


def test_regulatory_event_poll_ingests_fda_calendar_and_tags_companies(db_session, company):
    detail_url = "https://www.fda.gov/advisory-committees/advisory-committee-calendar/april-30-2026-apex-bio"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FDA_ADVISORY_CALENDAR_JSON_URL:
            return httpx.Response(
                200,
                json=[
                    {
                        "field_start_date": "04/30/2026 08:00 AM EDT",
                        "field_end_date": "04/30/2026 05:00 PM EDT",
                        "title": '<a href="/advisory-committees/advisory-committee-calendar/april-30-2026-apex-bio">April 30, 2026: Meeting of the Oncologic Drugs Advisory Committee Meeting Announcement - 04/30/2026</a>',
                        "field_contributing_office": "",
                        "field_center": "Center for Drug Evaluation and Research",
                    }
                ],
            )
        if str(request.url) == detail_url:
            return httpx.Response(
                200,
                text="""
                <html>
                  <main>
                    <h1>April 30, 2026: Meeting of the Oncologic Drugs Advisory Committee</h1>
                    <p>The committee will discuss Apex Bio's oncology application.</p>
                    <p>FDA staff briefing documents will be posted in advance of the meeting.</p>
                  </main>
                </html>
                """,
            )
        return httpx.Response(404)

    service = RegulatoryEventService(db_session, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = service.poll_fda_advisory_calendar()

    event = db_session.query(RegulatoryEvent).one()
    assert result["scanned"] == 1
    assert result["inserted"] == 1
    assert result["tagged"] == 1
    assert event.company_tag_ids == [company.id]
    assert event.source_type == "regulator"
    assert event.event_type == "fda-advisory-committee"
    assert event.composite_score > 0
    assert "Apex Bio" in event.mentioned_companies
    assert event.starts_at.year == 2026
    assert event.starts_at.month == 4
    assert event.starts_at.day == 30
