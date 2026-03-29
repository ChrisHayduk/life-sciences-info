from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


@dataclass
class FilingDocument:
    content: bytes
    content_type: str
    source_url: str


class SECClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=self.settings.source_fetch_timeout_seconds,
            headers={"User-Agent": self.settings.sec_user_agent},
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_http_client:
            with contextlib.suppress(Exception):
                self.http_client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def _throttle(self) -> None:
        time.sleep(self.settings.sec_rate_limit_delay_seconds)

    def _get_json(self, url: str) -> dict[str, Any]:
        self._throttle()
        response = self.http_client.get(url)
        response.raise_for_status()
        return response.json()

    def get_company_tickers(self) -> list[dict[str, Any]]:
        payload = self._get_json(self.settings.sec_tickers_url)
        if "data" in payload and "fields" in payload:
            fields = payload["fields"]
            return [dict(zip(fields, row)) for row in payload["data"]]
        if isinstance(payload, dict):
            return list(payload.values())
        return payload

    def get_company_submissions(self, cik: str) -> dict[str, Any]:
        cik_padded = f"{int(cik):010d}"
        return self._get_json(f"{self.settings.sec_base_url}/submissions/CIK{cik_padded}.json")

    def iter_company_filings(self, cik: str) -> list[dict[str, Any]]:
        submissions = self.get_company_submissions(cik)
        recent = self._rows_from_columnar(submissions.get("filings", {}).get("recent", {}))
        older_files = submissions.get("filings", {}).get("files", [])
        rows = recent[:]
        for file_info in older_files:
            name = file_info.get("name")
            if not name:
                continue
            older_payload = self._get_json(f"{self.settings.sec_base_url}/submissions/{name}")
            rows.extend(self._rows_from_columnar(older_payload))
        return rows

    def _rows_from_columnar(self, payload: dict[str, list[Any]]) -> list[dict[str, Any]]:
        if not payload:
            return []
        keys = list(payload.keys())
        row_count = len(payload[keys[0]])
        rows: list[dict[str, Any]] = []
        for index in range(row_count):
            rows.append({key: payload[key][index] for key in keys})
        return rows

    def build_filing_urls(self, cik: str, accession_number: str, primary_document: str | None) -> dict[str, str]:
        accession_no_dashes = accession_number.replace("-", "")
        cik_int = str(int(cik))
        base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}"
        filing_url = f"{base}/{accession_number}-index.htm"
        original_document_url = f"{base}/{primary_document}" if primary_document else filing_url
        return {
            "base_url": base,
            "filing_url": filing_url,
            "original_document_url": original_document_url,
            "submission_text_url": f"{base}/{accession_number}.txt",
        }

    def download_primary_document(
        self,
        cik: str,
        accession_number: str,
        primary_document: str | None,
    ) -> FilingDocument:
        urls = self.build_filing_urls(cik, accession_number, primary_document)
        candidate_urls = [
            urls["original_document_url"],
            urls["filing_url"],
            urls["submission_text_url"],
        ]
        last_error: Exception | None = None
        for candidate_url in candidate_urls:
            try:
                self._throttle()
                response = self.http_client.get(candidate_url)
                response.raise_for_status()
                return FilingDocument(
                    content=response.content,
                    content_type=response.headers.get("Content-Type", "text/plain"),
                    source_url=candidate_url,
                )
            except Exception as exc:  # pragma: no cover - exercised in live SEC access
                last_error = exc
                continue
        raise last_error or RuntimeError("Unable to download SEC filing document")
