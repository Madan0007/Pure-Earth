"""
brevo_backend.py

An email backend that sends via Brevo's HTTP API (https://api.brevo.com)
instead of SMTP.

Why this exists: Render's free web services block outbound traffic to SMTP
ports (25, 465, 587) as of September 2025 -- see
https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports.
That makes the app's existing SMTP-based email system (base.backends,
DynamicEmailConfiguration) unusable on Render's free tier regardless of how
correctly it's configured, since the connection is blocked before it ever
reaches Brevo. Brevo's REST API runs over plain HTTPS (port 443), which
Render does not block, so this achieves the same result -- sending email via
Brevo -- through a path that actually works on the free tier.

This does not touch or replace DynamicEmailConfiguration or
base.backends.ConfiguredEmailBackend. It's a separate, self-contained Django
EmailBackend, wired in only via the EMAIL_BACKEND setting. To go back to the
original SMTP-based system later (e.g. after upgrading off the free tier),
just remove the EMAIL_BACKEND environment variable -- nothing else needs to
change.

Setup:
1. In Brevo: Settings -> SMTP & API -> API Keys tab -> Generate a new API
   key. This is different from the SMTP key used for SMTP auth -- an API key
   is required here, an SMTP key will not work.
2. On Render, set the environment variable BREVO_API_KEY to that key.
3. On Render, set the environment variable EMAIL_BACKEND to
   "base.brevo_backend.BrevoAPIEmailBackend"
"""

import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _split_address(address: str) -> dict:
    """'Display Name <a@b.com>' or 'a@b.com' -> {"name": ..., "email": ...}."""
    name, email = parseaddr(address)
    result = {"email": email or address}
    if name:
        result["name"] = name
    return result


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Sends Django EmailMessage objects through Brevo's REST API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, "BREVO_API_KEY", None)

    def _build_payload(self, message) -> dict:
        if not message.recipients():
            return None

        sender = _split_address(message.from_email or getattr(
            settings, "DEFAULT_FROM_EMAIL", ""
        ))
        if not sender.get("email"):
            raise ValueError("Email has no from address and DEFAULT_FROM_EMAIL is not set")

        payload = {
            "sender": sender,
            "subject": message.subject or "",
        }

        to = [_split_address(a) for a in (message.to or [])]
        if to:
            payload["to"] = to
        cc = [_split_address(a) for a in (message.cc or [])]
        if cc:
            payload["cc"] = cc
        bcc = [_split_address(a) for a in (message.bcc or [])]
        if bcc:
            payload["bcc"] = bcc
        if not payload.get("to"):
            # Brevo requires at least one "to" recipient; a cc/bcc-only
            # message (unusual, but technically valid EmailMessage) has to
            # fall back to something rather than silently 400.
            payload["to"] = cc or bcc
            if "cc" in payload and payload["to"] is cc:
                del payload["cc"]
            if "bcc" in payload and payload["to"] is bcc:
                del payload["bcc"]

        if message.reply_to:
            payload["replyTo"] = _split_address(message.reply_to[0])

        # This app sets `content_subtype = "html"` on plain EmailMessage
        # instances in several places (body IS html in that case), and may
        # also use EmailMultiAlternatives (body is plain text, html lives in
        # .alternatives). Handle both without assuming either.
        html_content = None
        text_content = None
        if getattr(message, "content_subtype", "plain") == "html":
            html_content = message.body
        else:
            text_content = message.body
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                html_content = content

        if html_content:
            payload["htmlContent"] = html_content
        if text_content:
            payload["textContent"] = text_content
        if not html_content and not text_content:
            # Brevo rejects a request with neither -- an empty body is
            # unusual but shouldn't crash the send.
            payload["textContent"] = ""

        attachments = []
        for attachment in getattr(message, "attachments", []) or []:
            # EmailMessage.attachments entries are either a (filename,
            # content, mimetype) tuple, or a MIMEBase object for
            # already-encoded attachments (e.g. attach_file with certain
            # types). Only the common tuple form is handled here.
            if isinstance(attachment, tuple):
                filename, content, _mimetype = attachment
                if isinstance(content, str):
                    content = content.encode("utf-8")
                import base64

                attachments.append(
                    {
                        "name": filename,
                        "content": base64.b64encode(content).decode("ascii"),
                    }
                )
        if attachments:
            payload["attachment"] = attachments

        return payload

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        if not self.api_key:
            if self.fail_silently:
                logger.error("BREVO_API_KEY is not set; skipping email send.")
                return 0
            raise ValueError(
                "BREVO_API_KEY is not set. Add it in Render's Environment settings."
            )

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }

        sent_count = 0
        for message in email_messages:
            try:
                payload = self._build_payload(message)
                if payload is None:
                    continue
                response = requests.post(
                    BREVO_API_URL, json=payload, headers=headers, timeout=15
                )
                if response.status_code in (200, 201):
                    sent_count += 1
                else:
                    logger.error(
                        "Brevo API send failed (%s): %s",
                        response.status_code,
                        response.text[:500],
                    )
                    if not self.fail_silently:
                        response.raise_for_status()
            except Exception:
                logger.exception("Failed to send email via Brevo API")
                if not self.fail_silently:
                    raise

        self._log_sent_messages(email_messages, sent_count)
        return sent_count

    @staticmethod
    def _log_sent_messages(email_messages, sent_count):
        """Mirrors base.backends.ConfiguredEmailBackend's EmailLog behavior,
        which this backend bypasses since it doesn't inherit from it."""
        try:
            from base.models import EmailLog
        except Exception:
            return
        for message in email_messages:
            try:
                EmailLog.objects.create(
                    subject=message.subject,
                    from_email=message.from_email or "",
                    to=message.to,
                    body=message.body,
                    status="sent" if sent_count else "failed",
                )
            except Exception:
                logger.exception("Failed to write EmailLog entry")
