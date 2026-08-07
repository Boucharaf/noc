"""
Notifications on critical incidents: SMS to the NOC lead via Twilio, plus the
permanence email over SMTP.

Only severity "critical" notifies. That threshold is the whole point of the
feature — it exists to reach someone who is not looking at the dashboard, and
a channel that fires on lesser severities gets muted by its recipients, after
which it reaches nobody at all.

Both channels degrade gracefully: if credentials are missing or the provider is
unreachable, the failure is logged and ingestion continues — an alerting outage
must never block the incident pipeline.
"""

import json
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from app.core.constants import (
    DASHBOARD_URL,
    NOC_EMAIL_RECIPIENTS,
    NOC_SMS_RECIPIENTS,
    NOTIFICATIONS_ENABLED,
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

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@lru_cache(maxsize=1)
def _templates() -> Environment:
    """Autoescaping matters here: node names and descriptions come straight from
    Zabbix/iTop and must never be able to inject markup into an alert mail."""
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


# Alerting must never stall ingestion, so the SDK gets an explicit request
# timeout instead of its default (none).
TWILIO_TIMEOUT_S = 10
# How many {{n}} slots to fill in the content template. Twilio's predefined
# trial templates have a handful; filling the unused ones with "" keeps the
# placeholder from being sent literally.
TWILIO_CONTENT_VARIABLE_SLOTS = 5
# One SMS segment is 160 GSM-7 characters; alerts get truncated rather than
# silently billed as three parts.
SMS_VARIABLE_MAX_CHARS = 300


def _twilio_client() -> Client:
    """Built per call, so a credential change is picked up without a restart.

    With an API key the SK/secret pair authenticates the request but the URL
    still has to name the account (`/Accounts/{AC…}/Messages.json`), so the
    account SID is passed separately — putting the SK there instead is what
    Twilio rejects with 401 / error 20003 "Policy evaluation failed".
    """
    if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET:
        username, password = TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET
    else:
        username, password = TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
    return Client(
        username,
        password,
        account_sid=TWILIO_ACCOUNT_SID,
        http_client=TwilioHttpClient(timeout=TWILIO_TIMEOUT_S),
    )


def _sms_configured() -> bool:
    has_credentials = bool(TWILIO_AUTH_TOKEN) or bool(
        TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET
    )
    if not (TWILIO_ACCOUNT_SID and has_credentials and TWILIO_FROM_NUMBER and NOC_SMS_RECIPIENTS):
        return False
    # An API key SID in the account slot authenticates but addresses no account,
    # so every send would 401. Say so plainly instead of letting Twilio do it.
    if not TWILIO_ACCOUNT_SID.startswith("AC"):
        logger.error(
            "TWILIO_ACCOUNT_SID is %s…, not an account SID: it must be the AC… "
            "value from the Twilio console. An API key belongs in "
            "TWILIO_API_KEY_SID / TWILIO_API_KEY_SECRET.",
            TWILIO_ACCOUNT_SID[:2],
        )
        return False
    # Trial accounts can only send predefined content templates; without one
    # every send would come back 400/572006. Drop the "and TWILIO_CONTENT_SID"
    # part of this check once the account is upgraded and send_sms goes back to
    # free-form bodies.
    if not TWILIO_CONTENT_SID:
        logger.error(
            "TWILIO_CONTENT_SID is not set: a trial Twilio account can only send "
            "predefined templates. Copy the template SID (HX…) from Twilio "
            "console → Messaging → Content Template Builder."
        )
        return False
    return True


def _email_configured() -> bool:
    return bool(SMTP_HOST and NOC_EMAIL_RECIPIENTS)


def _content_variables(body: str) -> str:
    """Positional substitutions for the content template, as Twilio wants them:
    a JSON object keyed "1", "2", … matching the template's {{1}}, {{2}} slots.

    The alert text goes in {{1}}; templates with more slots get the remaining
    ones filled with empty strings rather than rendering "{{2}}" literally.
    """
    variables = {"1": body[:SMS_VARIABLE_MAX_CHARS]}
    variables.update({str(i): "" for i in range(2, TWILIO_CONTENT_VARIABLE_SLOTS + 1)})
    return json.dumps(variables)


def send_sms(body: str) -> int:
    """Send `body` to every configured NOC number. Returns the count sent.

    The trial account this runs against refuses free-form bodies (400/572006,
    "Trial accounts can only use predefined SMS templates"), so the text is
    passed as the variable of an approved content template instead. Once the
    Twilio account is upgraded, swap the two calls below back over: free-form
    is what the alert text is actually written for.
    """
    if not _sms_configured():
        logger.info("SMS not configured, skipping notification")
        return 0
    client = _twilio_client()
    sent = 0
    for number in NOC_SMS_RECIPIENTS:
        try:
            # Free-form body — the real thing, kept for the day the account is
            # upgraded. Uncomment this and drop the content-template call below;
            # TWILIO_CONTENT_SID then becomes unnecessary (also remove its check
            # in _sms_configured).
            # client.messages.create(from_=TWILIO_FROM_NUMBER, to=number, body=body)
            client.messages.create(
                from_=TWILIO_FROM_NUMBER,
                to=number,
                content_sid=TWILIO_CONTENT_SID,
                content_variables=_content_variables(body),
            )
            sent += 1
        # The SDK raises TwilioRestException for anything the API rejects, but
        # transport failures come straight from requests underneath it.
        except (TwilioException, requests.RequestException) as exc:
            logger.error("SMS to %s failed: %s", number, exc)
    return sent


def send_email(subject: str, body: str, html: str | None = None) -> int:
    """Send an email to the NOC permanence list. Returns the count sent.

    `body` is the plain-text part and is mandatory: it is what text-only
    clients, and most phone notification previews, actually show. `html`, when
    given, is attached as the richer alternative.
    """
    if not _email_configured():
        logger.info("SMTP not configured, skipping notification")
        return 0
    if html:
        msg = MIMEMultipart("alternative")
        # Last part wins in multipart/alternative, so the HTML goes second.
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(NOC_EMAIL_RECIPIENTS)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_FROM, NOC_EMAIL_RECIPIENTS, msg.as_string())
        return len(NOC_EMAIL_RECIPIENTS)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Email notification failed: %s", exc)
        return 0


