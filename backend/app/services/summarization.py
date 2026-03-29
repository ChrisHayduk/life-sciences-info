from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import SummaryPayload

# Lightweight schema for 8-K event filings (6 fields vs 14 in full schema)
EIGHT_K_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "event_type": {"type": "string"},
        "key_takeaways": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "importance_score": {"type": "number"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["name", "type", "context"],
            },
        },
    },
    "required": ["summary", "event_type", "key_takeaways", "risk_flags", "importance_score", "entities"],
}

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

TEXT_LIMITS: dict[str, int] = {
    "10-K": 30000,
    "20-F": 30000,
    "40-F": 30000,
    "10-Q": 20000,
    "8-K": 15000,
    "6-K": 15000,
}

MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached_input": 0.02, "output": 1.25},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
}


@dataclass
class UsageMetrics:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class SummaryCallResult:
    payload: SummaryPayload
    usage: UsageMetrics


@dataclass
class DiffCallResult:
    payload: dict[str, Any]
    usage: UsageMetrics


@dataclass
class DigestCallResult:
    text: str
    usage: UsageMetrics


class OpenAISummarizer:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=60.0)

    def close(self) -> None:
        if self._owns_http_client:
            with contextlib.suppress(Exception):
                self.http_client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

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
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> SummaryPayload:
        return self.summarize_with_usage(
            kind=kind,
            title=title,
            text=text,
            company_name=company_name,
            evidence_sections=evidence_sections,
            form_type=form_type,
            max_attempts=max_attempts,
            model=model,
            prompt_cache_key=prompt_cache_key,
        ).payload

    def summarize_with_usage(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        company_name: str | None = None,
        evidence_sections: list[str] | None = None,
        form_type: str | None = None,
        max_attempts: int = 2,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> SummaryCallResult:
        selected_model = model or self.settings.openai_model
        if not self.settings.openai_api_key:
            payload = self._fallback_summary(
                kind=kind,
                title=title,
                text=text,
                company_name=company_name,
                evidence_sections=evidence_sections,
            )
            return SummaryCallResult(payload=payload, usage=UsageMetrics(model="fallback-local"))

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                payload, usage = self._call_openai(
                    kind=kind,
                    title=title,
                    text=text,
                    company_name=company_name,
                    evidence_sections=evidence_sections,
                    form_type=form_type,
                    model=selected_model,
                    prompt_cache_key=prompt_cache_key,
                )
                return SummaryCallResult(payload=SummaryPayload.model_validate(payload), usage=usage)
            except (ValidationError, ValueError, httpx.HTTPError) as exc:
                last_error = exc
        raise RuntimeError(f"Unable to summarize after {max_attempts} attempts") from last_error

    def summarize_diff(
        self,
        *,
        form_type: str,
        company_name: str,
        current_text: str,
        prior_text: str,
        max_attempts: int = 2,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> dict[str, Any]:
        return self.summarize_diff_with_usage(
            form_type=form_type,
            company_name=company_name,
            current_text=current_text,
            prior_text=prior_text,
            max_attempts=max_attempts,
            model=model,
            prompt_cache_key=prompt_cache_key,
        ).payload

    def summarize_diff_with_usage(
        self,
        *,
        form_type: str,
        company_name: str,
        current_text: str,
        prior_text: str,
        max_attempts: int = 2,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> DiffCallResult:
        selected_model = model or self.settings.openai_model
        if not self.settings.openai_api_key:
            return DiffCallResult(
                payload={"status": "skipped", "reason": "No OpenAI API key configured"},
                usage=UsageMetrics(model="fallback-local"),
            )

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

        request_body = {
            "model": selected_model,
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
        }
        if prompt_cache_key:
            request_body["prompt_cache_key"] = prompt_cache_key

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                body = self._post_responses(request_body)
                extracted = self._extract_json_payload(body)
                payload = json.loads(extracted) if isinstance(extracted, str) else extracted
                return DiffCallResult(
                    payload=payload,
                    usage=self._extract_usage_metrics(body, selected_model),
                )
            except (ValueError, httpx.HTTPError) as exc:
                last_error = exc

        return DiffCallResult(
            payload={"status": "failed", "reason": str(last_error)},
            usage=UsageMetrics(model=selected_model),
        )

    def summarize_digest(
        self,
        *,
        window_label: str,
        filing_summaries: list[dict[str, str]],
        news_summaries: list[dict[str, str]],
        max_attempts: int = 2,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> str:
        return self.summarize_digest_with_usage(
            window_label=window_label,
            filing_summaries=filing_summaries,
            news_summaries=news_summaries,
            max_attempts=max_attempts,
            model=model,
            prompt_cache_key=prompt_cache_key,
        ).text

    def summarize_digest_with_usage(
        self,
        *,
        window_label: str,
        filing_summaries: list[dict[str, str]],
        news_summaries: list[dict[str, str]],
        max_attempts: int = 2,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> DigestCallResult:
        selected_model = model or self.settings.openai_model
        if not self.settings.openai_api_key:
            return DigestCallResult(
                text=self._fallback_digest_narrative(filing_summaries, news_summaries),
                usage=UsageMetrics(model="fallback-local"),
            )

        filing_block = "\n".join(
            f"- [{f.get('form_type', 'Filing')}] {f.get('company', 'Unknown')}: {f.get('summary', '')}"
            for f in filing_summaries[:10]
        )
        news_block = "\n".join(
            f"- [{n.get('source', 'News')}] {n.get('title', '')}: {n.get('summary', '')}"
            for n in news_summaries[:10]
        )
        digest_prompt = (
            f"Digest window: {window_label}\n\n"
            f"TOP FILINGS IN THIS WINDOW:\n{filing_block or 'None'}\n\n"
            f"TOP NEWS IN THIS WINDOW:\n{news_block or 'None'}\n\n"
            "Write a concise life sciences intelligence digest in markdown. "
            "Synthesize themes across filings and news rather than listing items one-by-one. "
            "Explain what changed, why it matters, and what the reader should open next."
        )

        request_body = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You write concise intelligence digests for life sciences investors. "
                                "Use markdown. Focus on what changed, why it matters, and how the items connect."
                            ),
                        }
                    ],
                },
                {"role": "user", "content": [{"type": "input_text", "text": digest_prompt}]},
            ],
        }
        if prompt_cache_key:
            request_body["prompt_cache_key"] = prompt_cache_key

        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                body = self._post_responses(request_body)
                text = self._extract_plain_text(body)
                return DigestCallResult(
                    text=text,
                    usage=self._extract_usage_metrics(body, selected_model),
                )
            except (ValueError, httpx.HTTPError) as exc:
                last_error = exc

        return DigestCallResult(
            text=self._fallback_digest_narrative(filing_summaries, news_summaries),
            usage=UsageMetrics(model=selected_model),
        )

    def _call_openai(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        company_name: str | None,
        evidence_sections: list[str] | None,
        form_type: str | None = None,
        model: str,
        prompt_cache_key: str | None = None,
    ) -> tuple[dict[str, Any], UsageMetrics]:
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

        request_body = {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "life_sciences_8k_summary" if normalized_form == "8-K" else "life_sciences_summary",
                    "schema": EIGHT_K_SUMMARY_SCHEMA if normalized_form == "8-K" else SUMMARY_SCHEMA,
                    "strict": True,
                }
            },
        }
        if prompt_cache_key:
            request_body["prompt_cache_key"] = prompt_cache_key

        body = self._post_responses(request_body)
        extracted = self._extract_json_payload(body)
        payload = json.loads(extracted) if isinstance(extracted, str) else extracted
        return payload, self._extract_usage_metrics(body, model)

    def _post_responses(self, request_body: dict[str, Any]) -> dict[str, Any]:
        response = self.http_client.post(
            f"{self.settings.openai_api_base}/responses",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        return response.json()

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

    def _extract_plain_text(self, body: dict[str, Any]) -> str:
        if body.get("output_text"):
            return str(body["output_text"])
        for output in body.get("output", []):
            for content in output.get("content", []):
                text = content.get("text")
                if text:
                    return str(text)
        raise ValueError("No text in response")

    def _extract_usage_metrics(self, body: dict[str, Any], requested_model: str) -> UsageMetrics:
        model = str(body.get("model") or requested_model)
        usage = body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cached_tokens = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        reasoning_tokens = int((usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)
        estimated_cost = self._estimate_cost_usd(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
        )
        return UsageMetrics(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_input_tokens=cached_tokens,
            estimated_cost_usd=estimated_cost,
        )

    def _estimate_cost_usd(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
    ) -> float:
        pricing = MODEL_PRICING_PER_1M.get(self._canonical_model_name(model))
        if not pricing:
            return 0.0
        uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
        input_cost = uncached_input_tokens * pricing["input"] / 1_000_000
        cached_input_cost = cached_input_tokens * pricing.get("cached_input", pricing["input"]) / 1_000_000
        output_cost = output_tokens * pricing["output"] / 1_000_000
        return round(input_cost + cached_input_cost + output_cost, 6)

    @staticmethod
    def _canonical_model_name(model: str) -> str:
        normalized = (model or "").strip()
        for candidate in MODEL_PRICING_PER_1M:
            if normalized == candidate or normalized.startswith(f"{candidate}-"):
                return candidate
        return normalized

    @staticmethod
    def _fallback_digest_narrative(
        filing_summaries: list[dict[str, str]],
        news_summaries: list[dict[str, str]],
    ) -> str:
        bits = []
        if filing_summaries:
            bits.append(f"{len(filing_summaries)} notable filings were captured in this window.")
        if news_summaries:
            top_title = news_summaries[0].get("title", "")
            bits.append(f"{len(news_summaries)} important news items were tracked, led by {top_title}.")
        return " ".join(bits) or "No qualifying filings or news were captured in this digest window."

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

        importance = min(
            100.0,
            30.0
            + 10.0
            * sum(keyword in lower for keyword in ["approval", "guidance", "restructuring", "trial", "earnings", "revenue"]),
        )
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
