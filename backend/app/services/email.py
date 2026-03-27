"""Email delivery service for weekly digest distribution."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_digest_email(
    *,
    title: str,
    narrative_summary: str,
    filings_count: int,
    news_count: int,
    digest_url: str,
) -> dict[str, Any]:
    """Send a digest email to configured recipients.

    Returns a dict with 'sent' count and 'errors' list.
    """
    settings = get_settings()

    smtp_host = settings.extra_metadata.get("smtp_host") if hasattr(settings, "extra_metadata") else None
    smtp_port = settings.extra_metadata.get("smtp_port", 587) if hasattr(settings, "extra_metadata") else 587
    smtp_user = settings.extra_metadata.get("smtp_user") if hasattr(settings, "extra_metadata") else None
    smtp_password = settings.extra_metadata.get("smtp_password") if hasattr(settings, "extra_metadata") else None
    from_email = settings.extra_metadata.get("digest_from_email", "noreply@lifesciencesintel.com") if hasattr(settings, "extra_metadata") else "noreply@lifesciencesintel.com"
    recipients_raw = settings.extra_metadata.get("digest_recipients", "") if hasattr(settings, "extra_metadata") else ""

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not smtp_host or not recipients:
        logger.info("Email delivery skipped: no SMTP host or recipients configured")
        return {"sent": 0, "errors": ["Email delivery not configured"]}

    # Build HTML email
    html_body = _build_digest_html(
        title=title,
        narrative_summary=narrative_summary,
        filings_count=filings_count,
        news_count=news_count,
        digest_url=digest_url,
    )

    sent = 0
    errors: list[str] = []

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)

            for recipient in recipients:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = f"Weekly Digest: {title}"
                    msg["From"] = from_email
                    msg["To"] = recipient
                    msg.attach(MIMEText(narrative_summary, "plain"))
                    msg.attach(MIMEText(html_body, "html"))
                    server.sendmail(from_email, recipient, msg.as_string())
                    sent += 1
                except Exception as exc:
                    errors.append(f"Failed to send to {recipient}: {exc}")
                    logger.warning("Failed to send digest email to %s: %s", recipient, exc)
    except Exception as exc:
        errors.append(f"SMTP connection failed: {exc}")
        logger.error("SMTP connection failed: %s", exc)

    return {"sent": sent, "errors": errors}


def _build_digest_html(
    *,
    title: str,
    narrative_summary: str,
    filings_count: int,
    news_count: int,
    digest_url: str,
) -> str:
    """Build a simple HTML email template for the weekly digest."""
    # Escape basic HTML in the narrative
    safe_narrative = (
        narrative_summary
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body style="margin:0;padding:0;font-family:'Avenir Next','Manrope','Segoe UI',sans-serif;background-color:#f4efe5;color:#112b28;">
    <div style="max-width:640px;margin:0 auto;padding:32px 24px;">
        <div style="background:rgba(255,252,247,0.88);border:1px solid rgba(9,49,49,0.12);border-radius:24px;padding:28px;box-shadow:0 20px 60px rgba(17,43,40,0.1);">
            <p style="text-transform:uppercase;letter-spacing:0.18em;font-size:0.72rem;color:#4f6763;margin:0;">
                Life Sciences Intelligence
            </p>
            <h1 style="font-family:'Iowan Old Style','Palatino Linotype',serif;font-size:1.5rem;letter-spacing:-0.03em;margin:8px 0 16px;">
                {title}
            </h1>
            <p style="font-size:0.92rem;color:#4f6763;margin:0 0 20px;">
                {filings_count} filings and {news_count} news items analyzed
            </p>
            <div style="font-size:0.95rem;line-height:1.6;">
                {safe_narrative}
            </div>
            <div style="margin-top:24px;padding-top:16px;border-top:1px solid rgba(9,49,49,0.12);">
                <a href="{digest_url}"
                   style="display:inline-block;padding:10px 20px;background:#0e6c67;color:#ffffff;border-radius:14px;text-decoration:none;font-weight:700;font-size:0.9rem;">
                    View Full Digest
                </a>
            </div>
        </div>
        <p style="text-align:center;font-size:0.75rem;color:#4f6763;margin:16px 0 0;">
            Intel Grid &middot; Weekly digest every Monday at 8:00 AM ET
        </p>
    </div>
</body>
</html>"""
