"""
Notifications sortantes sur alerte grave : SMS (Twilio) et courriel.

DEUX APPELANTS : le canal temps réel (services/realtime_service.py) pour les
alertes que le collecteur découvre chez les outils, et la création d'un
incident signalé à la main (routes/operations.py). Ne lève jamais : une
notification qui échoue ne doit interrompre ni la diffusion WebSocket ni les
alertes suivantes — l'alerte est de toute façon déjà visible à l'écran.

DESTINATAIRES DU COURRIEL, deux sources additionnées :
  * NOC_EMAIL_RECIPIENTS — listes de diffusion fixes (astreinte, direction
    technique), qui ne correspondent à aucun compte ;
  * les comptes ACTIFS abonnés depuis l'interface (`noc_user.notify_email`).
    C'est ce qui permet au Chef NOC d'ajouter ou de retirer un destinataire
    sans toucher à la configuration ni redéployer.

L'ANTI-DOUBLON EST UNE CONTRAINTE DE BASE, pas un verrou applicatif. Deux
backends derrière un répartiteur reçoivent tous deux la publication Redis ;
c'est l'insertion dans `ops_alert_notified` qui départage, et le perdant
n'envoie rien. Un verrou en mémoire ne survivrait pas à un redémarrage et
laisserait repartir toutes les notifications.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import (
    DASHBOARD_URL,
    NOC_EMAIL_RECIPIENTS,
    NOC_SMS_RECIPIENTS,
    NOTIFICATIONS_ENABLED,
    NOTIFY_SEVERITIES,
    REPORT_ORGANISATION,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USER,
    SMTP_VERIFY_SSL,
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY_SECRET,
    TWILIO_API_KEY_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_CONTENT_SID,
    TWILIO_FROM_NUMBER,
)
from app.db.session import SessionLocal
from app.models import AlertNotified, NotificationLog, User

logger = logging.getLogger(__name__)

# Libellés alignés sur frontend/src/lib/vocabulary.js : le courriel et
# l'écran doivent nommer une même gravité de la même façon.
_SEVERITY_LABEL = {
    "critical": "Critique",
    "high": "Majeur",
    "medium": "Moyen",
    "low": "Mineur",
    "info": "Information",
    "unknown": "Inconnu",
}


def _log_notification(
    alert_key: str,
    channel: str,
    status: str,
    detail: str = "",
    recipient: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            NotificationLog(
                alert_key=alert_key,
                channel=channel,
                recipient=recipient[:1000] if recipient else None,
                status=status,
                error=detail[:500],
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


def send_sms(alert_key: str, body: str) -> None:
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
        _log_notification(
            alert_key, "sms", "sent", f"{len(NOC_SMS_RECIPIENTS)} destinataire(s)",
            ", ".join(NOC_SMS_RECIPIENTS),
        )
    except Exception as exc:
        logger.error("Envoi SMS échoué pour l'alerte %s : %s", alert_key, exc)
        _log_notification(alert_key, "sms", "failed", str(exc))


# ---------------------------------------------------------------------------
# Courriel
# ---------------------------------------------------------------------------
def email_recipients() -> list[str]:
    """Destinataires effectifs : listes fixes + comptes actifs abonnés.

    Relu à chaque envoi, jamais mis en cache : un compte désactivé à 3 h 10
    ne doit pas recevoir l'alerte de 3 h 12.
    """
    addresses = list(NOC_EMAIL_RECIPIENTS)
    db = SessionLocal()
    try:
        rows = (
            db.query(User.email)
            .filter(
                User.is_active.is_(True),
                User.notify_email.is_(True),
                User.email.isnot(None),
            )
            .order_by(User.username)
            .all()
        )
        addresses.extend(email for (email,) in rows if email)
    except Exception as exc:  # noqa: BLE001
        # Base injoignable : prévenir au moins les listes fixes vaut mieux
        # que ne prévenir personne.
        logger.warning("Abonnés courriel illisibles, envoi aux seules listes fixes : %s", exc)
    finally:
        db.close()

    # Dédoublonnage insensible à la casse : une même boîte inscrite à la
    # fois dans la liste fixe et sur un compte ne reçoit qu'un exemplaire.
    seen: set[str] = set()
    unique: list[str] = []
    for address in addresses:
        normalised = address.strip().lower()
        if normalised and normalised not in seen:
            seen.add(normalised)
            unique.append(address.strip())
    return unique


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not SMTP_VERIFY_SSL:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _deliver(subject: str, html_body: str, text_body: str, recipients: list[str]) -> None:
    """Envoi SMTP. LÈVE en cas d'échec : c'est l'appelant qui décide s'il
    journalise (alerte) ou rend l'erreur à l'écran (courriel de test)."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10, context=_tls_context())
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    with server:
        if SMTP_USE_TLS and not SMTP_USE_SSL:
            server.starttls(context=_tls_context())
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)


