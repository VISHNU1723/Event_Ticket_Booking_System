
import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def send_email_notification(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: Optional[str] = None,
) -> bool:
    """Send an email, optionally attaching a PDF ticket."""

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", smtp_user or "")

    if not all([smtp_host, smtp_user, smtp_password, sender]):
        logger.error("Email not sent: SMTP settings are missing.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    if attachment_path:
        path = Path(attachment_path)
        if not path.is_file():
            logger.error("Email attachment not found: %s", path)
            return False

        try:
            with path.open("rb") as file:
                message.add_attachment(
                    file.read(),
                    maintype="application",
                    subtype="pdf",
                    filename=path.name,
                )
        except OSError:
            logger.exception("Could not read email attachment: %s", path)
            return False

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)

        logger.info("Email sent to %s: %s", recipient, subject)
        return True

    except (smtplib.SMTPException, OSError, ValueError):
        logger.exception("Email delivery failed for %s", recipient)
        return False
