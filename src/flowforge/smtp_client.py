"""Email delivery — SMTP (Mailtrap dev) or AWS SES (production)."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

import boto3

from flowforge.config import Settings, get_settings

logger = logging.getLogger(__name__)

EmailProvider = Literal["smtp", "ses"]


def send_html_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Send one HTML email via configured provider."""

    resolved = settings or get_settings()

    if not resolved.email_enabled:
        logger.debug("Email disabled — skipping send to %s", to_email)

        return

    provider = resolved.email_provider

    if provider == "ses":
        _send_via_ses(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            settings=resolved,
        )
    else:
        _send_via_smtp(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            settings=resolved,
        )


def _send_via_smtp(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
    settings: Settings,
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to_email

    plain = text_body or "View this message in an HTML-capable email client."
    message.attach(MIMEText(plain, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()

            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)

            smtp.sendmail(settings.email_from, [to_email], message.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)

            smtp.sendmail(settings.email_from, [to_email], message.as_string())

    logger.info("SMTP email sent to %s subject=%r", to_email, subject)


def _send_via_ses(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
    settings: Settings,
) -> None:
    client = boto3.client("ses", region_name=settings.ses_region)

    body: dict[str, dict[str, str]] = {
        "Html": {"Data": html_body, "Charset": "UTF-8"},
    }

    if text_body:
        body["Text"] = {"Data": text_body, "Charset": "UTF-8"}

    client.send_email(
        Source=settings.email_from,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": body,
        },
    )

    logger.info("SES email sent to %s subject=%r", to_email, subject)
