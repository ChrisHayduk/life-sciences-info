from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from app.config import Settings, get_settings
from app.models import Digest


class DigestEmailService:
    def __init__(self, settings: Settings | None = None, smtp_factory=smtplib.SMTP) -> None:
        self.settings = settings or get_settings()
        self.smtp_factory = smtp_factory

    def is_enabled(self) -> bool:
        return bool(self.settings.digest_email_enabled)

    def is_configured(self) -> bool:
        return bool(
            self.settings.digest_email_from
            and self.settings.digest_email_to
            and self.settings.smtp_host
            and self.settings.smtp_port
            and self.settings.smtp_username
            and self.settings.smtp_password
        )

    def build_daily_digest_message(self, digest: Digest) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = digest.title
        message["From"] = self.settings.digest_email_from
        message["To"] = self.settings.digest_email_to
        message.set_content(self._plain_text_body(digest))
        message.add_alternative(self._html_body(digest), subtype="html")
        return message

    def send_daily_digest(self, digest: Digest) -> None:
        message = self.build_daily_digest_message(digest)
        with self.smtp_factory(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if self.settings.smtp_use_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)

    def _frontend_url(self, path: str) -> str:
        base = self.settings.frontend_base_url.rstrip("/")
        return f"{base}{path}"

    def _plain_text_body(self, digest: Digest) -> str:
        payload = digest.payload or {}
        filings = payload.get("filings") or []
        news_items = payload.get("news") or []
        lines = [
            digest.title,
            "",
            f"Digest archive: {self._frontend_url('/digests')}",
            "",
            (digest.narrative_summary or "").strip(),
        ]

        if filings:
            lines.extend(["", "Top Filings"])
            for filing in filings:
                filing_id = filing.get("id")
                company_id = filing.get("company_id")
                lines.append(
                    f"- {filing.get('title') or 'Untitled filing'}"
                    + (f" — {filing.get('company_name')}" if filing.get("company_name") else "")
                )
                if filing_id:
                    lines.append(f"  Filing: {self._frontend_url(f'/filings/{filing_id}')}")
                if company_id:
                    lines.append(f"  Company: {self._frontend_url(f'/companies/{company_id}')}")

        if news_items:
            lines.extend(["", "Top News"])
            for item in news_items:
                lines.append(
                    f"- {item.get('title') or 'Untitled news item'}"
                    + (f" ({item.get('source_name')})" if item.get("source_name") else "")
                )
                if item.get("canonical_url"):
                    lines.append(f"  Article: {item['canonical_url']}")
                for company_id, company_name in zip(item.get("company_tag_ids") or [], item.get("mentioned_companies") or []):
                    lines.append(f"  Company: {company_name} — {self._frontend_url(f'/companies/{company_id}')}")

        return "\n".join(lines).strip() + "\n"

    def _html_body(self, digest: Digest) -> str:
        payload = digest.payload or {}
        filings = payload.get("filings") or []
        news_items = payload.get("news") or []
        archive_url = self._frontend_url("/digests")

        parts = [
            "<html><body style=\"font-family:Arial,sans-serif;color:#111827;line-height:1.5;\">",
            f"<h1 style=\"font-size:22px;margin-bottom:8px;\">{escape(digest.title)}</h1>",
            f"<p style=\"margin:0 0 16px;\"><a href=\"{escape(archive_url, quote=True)}\">Open digest archive</a></p>",
            f"<div style=\"white-space:pre-wrap;margin-bottom:20px;\">{escape((digest.narrative_summary or '').strip())}</div>",
        ]

        if filings:
            parts.append("<h2 style=\"font-size:18px;margin:20px 0 8px;\">Top Filings</h2><ul>")
            for filing in filings:
                filing_url = self._frontend_url(f"/filings/{filing['id']}") if filing.get("id") else None
                company_url = self._frontend_url(f"/companies/{filing['company_id']}") if filing.get("company_id") else None
                title = escape(filing.get("title") or "Untitled filing")
                company_name = escape(filing.get("company_name") or "")
                entry = "<li>"
                entry += (
                    f"<a href=\"{escape(filing_url, quote=True)}\">{title}</a>"
                    if filing_url
                    else title
                )
                if company_name:
                    entry += " — "
                    entry += (
                        f"<a href=\"{escape(company_url, quote=True)}\">{company_name}</a>"
                        if company_url
                        else company_name
                    )
                entry += "</li>"
                parts.append(entry)
            parts.append("</ul>")

        if news_items:
            parts.append("<h2 style=\"font-size:18px;margin:20px 0 8px;\">Top News</h2><ul>")
            for item in news_items:
                title = escape(item.get("title") or "Untitled news item")
                source_name = escape(item.get("source_name") or "")
                canonical_url = item.get("canonical_url")
                entry = "<li>"
                entry += (
                    f"<a href=\"{escape(canonical_url, quote=True)}\">{title}</a>"
                    if canonical_url
                    else title
                )
                if source_name:
                    entry += f" <span style=\"color:#6b7280;\">({source_name})</span>"
                company_links: list[str] = []
                for company_id, company_name in zip(item.get("company_tag_ids") or [], item.get("mentioned_companies") or []):
                    company_url = self._frontend_url(f"/companies/{company_id}")
                    company_links.append(
                        f"<a href=\"{escape(company_url, quote=True)}\">{escape(company_name)}</a>"
                    )
                if company_links:
                    entry += " — " + ", ".join(company_links)
                entry += "</li>"
                parts.append(entry)
            parts.append("</ul>")

        parts.append("</body></html>")
        return "".join(parts)
