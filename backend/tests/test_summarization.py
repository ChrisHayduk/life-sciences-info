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


def test_openai_summary_with_usage_uses_requested_model_and_cache_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.test/v1")
    get_settings.cache_clear()

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        payload = {
            "model": "gpt-5.4-mini",
            "output_text": json.dumps(
                {
                    "summary": "Compact summary.",
                    "key_takeaways": ["Revenue up"],
                    "material_changes": ["Guidance raised"],
                    "risk_flags": [],
                    "opportunity_flags": ["Launch momentum"],
                    "company_mentions": ["Apex Bio"],
                    "evidence_sections": ["md&a"],
                    "entities": [],
                    "importance_score": 72,
                    "market_cap_score": 0,
                    "composite_score": 72,
                    "score_explanation": "High signal",
                }
            ),
            "usage": {
                "input_tokens": 1000,
                "input_tokens_details": {"cached_tokens": 200},
                "output_tokens": 300,
                "output_tokens_details": {"reasoning_tokens": 40},
                "total_tokens": 1300,
            },
        }
        return httpx.Response(200, json=payload)

    summarizer = OpenAISummarizer(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = summarizer.summarize_with_usage(
        kind="news",
        title="Apex Bio raises guidance",
        text="Apex Bio raised guidance.",
        company_name="Apex Bio",
        model="gpt-5.4-mini",
        prompt_cache_key="summary:news:short_ai:earnings:test:gpt-5.4-mini",
    )

    assert captured["body"]["model"] == "gpt-5.4-mini"
    assert captured["body"]["prompt_cache_key"] == "summary:news:short_ai:earnings:test:gpt-5.4-mini"
    assert result.usage.model == "gpt-5.4-mini"
    assert result.usage.prompt_tokens == 1000
    assert result.usage.cached_input_tokens == 200
    assert result.usage.completion_tokens == 300
    assert result.usage.reasoning_tokens == 40
    assert result.usage.estimated_cost_usd > 0
