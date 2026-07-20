"""Outbound email, shared by the API (subscription confirmations) and the
nightly notifier (topic digests). Plain SMTP with STARTTLS, configured
entirely by environment:

    SMTP_HOST      unset -> emails are logged and dropped (local dev)
    SMTP_PORT      default 587
    SMTP_USERNAME / SMTP_PASSWORD
    MAIL_FROM      default "CouncilHound <hound@councilhound.net>"
"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
MAIL_FROM = os.environ.get("MAIL_FROM", "CouncilHound <hound@councilhound.net>")


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one message. Returns True when handed to the SMTP server;
    False (after logging) when SMTP is unconfigured or the send fails —
    callers must not advance notification watermarks on False."""
    if not SMTP_HOST:
        log.info("SMTP unconfigured — dropping email to %s: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD or "")
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("email send failed (to=%s subject=%r)", to, subject)
        return False
