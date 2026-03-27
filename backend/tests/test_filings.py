from __future__ import annotations

from app.models import Filing
from app.schemas import SummaryPayload
from app.services.filings import FilingService, html_to_text, is_periodic_6k, normalize_form_type, parse_sections
from app.services.sec import FilingDocument
from app.services.storage import ObjectStore


class StubSummarizer:
    def summarize(self, **kwargs):
        return SummaryPayload(
            summary=f"Summary for {kwargs['title']}",
            key_takeaways=["Takeaway 1", "Takeaway 2"],
            material_changes=["Guidance updated"],
            risk_flags=["Risk: delay"],
            opportunity_flags=["Opportunity: launch"],
            company_mentions=[kwargs.get("company_name")] if kwargs.get("company_name") else [],
            evidence_sections=kwargs.get("evidence_sections") or [],
            importance_score=78.0,
            market_cap_score=0.0,
            composite_score=78.0,
            score_explanation="Stub summary",
        )


class StubMarketData:
    def fetch_market_cap(self, ticker):
        return {"market_cap": 3_000_000_000, "source": "test", "as_of": None}


class FakeSECClient:
    def __init__(self):
        self.downloads = {}

    def iter_company_filings(self, cik: str):
        return [
            {
                "accessionNumber": "0001-24-000001",
                "form": "10-K",
                "filingDate": "2024-01-31",
                "reportDate": "2023-12-31",
                "primaryDocument": "annual.htm",
                "primaryDocDescription": "Annual report",
            },
            {
                "accessionNumber": "0001-24-000002",
                "form": "20-F",
                "filingDate": "2024-02-28",
                "reportDate": "2023-12-31",
                "primaryDocument": "foreign.htm",
                "primaryDocDescription": "Foreign annual report",
            },
            {
                "accessionNumber": "0001-24-000003",
                "form": "6-K",
                "filingDate": "2024-03-15",
                "reportDate": "2024-03-01",
                "primaryDocument": "interim.htm",
                "primaryDocDescription": "Interim results",
                "items": "Quarterly results",
            },
            {
                "accessionNumber": "0001-24-000004",
                "form": "8-K",
                "filingDate": "2024-03-20",
                "reportDate": "2024-03-20",
                "primaryDocument": "event.htm",
                "primaryDocDescription": "Current report",
            },
        ]

    def build_filing_urls(self, cik: str, accession_number: str, primary_document: str | None):
        return {
            "filing_url": f"https://example.com/{accession_number}/index.htm",
            "original_document_url": f"https://example.com/{accession_number}/{primary_document}",
        }

    def download_primary_document(self, cik: str, accession_number: str, primary_document: str | None):
        html = f"""
        <html><body>
        <div style="display:none">mrk:NoiseMember 2024-12-31 0000310158 us-gaap:PendingLitigationMember</div>
        <div>Item 1.</div>
        <div>Business</div>
        <div>1</div>
        <div>Item 1A.</div>
        <div>Risk Factors</div>
        <div>26</div>
        <div>Item 7.</div>
        <div>Management's Discussion and Analysis of Financial Condition and Results of Operations</div>
        <div>46</div>
        <h1>Item 1.</h1>
        <h2>Business</h2>
        <p>Revenue increased 22% to $120 million.</p>
        <h1>Item 1A.</h1>
        <h2>Risk Factors</h2>
        <p>Manufacturing delay and FDA review noted.</p>
        <h1>Item 7.</h1>
        <h2>Management's Discussion and Analysis of Financial Condition and Results of Operations</h2>
        <h3>Analysis of Liquidity and Capital Resources</h3>
        <p>Guidance increased after strong quarterly results.</p>
        <h1>Item 8.</h1>
        <h2>Financial Statements and Supplementary Data</h2>
        <p>Consolidated statements follow.</p>
        </body></html>
        """
        return FilingDocument(content=html.encode("utf-8"), content_type="text/html", source_url="https://example.com")


class FakeSECClientWithOlderFiling(FakeSECClient):
    def iter_company_filings(self, cik: str):
        return super().iter_company_filings(cik) + [
            {
                "accessionNumber": "0001-20-000001",
                "form": "10-K",
                "filingDate": "2020-02-01",
                "reportDate": "2019-12-31",
                "primaryDocument": "older.htm",
                "primaryDocDescription": "Older annual report",
            }
        ]


def test_form_normalization_and_6k_equivalence():
    assert normalize_form_type("10-Q/A") == "10-Q"
    assert is_periodic_6k("Interim results", "Quarterly results and six months ended 2024") is True
    assert is_periodic_6k("Other announcement", "Executive appointment") is False


