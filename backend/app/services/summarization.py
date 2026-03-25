from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import SummaryPayload

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "key_takeaways": {"type": "array", "items": {"type": "string"}},
        "material_changes": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "opportunity_flags": {"type": "array", "items": {"type": "string"}},
        "company_mentions": {"type": "array", "items": {"type": "string"}},
        "evidence_sections": {"type": "array", "items": {"type": "string"}},
        "importance_score": {"type": "number"},
        "market_cap_score": {"type": "number"},
        "composite_score": {"type": "number"},
        "score_explanation": {"type": "string"},
    },
    "required": [
        "summary",
        "key_takeaways",
        "material_changes",
        "risk_flags",
        "opportunity_flags",
        "company_mentions",
        "evidence_sections",
        "importance_score",
        "market_cap_score",
        "composite_score",
        "score_explanation",
    ],
}

SYSTEM_PROMPT = """
You analyze public life sciences company disclosures and industry news.
Return concise JSON matching the supplied schema.
Importance scores must be between 0 and 100.
Focus on what changed, why it matters, and what a healthcare/life sciences investor or operator should know.
""".strip()


class OpenAISummarizer:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.http_client = http_client or httpx.Client(timeout=60.0)

    def summarize(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        company_name: str | None = None,
        evidence_sections: list[str] | None = None,
        max_attempts: int = 2,
    ) -> SummaryPayload:
        if not self.settings.openai_api_key:
            return self._fallback_summary(kind=kind, title=title, text=text, company_name=company_name, evidence_sections=evidence_sections)

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                payload = self._call_openai(kind=kind, title=title, text=text, company_name=company_name, evidence_sections=evidence_sections)
                return SummaryPayload.model_validate(payload)
            except (ValidationError, ValueError, httpx.HTTPError) as exc:
                last_error = exc
        raise RuntimeError(f"Unable to summarize after {max_attempts} attempts") from last_error

    def _call_openai(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        company_name: str | None,
        evidence_sections: list[str] | None,
    ) -> dict[str, Any]:
        prompt = (
            f"Kind: {kind}\n"
            f"Title: {title}\n"
            f"Company: {company_name or 'N/A'}\n"
            f"Evidence Sections: {', '.join(evidence_sections or []) or 'N/A'}\n\n"
            f"Source text:\n{text[:20000]}"
        )
        response = self.http_client.post(
            f"{self.settings.openai_api_base}/responses",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.openai_model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "life_sciences_summary",
                        "schema": SUMMARY_SCHEMA,
                        "strict": True,
                    }
                },
            },
        )
        response.raise_for_status()
        body = response.json()
        extracted = self._extract_json_payload(body)
        return json.loads(extracted) if isinstance(extracted, str) else extracted

    def _extract_json_payload(self, body: dict[str, Any]) -> str | dict[str, Any]:
        if body.get("output_text"):
            return body["output_text"]
        for output in body.get("output", []):
            for content in output.get("content", []):
                if "json" in content:
                    return content["json"]
                text = content.get("text")
                if text:
                    return text
        raise ValueError("Response did not contain structured output")

    def _fallback_summary(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        company_name: str | None,
        evidence_sections: list[str] | None,
    ) -> SummaryPayload:
        clean_text = re.sub(r"\s+", " ", text).strip()
        sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", clean_text) if segment.strip()]
        summary = " ".join(sentences[:2])[:700] if sentences else title
        lower = clean_text.lower()
        keyword_map = {
            "risk_flags": ["risk", "warning", "litigation", "regulatory", "shortage", "delay"],
            "opportunity_flags": ["approval", "expansion", "growth", "launch", "positive", "partnership"],
            "material_changes": ["acquisition", "guidance", "trial", "restructuring", "financing", "manufacturing"],
        }

        def collect_items(words: list[str], label: str) -> list[str]:
            hits = [word for word in words if word in lower]
            return [f"{label}: {word}" for word in hits[:3]]

        importance = min(100.0, 30.0 + 10.0 * sum(keyword in lower for keyword in ["approval", "guidance", "restructuring", "trial", "earnings", "revenue"]))
        return SummaryPayload(
            summary=summary or title,
            key_takeaways=sentences[:3] or [title],
            material_changes=collect_items(keyword_map["material_changes"], "Detected"),
            risk_flags=collect_items(keyword_map["risk_flags"], "Risk"),
            opportunity_flags=collect_items(keyword_map["opportunity_flags"], "Opportunity"),
            company_mentions=[company_name] if company_name else [],
            evidence_sections=evidence_sections or [],
            importance_score=importance,
            market_cap_score=0.0,
            composite_score=importance,
            score_explanation=f"Fallback summary used for {kind}; OpenAI credentials unavailable.",
        )

