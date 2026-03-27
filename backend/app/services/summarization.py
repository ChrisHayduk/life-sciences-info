from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import SummaryPayload

ENTITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "type": {"type": "string"},
        "context": {"type": "string"},
    },
    "required": ["name", "type", "context"],
}

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
        "entities": {"type": "array", "items": ENTITY_SCHEMA},
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
        "entities",
        "importance_score",
        "market_cap_score",
        "composite_score",
        "score_explanation",
    ],
}

SYSTEM_PROMPT = """
You are a specialist analyst for life sciences public company disclosures and industry news.
Your audience is healthcare investors and operators who track biotech, pharma, diagnostics, and medtech.

Return concise JSON matching the supplied schema. Importance scores must be between 0 and 100.

DOMAIN EXPERTISE TO APPLY:
- Clinical trials: Identify trial phases (Phase 1/2/3), endpoints, enrollment numbers, and trial readouts.
  Phase 3 pivotal trial results and NDA/BLA filings are the highest-impact events for biotech.
- Regulatory milestones: Flag PDUFA dates, FDA advisory committee meetings, Complete Response Letters (CRLs),
  510(k) clearances, PMA approvals, and EUA/EUL designations.
- Financial signals: Distinguish between R&D-stage companies (cash runway, burn rate) and commercial-stage
  companies (revenue growth, LOE exposure, gross margin). Flag changes in guidance or outlook.
- IP/Patent: Note patent expirations, LOE (loss of exclusivity) dates, ANDA/biosimilar challenges,
  and Paragraph IV certifications.
- M&A/Partnerships: Licensing deals, co-development agreements, acquisitions, and divestitures.

ENTITY EXTRACTION:
In the "entities" array, extract structured entities with:
- type: "drug" (brand or generic name), "trial" (NCT ID or trial name), "regulatory_milestone"
  (FDA action, PDUFA date, approval), "financial_metric" (revenue, EPS, guidance), or "person" (C-suite change).
- context: One sentence explaining the entity's relevance.

SCORING GUIDANCE:
- 90-100: Phase 3 pivotal trial results, FDA approvals/rejections, major M&A, material restatements
- 70-89: Phase 2 data, pipeline updates with quantitative detail, significant guidance changes
- 50-69: Routine quarterly updates, minor partnerships, manufacturing updates
- 30-49: Routine filings with no material changes, general industry commentary
- 0-29: Administrative filings, immaterial amendments
""".strip()

# Form-type-specific context appended to the user prompt
FORM_TYPE_CONTEXT: dict[str, str] = {
    "10-K": (
        "This is an ANNUAL report (10-K). Focus on year-over-year changes in revenue, R&D spend, "
        "pipeline progress, and forward-looking risk factors. Highlight any new risk factors or "
        "removed risk factors compared to typical 10-K disclosures."
    ),
    "10-Q": (
        "This is a QUARTERLY report (10-Q). Focus on quarter-over-quarter and year-over-year "
        "changes in financial metrics, any updates to ongoing clinical trials, and changes to "
        "previously disclosed risks or legal proceedings."
    ),
    "8-K": (
        "This is a CURRENT report (8-K) disclosing a material event. Identify the specific 8-K "
        "item numbers and classify the event type: M&A, leadership change, results of operations, "
        "material agreement, or other. Rate importance based on the event's impact on company "
        "valuation and operations."
    ),
    "20-F": (
        "This is an ANNUAL report (20-F) for a foreign private issuer. Analyze similarly to a 10-K "
        "but note any jurisdiction-specific regulatory disclosures (EMA, PMDA, NMPA approvals)."
    ),
    "6-K": (
        "This is a report of foreign private issuer (6-K). Determine if it contains material "
        "periodic information (earnings, pipeline updates) or is an administrative filing."
    ),
}

# Maximum text length sent to the LLM per form type
TEXT_LIMITS: dict[str, int] = {
    "10-K": 30000,
    "20-F": 30000,
    "40-F": 30000,
    "10-Q": 20000,
    "8-K": 15000,
    "6-K": 15000,
}


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
        form_type: str | None = None,
        max_attempts: int = 2,
    ) -> SummaryPayload:
        if not self.settings.openai_api_key:
            return self._fallback_summary(kind=kind, title=title, text=text, company_name=company_name, evidence_sections=evidence_sections)

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                payload = self._call_openai(
                    kind=kind, title=title, text=text, company_name=company_name,
                    evidence_sections=evidence_sections, form_type=form_type,
                )
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
        form_type: str | None = None,
    ) -> dict[str, Any]:
        # Determine text limit based on form type
        normalized_form = (form_type or "").split("/")[0].upper() if form_type else ""
        text_limit = TEXT_LIMITS.get(normalized_form, 20000)
        form_context = FORM_TYPE_CONTEXT.get(normalized_form, "")

        prompt_parts = [
            f"Kind: {kind}",
            f"Title: {title}",
            f"Company: {company_name or 'N/A'}",
        ]
        if form_type:
            prompt_parts.append(f"Form Type: {form_type}")
        if form_context:
            prompt_parts.append(f"\nForm-specific guidance:\n{form_context}")
        prompt_parts.append(f"Evidence Sections: {', '.join(evidence_sections or []) or 'N/A'}")
        prompt_parts.append(f"\nSource text:\n{text[:text_limit]}")
        prompt = "\n".join(prompt_parts)
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

    def summarize_diff(
        self,
        *,
        form_type: str,
        company_name: str,
        current_text: str,
        prior_text: str,
        max_attempts: int = 2,
    ) -> dict:
        """Compare two sequential filings and return structured diff analysis."""
        if not self.settings.openai_api_key:
            return {"status": "skipped", "reason": "No OpenAI API key configured"}

        diff_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "added_risks": {"type": "array", "items": {"type": "string"}},
                "removed_risks": {"type": "array", "items": {"type": "string"}},
                "financial_deltas": {"type": "array", "items": {"type": "string"}},
                "guidance_changes": {"type": "array", "items": {"type": "string"}},
                "pipeline_updates": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["added_risks", "removed_risks", "financial_deltas", "guidance_changes", "pipeline_updates", "summary"],
        }

        diff_prompt = (
            f"Compare these two sequential {form_type} filings from {company_name}.\n\n"
            f"CURRENT FILING (newer):\n{current_text[:15000]}\n\n"
            f"PRIOR FILING (older):\n{prior_text[:15000]}\n\n"
            "Identify:\n"
            "- added_risks: New risk factors not in the prior filing\n"
            "- removed_risks: Risk factors removed or resolved since prior filing\n"
            "- financial_deltas: Material changes in financial metrics (revenue, expenses, guidance)\n"
            "- guidance_changes: Changes in forward-looking statements or outlook\n"
            "- pipeline_updates: Changes in clinical trials, regulatory milestones, or product pipeline\n"
            "- summary: 2-3 sentence overview of the most material changes"
        )

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
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
                            {"role": "user", "content": [{"type": "input_text", "text": diff_prompt}]},
                        ],
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "filing_diff_analysis",
                                "schema": diff_schema,
                                "strict": True,
                            }
                        },
                    },
                )
                response.raise_for_status()
                body = response.json()
                extracted = self._extract_json_payload(body)
                return json.loads(extracted) if isinstance(extracted, str) else extracted
            except (ValueError, httpx.HTTPError) as exc:
                last_error = exc

        return {"status": "failed", "reason": str(last_error)}

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

