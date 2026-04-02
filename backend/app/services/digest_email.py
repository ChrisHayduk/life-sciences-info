from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from app.config import Settings, get_settings
from app.models import Digest

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
ORDERED_LIST_RE = re.compile(r"^(\d+)\.\s+(.*)$")
UNORDERED_LIST_RE = re.compile(r"^[-*]\s+(.*)$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


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
            self._markdown_to_plain_text((digest.narrative_summary or "").strip()),
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
        rendered_summary = self._markdown_to_html((digest.narrative_summary or "").strip())

        parts = [
            "<html><body style=\"margin:0;padding:24px;background:#f3f4f6;font-family:Arial,sans-serif;color:#111827;line-height:1.6;\">",
            "<div style=\"max-width:720px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;\">",
            "<div style=\"padding:28px 32px;background:linear-gradient(135deg,#0f172a 0%,#1d4ed8 100%);color:#ffffff;\">",
            "<div style=\"font-size:12px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.8;margin-bottom:10px;\">Life Sciences Intel</div>",
            f"<h1 style=\"font-size:28px;line-height:1.2;margin:0 0 12px;\">{escape(digest.title)}</h1>",
            f"<a href=\"{escape(archive_url, quote=True)}\" style=\"display:inline-block;padding:10px 14px;background:#ffffff;color:#1d4ed8;text-decoration:none;border-radius:999px;font-weight:600;\">Open digest archive</a>",
            "</div>",
            "<div style=\"padding:28px 32px;\">",
            f"<div style=\"font-size:16px;\">{rendered_summary}</div>",
        ]

        if filings:
            parts.append("<h2 style=\"font-size:18px;margin:28px 0 12px;\">Top Filings</h2>")
            parts.append("<div>")
            for filing in filings:
                filing_url = self._frontend_url(f"/filings/{filing['id']}") if filing.get("id") else None
                company_url = self._frontend_url(f"/companies/{filing['company_id']}") if filing.get("company_id") else None
                title = escape(filing.get("title") or "Untitled filing")
                company_name = escape(filing.get("company_name") or "")
                entry = "<div style=\"padding:14px 16px;margin:0 0 10px;border:1px solid #e5e7eb;border-radius:14px;background:#f9fafb;\">"
                entry += (
                    f"<a href=\"{escape(filing_url, quote=True)}\" style=\"font-weight:700;color:#111827;text-decoration:none;\">{title}</a>"
                    if filing_url
                    else title
                )
                if company_name:
                    entry += "<div style=\"margin-top:4px;color:#4b5563;\">"
                    entry += (
                        f"<a href=\"{escape(company_url, quote=True)}\" style=\"color:#2563eb;text-decoration:none;\">{company_name}</a>"
                        if company_url
                        else company_name
                    )
                    entry += "</div>"
                entry += "</div>"
                parts.append(entry)
            parts.append("</div>")

        if news_items:
            parts.append("<h2 style=\"font-size:18px;margin:28px 0 12px;\">Top News</h2>")
            parts.append("<div>")
            for item in news_items:
                title = escape(item.get("title") or "Untitled news item")
                source_name = escape(item.get("source_name") or "")
                canonical_url = item.get("canonical_url")
                entry = "<div style=\"padding:14px 16px;margin:0 0 10px;border:1px solid #e5e7eb;border-radius:14px;background:#f9fafb;\">"
                entry += (
                    f"<a href=\"{escape(canonical_url, quote=True)}\" style=\"font-weight:700;color:#111827;text-decoration:none;\">{title}</a>"
                    if canonical_url
                    else title
                )
                if source_name:
                    entry += f"<div style=\"margin-top:4px;color:#6b7280;\">{source_name}</div>"
                company_links: list[str] = []
                for company_id, company_name in zip(item.get("company_tag_ids") or [], item.get("mentioned_companies") or []):
                    company_url = self._frontend_url(f"/companies/{company_id}")
                    company_links.append(
                        f"<a href=\"{escape(company_url, quote=True)}\" style=\"color:#2563eb;text-decoration:none;\">{escape(company_name)}</a>"
                    )
                if company_links:
                    entry += "<div style=\"margin-top:8px;color:#4b5563;\">" + ", ".join(company_links) + "</div>"
                entry += "</div>"
                parts.append(entry)
            parts.append("</div>")

        parts.append("</div></div></body></html>")
        return "".join(parts)

    def _markdown_to_plain_text(self, markdown_text: str) -> str:
        text = markdown_text.replace("\r\n", "\n").strip()
        if not text:
            return ""
        text = LINK_RE.sub(r"\1 (\2)", text)
        text = BOLD_RE.sub(r"\1", text)
        text = ITALIC_RE.sub(r"\1", text)
        text = INLINE_CODE_RE.sub(r"\1", text)

        plain_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                plain_lines.append("")
                continue
            heading = HEADING_RE.match(line)
            if heading:
                plain_lines.append(heading.group(2).strip())
                continue
            plain_lines.append(line)
        return "\n".join(plain_lines).strip()

    def _markdown_to_html(self, markdown_text: str) -> str:
        text = markdown_text.replace("\r\n", "\n").strip()
        if not text:
            return ""

        blocks: list[str] = []
        paragraph_lines: list[str] = []
        list_items: list[str] = []
        list_kind: str | None = None

        def flush_paragraph() -> None:
            nonlocal paragraph_lines
            if paragraph_lines:
                content = " ".join(line.strip() for line in paragraph_lines if line.strip())
                blocks.append(f"<p style=\"margin:0 0 14px;\">{self._render_inline_markdown(content)}</p>")
                paragraph_lines = []

        def flush_list() -> None:
            nonlocal list_items, list_kind
            if list_items and list_kind:
                style = "margin:0 0 16px 20px;padding:0;"
                blocks.append(f"<{list_kind} style=\"{style}\">{''.join(list_items)}</{list_kind}>")
            list_items = []
            list_kind = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                flush_list()
                continue

            heading = HEADING_RE.match(line)
            if heading:
                flush_paragraph()
                flush_list()
                level = min(len(heading.group(1)) + 1, 6)
                margin = "24px 0 10px" if level <= 3 else "18px 0 8px"
                size = {2: 24, 3: 20, 4: 18, 5: 16, 6: 15}.get(level, 15)
                blocks.append(
                    f"<h{level} style=\"margin:{margin};font-size:{size}px;line-height:1.3;\">"
                    f"{self._render_inline_markdown(heading.group(2).strip())}</h{level}>"
                )
                continue

            ordered = ORDERED_LIST_RE.match(line)
            if ordered:
                flush_paragraph()
                if list_kind not in {None, 'ol'}:
                    flush_list()
                list_kind = "ol"
                list_items.append(
                    f"<li style=\"margin:0 0 8px;\">{self._render_inline_markdown(ordered.group(2).strip())}</li>"
                )
                continue

            unordered = UNORDERED_LIST_RE.match(line)
            if unordered:
                flush_paragraph()
                if list_kind not in {None, 'ul'}:
                    flush_list()
                list_kind = "ul"
                list_items.append(
                    f"<li style=\"margin:0 0 8px;\">{self._render_inline_markdown(unordered.group(1).strip())}</li>"
                )
                continue

            flush_list()
            paragraph_lines.append(line)

        flush_paragraph()
        flush_list()
        return "".join(blocks)

    def _render_inline_markdown(self, text: str) -> str:
        rendered = escape(text)
        rendered = LINK_RE.sub(
            lambda match: (
                f'<a href="{match.group(2)}" style="color:#2563eb;text-decoration:none;">{match.group(1)}</a>'
            ),
            rendered,
        )
        rendered = BOLD_RE.sub(r"<strong>\1</strong>", rendered)
        rendered = ITALIC_RE.sub(r"<em>\1</em>", rendered)
        rendered = INLINE_CODE_RE.sub(
            lambda match: (
                f'<code style="font-family:Menlo,monospace;background:#e5e7eb;'
                f'padding:1px 4px;border-radius:4px;">{match.group(1)}</code>'
            ),
            rendered,
        )
        return rendered