# Same severity palette as the dashboard (frontend/src/theme/colors.js), so an
# alert mail and the screen it points at agree on what "critique" looks like.
SEVERITY_COLOR = {
    "critical": "#d03b3b",
    "high": "#ec835a",
    "medium": "#fab219",
    "low": "#0ca30c",
}
SEVERITY_LABEL = {
    "critical": "Critique",
    "high": "Élevée",
    "medium": "Moyenne",
    "low": "Faible",
}


def _format_datetime(value: str) -> str:
    """ISO timestamp → "17/05/2026 à 03h22". Falls back to the raw string."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
            "%d/%m/%Y à %Hh%M"
        )
    except (ValueError, AttributeError):
        return value


def _incident_email_html(
    incident_id: int,
    node_code: str,
    node_name: str,
    severity: str,
    detected_at: str,
    description: str | None,
    itop_ticket_id: str | None,
) -> str:
    """Render templates/incident_alert.html for one incident."""
    severity_label = SEVERITY_LABEL.get(severity, severity)
    return _templates().get_template("incident_alert.html").render(
        accent=SEVERITY_COLOR.get(severity, SEVERITY_COLOR["critical"]),
        severity_label=severity_label,
        node_code=node_code,
        node_name=node_name,
        detected_at=_format_datetime(detected_at),
        description=description,
        dashboard_url=DASHBOARD_URL,
        rows=[
            ("Nœud", f"{node_code} — {node_name}"),
            ("Sévérité", severity_label),
            ("Détecté le", _format_datetime(detected_at)),
            ("Ticket iTop", itop_ticket_id or "—"),
            ("Référence", f"#{incident_id}"),
        ],
    )


def notify_critical_incident(
    incident_id: int,
    node_code: str,
    node_name: str,
    severity: str,
    detected_at: str,
    description: str | None,
    itop_ticket_id: str | None,
) -> None:
    """Fire SMS + email for a critical incident. Never raises."""
    if not NOTIFICATIONS_ENABLED:
        return
    try:
        summary = (
            f"[NOC ALERTE {severity.upper()}] {node_code} {node_name} — "
            f"{description or 'incident détecté'} ({detected_at})"
        )
        if itop_ticket_id:
            summary += f" | Ticket {itop_ticket_id}"

        sms_sent = send_sms(summary)
        email_sent = send_email(
            subject=f"[NOC] Incident critique #{incident_id} — {node_code}",
            body=(
                f"Incident critique détecté par la supervision.\n\n"
                f"Nœud       : {node_code} — {node_name}\n"
                f"Sévérité   : {SEVERITY_LABEL.get(severity, severity)}\n"
                f"Détecté le : {_format_datetime(detected_at)}\n"
                f"Ticket iTop: {itop_ticket_id or 'N/A'}\n"
                f"Référence  : #{incident_id}\n\n"
                f"Description:\n{description or '—'}\n"
                + (f"\nDashboard: {DASHBOARD_URL}/global\n" if DASHBOARD_URL else "")
                + f"\n— NOC Dashboard ANPTIC (message automatique)"
            ),
            html=_incident_email_html(
                incident_id,
                node_code,
                node_name,
                severity,
                detected_at,
                description,
                itop_ticket_id,
            ),
        )
        logger.info(
            "Critical incident #%s notified (sms=%d, email=%d)",
            incident_id,
            sms_sent,
            email_sent,
        )
    except Exception as exc:  # notification failure must never break ingestion
        logger.exception("Notification for incident #%s failed: %s", incident_id, exc)