def send_email(alert_key: str, subject: str, html_body: str, text_body: str) -> None:
    if not SMTP_HOST:
        logger.info("Courriel non configuré (SMTP_HOST vide), envoi ignoré")
        return
    recipients = email_recipients()
    if not recipients:
        logger.info(
            "Aucun destinataire courriel (ni NOC_EMAIL_RECIPIENTS ni compte abonné), "
            "envoi ignoré"
        )
        return

    try:
        _deliver(subject, html_body, text_body, recipients)
        _log_notification(
            alert_key, "email", "sent", f"{len(recipients)} destinataire(s)",
            ", ".join(recipients),
        )
    except Exception as exc:
        logger.error("Envoi courriel échoué pour l'alerte %s : %s", alert_key, exc)
        _log_notification(alert_key, "email", "failed", str(exc), ", ".join(recipients))


def send_test_email(recipients: list[str], requested_by: str) -> None:
    """Courriel de vérification demandé par le Chef NOC.

    LÈVE en cas d'échec : le message du serveur SMTP (authentification
    refusée, relais interdit, certificat invalide) est exactement ce que
    l'exploitant doit lire pour corriger la configuration.
    """
    subject = f"[NOC] Courriel de test — {REPORT_ORGANISATION}"
    security = "SMTPS" if SMTP_USE_SSL else ("STARTTLS" if SMTP_USE_TLS else "sans chiffrement")
    automatic = (
        "activées" if NOTIFICATIONS_ENABLED else "DÉSACTIVÉES (NOTIFICATIONS_ENABLED=false)"
    )
    lines = [
        "Ce courriel confirme que la plateforme NOC sait envoyer ses alertes.",
        "",
        f"Demandé par : {requested_by}",
        f"Serveur     : {SMTP_HOST}:{SMTP_PORT} ({security})",
        f"Gravités    : {', '.join(_SEVERITY_LABEL.get(s, s) for s in NOTIFY_SEVERITIES)}",
        f"Alertes     : {automatic}",
        "",
        f"— {REPORT_ORGANISATION}",
    ]
    text_body = "\n".join(lines)
    html_body = (
        '<html><body style="font-family:Arial,sans-serif;color:#222;">'
        + "".join(f"<p>{html.escape(line)}</p>" if line else "" for line in lines)
        + "</body></html>"
    )
    try:
        _deliver(subject, html_body, text_body, recipients)
    except Exception as exc:
        _log_notification("test", "email", "failed", str(exc), ", ".join(recipients))
        raise
    _log_notification("test", "email", "sent", f"test par {requested_by}", ", ".join(recipients))


def email_status() -> dict:
    """État de la chaîne courriel, pour l'écran de gestion des comptes."""
    return {
        "notifications_enabled": NOTIFICATIONS_ENABLED,
        "smtp_configured": bool(SMTP_HOST),
        "smtp_host": SMTP_HOST or None,
        "smtp_port": SMTP_PORT,
        "security": "ssl" if SMTP_USE_SSL else ("starttls" if SMTP_USE_TLS else "none"),
        "sender": SMTP_FROM,
        "severities": list(NOTIFY_SEVERITIES),
        "fixed_recipients": list(NOC_EMAIL_RECIPIENTS),
        "recipients": email_recipients(),
    }


