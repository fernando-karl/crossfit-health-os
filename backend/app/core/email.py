"""
Transactional email via SMTP (stdlib).

When SMTP is not configured, callers should fall back to logging the message
(for local dev). Production sets SMTP_* in backend/.env.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool((settings.SMTP_HOST or "").strip() and (settings.SMTP_FROM or "").strip())


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    """Send an email. Returns True on success, False if SMTP disabled or send failed."""
    if not smtp_configured():
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        with server:
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        logger.info("Email sent to %s subject=%s", to_email, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    app = settings.APP_NAME
    subject = f"{app} — redefinir senha"
    text = (
        f"Recebemos um pedido para redefinir a senha da sua conta {app}.\n\n"
        f"Abra o link abaixo (válido por 1 hora):\n{reset_url}\n\n"
        "Se você não solicitou, ignore este e-mail."
    )
    html = (
        f"<p>Recebemos um pedido para redefinir a senha da sua conta <strong>{app}</strong>.</p>"
        f'<p><a href="{reset_url}">Redefinir senha</a> (válido por 1 hora)</p>'
        "<p>Se você não solicitou, ignore este e-mail.</p>"
    )
    return send_email(to_email=to_email, subject=subject, text_body=text, html_body=html)