def test_html_to_text_strips_xbrl_noise_and_parse_sections_prefers_body_over_toc():
    html = """
    <html>
      <body>
        <div style="display:none">mrk:NoiseMember 2024-12-31 0000310158 us-gaap:PendingLitigationMember</div>
        <div>Item 1.</div>
        <div>Business</div>
        <div>1</div>
        <div>Item 1A.</div>
        <div>Risk Factors</div>
        <div>26</div>
        <div>Item 7.</div>
        <div>Management's Discussion and Analysis of Financial Condition and Results of Operations</div>
        <div>46</div>
        <h1>Item 1.</h1>
        <h2>Business</h2>
        <p>The company develops oncology and vaccine products.</p>
        <h1>Item 1A.</h1>
        <h2>Risk Factors</h2>
        <p>Loss of exclusivity may reduce revenue.</p>
        <h1>Item 3.</h1>
        <h2>Legal Proceedings</h2>
        <p>Patent litigation remains pending.</p>
        <h1>Item 7.</h1>
        <h2>Management's Discussion and Analysis of Financial Condition and Results of Operations</h2>
        <h3>Analysis of Liquidity and Capital Resources</h3>
        <p>Operating cash flow improved meaningfully in 2024.</p>
        <h1>Item 8.</h1>
        <h2>Financial Statements and Supplementary Data</h2>
        <p>Consolidated statements follow.</p>
      </body>
    </html>
    """

    text = html_to_text(html.encode("utf-8"), "text/html")
    sections = parse_sections(text, form_type="10-K")

    assert "mrk:NoiseMember" not in text
    assert "us-gaap:PendingLitigationMember" not in text
    assert sections["business"].startswith("The company develops oncology and vaccine products.")
    assert "Item 1A." not in sections["business"]
    assert sections["risk_factors"].startswith("Loss of exclusivity may reduce revenue.")
    assert sections["legal_proceedings"].startswith("Patent litigation remains pending.")
    assert sections["liquidity"].startswith("Operating cash flow improved meaningfully in 2024.")
    assert sections["financial_statements"].startswith("Consolidated statements follow.")


def test_html_to_text_handles_nested_hidden_tags_without_crashing():
    html = """
    <html>
      <body>
        <div style="display:none">
          <span>mrk:NoiseMember</span>
          <span>us-gaap:PendingLitigationMember</span>
        </div>
        <h1>Item 1.</h1>
        <h2>Business</h2>
        <p>Visible operating text.</p>
      </body>
    </html>
    """

    text = html_to_text(html.encode("utf-8"), "text/html")

    assert "Visible operating text." in text
    assert "mrk:NoiseMember" not in text
    assert "us-gaap:PendingLitigationMember" not in text


def test_backfill_loads_target_forms_and_dedupes_on_rerun(db_session, company, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    from app.config import get_settings

    get_settings.cache_clear()
    service = FilingService(
        db_session,
        sec_client=FakeSECClient(),
        summarizer=StubSummarizer(),
        market_data_client=StubMarketData(),
        object_store=ObjectStore(),
    )

    created_first = service.backfill_company(company.id)
    created_second = service.backfill_company(company.id)

    filings = db_session.query(Filing).order_by(Filing.filed_at).all()
    assert created_first == 3
    assert created_second == 0
    assert [filing.normalized_form_type for filing in filings] == ["10-K", "20-F", "6-K"]
    assert all(filing.original_document_url for filing in filings)
    assert all(filing.pdf_artifact_key for filing in filings)
    pdf_bytes = ObjectStore().get_bytes(filings[0].pdf_artifact_key)
    assert pdf_bytes.startswith(b"%PDF")
    assert b"Risk Factors" in pdf_bytes
    assert b"mrk:NoiseMember" not in pdf_bytes


def test_backfill_prefers_browser_rendered_html_pdf_when_available(db_session, company, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.filings.render_html_to_pdf",
        lambda html_bytes, source_url=None, timeout_seconds=45.0: b"%PDF-browser-rendered",
    )
    service = FilingService(
        db_session,
        sec_client=FakeSECClient(),
        summarizer=StubSummarizer(),
        market_data_client=StubMarketData(),
        object_store=ObjectStore(),
    )

    created = service.backfill_company(company.id)
    filing = db_session.query(Filing).filter(Filing.normalized_form_type == "10-K").one()
    pdf_bytes = ObjectStore().get_bytes(filing.pdf_artifact_key)

    assert created == 3
    assert pdf_bytes == b"%PDF-browser-rendered"
    assert filing.extra_metadata["pdf_source"] == "rendered-html"


def test_backfill_company_can_limit_by_years_back(db_session, company, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    from app.config import get_settings

    get_settings.cache_clear()
    service = FilingService(
        db_session,
        sec_client=FakeSECClientWithOlderFiling(),
        summarizer=StubSummarizer(),
        market_data_client=StubMarketData(),
        object_store=ObjectStore(),
    )

    created = service.backfill_company(company.id, years_back=3)
    filings = db_session.query(Filing).all()

    assert created == 3
    assert all(filing.filed_at.year >= 2023 for filing in filings)