# ---------------------------------------------------------------------------
# Points d'entrée
# ---------------------------------------------------------------------------
def _claim(alert_key: str) -> bool:
    """Réserve l'envoi pour cette alerte. False si quelqu'un l'a déjà prise.

    La clé primaire de `ops_alert_notified` EST le verrou : deux backends qui
    traiteraient la même publication au même instant, l'un des deux verra son
    insertion refusée et n'enverra rien. Plus sûr qu'un verrou en mémoire, qui
    ne survit pas à un redémarrage et laisserait tout repartir.
    """
    db = SessionLocal()
    try:
        db.add(AlertNotified(alert_key=alert_key))
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def notify_alert(
    *,
    alert_key: str,
    node_name: str,
    site: str | None,
    severity: str,
    message: str | None,
    source: str | None = None,
) -> None:
    """Envoie SMS et courriel pour une alerte. Idempotent."""
    if not NOTIFICATIONS_ENABLED:
        return
    if not _claim(alert_key):
        logger.debug("Alerte %s déjà notifiée — envoi ignoré", alert_key)
        return

    label = _SEVERITY_LABEL.get(severity, severity)
    title = f"[NOC] Alerte {label.upper()} — {node_name}"
    detail = message or "Aucun détail fourni par l'outil de supervision."
    location = site or "site non renseigné"
    # La page des incidents, et non une fiche : une clé d'alerte n'est pas
    # encore adressable directement par URL côté interface.
    link = f"{DASHBOARD_URL}/incidents" if DASHBOARD_URL else ""

    rows = [("Équipement", node_name), ("Site", location), ("Gravité", label)]
    if source:
        rows.append(("Source", source))
    rows.append(("Détail", detail))

    text_lines = [title, ""] + [f"{name:<11}: {value}" for name, value in rows]
    if link:
        text_lines += ["", f"Ouvrir le NOC : {link}"]
    text_lines += ["", f"— {REPORT_ORGANISATION}"]
    text_body = "\n".join(text_lines)

    # Tout ce qui vient d'un outil source est ÉCHAPPÉ avant d'entrer dans le
    # HTML. Un message de sonde contient couramment des chevrons, qui
    # casseraient la mise en page — et un outil compromis pourrait sinon
    # injecter du contenu dans les boîtes de toute l'équipe.
    esc = html.escape
    table_rows = "".join(
        f"<tr><td><b>{esc(name)}</b></td><td>{esc(value)}</td></tr>" for name, value in rows
    )
    button = (
        f'<p><a href="{esc(link, quote=True)}" style="background:#c0392b;color:#fff;'
        f'padding:10px 18px;text-decoration:none;border-radius:4px;">Ouvrir le NOC</a></p>'
        if link
        else ""
    )
    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;">
      <h2 style="color:#c0392b;">{esc(title)}</h2>
      <table cellpadding="6" style="border-collapse:collapse;">{table_rows}</table>
      {button}
      <p style="color:#777;font-size:12px;">{esc(REPORT_ORGANISATION)}</p>
    </body></html>
    """

    send_sms(alert_key, f"{title} — {location}. {detail[:120]}")
    send_email(alert_key, title, html_body, text_body)


def notify_manual_incident(
    *,
    incident_id: int,
    title: str,
    severity: str,
    description: str | None,
    node_name: str | None,
    site: str | None,
    reported_by: str,
) -> None:
    """Incident signalé à la main : même chemin qu'une alerte d'outil.

    Exécuté en tâche de fond, après la réponse HTTP : l'agent qui signale une
    panne depuis son téléphone n'a pas à attendre le serveur SMTP.
    """
    if severity not in NOTIFY_SEVERITIES:
        return
    try:
        notify_alert(
            alert_key=f"manual:{incident_id}",
            node_name=node_name or site or "Incident signalé",
            site=site,
            severity=severity,
            message=f"{title} — {description}" if description else title,
            source=f"signalement manuel par {reported_by}",
        )
    except Exception:  # noqa: BLE001 — voir l'en-tête : ne lève jamais.
        logger.exception("Notification de l'incident manuel %s en échec", incident_id)


async def notify_new_alerts(alerts: list[dict]) -> None:
    """Point d'entrée appelé par le canal temps réel.

    Les envois sont faits dans un THREAD : Twilio et smtplib sont des
    bibliothèques synchrones, et les appeler directement dans la boucle
    asyncio bloquerait la diffusion WebSocket de toutes les autres alertes
    pendant la durée de l'envoi — plusieurs secondes si la passerelle SMS
    est lente.
    """
    if not NOTIFICATIONS_ENABLED or not alerts:
        return

    import asyncio

    def _send_all() -> None:
        for alert in alerts:
            try:
                notify_alert(
                    alert_key=f"{alert.get('tool')}:{alert.get('ref')}",
                    node_name=alert.get("node_name") or "équipement inconnu",
                    site=alert.get("site"),
                    severity=alert.get("severity", "unknown"),
                    message=alert.get("message"),
                    source=alert.get("tool"),
                )
            except Exception:  # noqa: BLE001 — une alerte qui échoue ne doit
                # pas empêcher les suivantes d'être notifiées.
                logger.exception("Notification en échec pour %s", alert.get("ref"))

    await asyncio.to_thread(_send_all)
