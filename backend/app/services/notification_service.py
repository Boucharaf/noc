"""
Notifications sortantes sur incident critique : SMS (Twilio) et e-mail.

Appelé par le veilleur (watcher_service), plus par un endpoint HTTP. Ne
lève jamais : une notification qui échoue ne doit pas interrompre la
boucle de veille ni empêcher les incidents suivants d'être diffusés.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import (
    DASHBOARD_URL,
    NOC_EMAIL_RECIPIENTS,
    NOC_SMS_RECIPIENTS,
    NOTIFICATIONS_ENABLED,
    REPORT_ORGANISATION,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY_SECRET,
    TWILIO_API_KEY_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_CONTENT_SID,
    TWILIO_FROM_NUMBER,
)
from app.db.session import SessionLocal
from app.models.operations import NotificationLog

logger = logging.getLogger(__name__)


def _log_notification(incident_id: int, channel: str, status: str, detail: str = "") -> None:
    db = SessionLocal()
    try:
        db.add(
            NotificationLog(
                incident_id=incident_id, channel=channel, status=status, detail=detail[:500]
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("Journalisation de notification impossible : %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------
def _twilio_client():
    """Twilio accepte deux formes d'authentification.

    Soit le SID du compte + son jeton, soit une clé d'API (SK…) et son
    secret — mais même dans ce second cas le SID du compte (AC…) reste
    obligatoire, car c'est lui qui figure dans l'URL de la requête.
    """
    from twilio.rest import Client

    if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET:
        return Client(TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_ACCOUNT_SID)
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_sms(incident_id: int, body: str) -> None:
    if not (TWILIO_ACCOUNT_SID and TWILIO_FROM_NUMBER and NOC_SMS_RECIPIENTS):
        logger.info("SMS non configuré, envoi ignoré")
        return

    try:
        client = _twilio_client()
        for number in NOC_SMS_RECIPIENTS:
            kwargs = {"from_": TWILIO_FROM_NUMBER, "to": number}
            if TWILIO_CONTENT_SID:
                # Un compte d'essai Twilio refuse tout corps libre
                # (erreur 400/572006) et n'accepte que des modèles
                # prédéfinis : le modèle est donc requis tant que le
                # compte n'est pas passé en production.
                kwargs["content_sid"] = TWILIO_CONTENT_SID
                kwargs["content_variables"] = f'{{"1": "{body[:100]}"}}'
            else:
                kwargs["body"] = body[:320]
            client.messages.create(**kwargs)
        _log_notification(incident_id, "sms", "sent", f"{len(NOC_SMS_RECIPIENTS)} destinataire(s)")
    except Exception as exc:
        logger.error("Envoi SMS échoué pour l'incident #%s : %s", incident_id, exc)
        _log_notification(incident_id, "sms", "failed", str(exc))


# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
def send_email(incident_id: int, subject: str, html_body: str, text_body: str) -> None:
    if not (SMTP_HOST and NOC_EMAIL_RECIPIENTS):
        logger.info("E-mail non configuré, envoi ignoré")
        return

    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = SMTP_FROM
        message["To"] = ", ".join(NOC_EMAIL_RECIPIENTS)
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)

        _log_notification(
            incident_id, "email", "sent", f"{len(NOC_EMAIL_RECIPIENTS)} destinataire(s)"
        )
    except Exception as exc:
        logger.error("Envoi e-mail échoué pour l'incident #%s : %s", incident_id, exc)
        _log_notification(incident_id, "email", "failed", str(exc))


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def notify_critical_incident(
    *,
    incident_id: int,
    node_code: str,
    node_name: str,
    locality: str,
    severity: str,
    description: str | None,
) -> None:
    if not NOTIFICATIONS_ENABLED:
        return

    title = f"[NOC] Incident {severity.upper()} — {node_code}"
    detail = description or "Aucune description fournie par l'outil de supervision."
    link = f"{DASHBOARD_URL}/incidents/{incident_id}" if DASHBOARD_URL else ""

    text_body = (
        f"{title}\n\n"
        f"Équipement : {node_name} ({node_code})\n"
        f"Site       : {locality}\n"
        f"Gravité    : {severity}\n"
        f"Détail     : {detail}\n"
        + (f"\nOuvrir l'incident : {link}\n" if link else "")
        + f"\n— {REPORT_ORGANISATION}"
    )

    button = (
        f'<p><a href="{link}" style="background:#c0392b;color:#fff;padding:10px 18px;'
        f'text-decoration:none;border-radius:4px;">Ouvrir l\'incident</a></p>'
        if link
        else ""
    )
    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;">
      <h2 style="color:#c0392b;">{title}</h2>
      <table cellpadding="6" style="border-collapse:collapse;">
        <tr><td><b>Équipement</b></td><td>{node_name} ({node_code})</td></tr>
        <tr><td><b>Site</b></td><td>{locality}</td></tr>
        <tr><td><b>Gravité</b></td><td>{severity}</td></tr>
        <tr><td><b>Détail</b></td><td>{detail}</td></tr>
      </table>
      {button}
      <p style="color:#777;font-size:12px;">{REPORT_ORGANISATION}</p>
    </body></html>
    """

    send_sms(incident_id, f"{title} — {locality}. {detail[:120]}")
    send_email(incident_id, title, html_body, text_body)
