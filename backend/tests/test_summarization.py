from __future__ import annotations

import json

import httpx

from app.config import get_settings
from app.services.summarization import OpenAISummarizer


def test_openai_summary_retries_on_invalid_payload(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.test/v1")
    get_settings.cache_clear()

    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        if call_count["value"] == 1:
            payload = {"output_text": "{bad json"}
        else:
            payload = {
                "output_text": json.dumps(
                    {
                        "summary": "Strong quarter with improved guidance.",
                        "key_takeaways": ["Revenue up", "Guidance raised"],
                        "material_changes": ["Guidance increase"],
                        "risk_flags": ["FDA timing remains open"],
                        "opportunity_flags": ["Launch momentum"],
                        "company_mentions": ["Apex Bio"],
                        "evidence_sections": ["md&a", "risk_factors"],
                        "importance_score": 88,
                        "market_cap_score": 0,
                        "composite_score": 88,
                        "score_explanation": "High materiality"
                    }
                )
            }
        return httpx.Response(200, json=payload)

    summarizer = OpenAISummarizer(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    summary = summarizer.summarize(kind="filing", title="Apex Bio 10-Q", text="Revenue increased.", company_name="Apex Bio")

    assert call_count["value"] == 2
    assert summary.summary.startswith("Strong quarter")
    assert summary.importance_score == 88
