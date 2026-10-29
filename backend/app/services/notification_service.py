"""
Notifications sortantes sur alerte grave : SMS (Twilio) et courriel.

APPELANT : le canal temps réel (services/realtime_service.py), pour les
alertes que le collecteur découvre chez les outils. Ne lève jamais : une
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

UN ENVOI ÉCHOUÉ N'EST PAS PERDU. Le verrou ci-dessus est pris AVANT l'envoi :
sans autre mécanisme, un serveur SMTP indisponible pendant une panne
critique faisait que personne n'était jamais prévenu. L'envoi échoué est
donc rangé dans `ops_notification_retry` et retenté par `retry_loop`
(1, 5, 15, 30 puis 60 minutes), tant que l'alerte est active, dans la
limite de NOTIFY_RETRY_MAX_ATTEMPTS tentatives et de NOTIFY_RETRY_MAX_AGE_MIN
minutes. Un envoi abandonné est journalisé et signalé par /api/health.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.config import (
    DASHBOARD_URL,
    NOC_EMAIL_RECIPIENTS,
    NOC_SMS_RECIPIENTS,
    NOTIFICATIONS_ENABLED,
    NOTIFY_BURST_MAX,
    NOTIFY_RETRY_MAX_AGE_MIN,
    NOTIFY_RETRY_MAX_ATTEMPTS,
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
from app.models import AlertNotified, NotificationLog, NotificationRetry, User

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


def _one_line(value: str) -> str:
    """Texte ramené sur une ligne. Le nom d'un équipement vient d'un outil
    source, le titre d'un incident manuel d'un utilisateur : un saut de ligne
    dans l'objet d'un courriel en ferait échouer l'envoi — ou, avec une
    bibliothèque moins stricte, y injecterait des en-têtes."""
    return " ".join(str(value).split())


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


def _sms_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_FROM_NUMBER)


def _send_sms_to(numbers: list[str], body: str) -> dict[str, str]:
    """Envoie le SMS numéro par numéro ; rend {numéro: erreur} des échecs.

    Numéro par numéro : si la passerelle refuse le troisième, les deux
    premiers ont reçu le message et ne doivent pas le recevoir à nouveau
    lors de la prochaine tentative.
    """
    try:
        client = _twilio_client()
    except Exception as exc:  # noqa: BLE001 — bibliothèque absente ou mal configurée
        return {number: str(exc) for number in numbers}
    failures: dict[str, str] = {}
    for number in numbers:
        kwargs = {"from_": TWILIO_FROM_NUMBER, "to": number}
        if TWILIO_CONTENT_SID:
            # Un compte d'essai Twilio refuse tout corps libre
            # (erreur 400/572006) et n'accepte que des modèles
            # prédéfinis : le modèle est donc requis tant que le
            # compte n'est pas passé en production.
            kwargs["content_sid"] = TWILIO_CONTENT_SID
            # json.dumps et non une chaîne formatée : un guillemet dans
            # le message d'une sonde casserait le JSON, ou y ajouterait
            # des variables.
            kwargs["content_variables"] = json.dumps({"1": body[:100]}, ensure_ascii=False)
        else:
            kwargs["body"] = body[:320]
        try:
            client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            failures[number] = str(exc)
    return failures


def send_sms(alert_key: str, body: str) -> None:
    if not (_sms_configured() and NOC_SMS_RECIPIENTS):
        logger.info("SMS non configuré, envoi ignoré")
        return

    numbers = list(NOC_SMS_RECIPIENTS)
    failures = _send_sms_to(numbers, body)
    sent = [number for number in numbers if number not in failures]
    if sent:
        _log_notification(
            alert_key, "sms", "sent", f"{len(sent)} destinataire(s)", ", ".join(sent)
        )
    if failures:
        error = next(iter(failures.values()))
        logger.error("Envoi SMS échoué pour l'alerte %s : %s", alert_key, error)
        _log_notification(alert_key, "sms", "failed", error, ", ".join(failures))
        _schedule_retry(
            alert_key, "sms", text_body=body, recipients=list(failures), error=error
        )


# ---------------------------------------------------------------------------
# Courriel
# ---------------------------------------------------------------------------
def email_recipients(site: str | None = None) -> list[str]:
    """Destinataires effectifs : listes fixes + comptes actifs abonnés.

    Relu à chaque envoi, jamais mis en cache : un compte désactivé à 3 h 10
    ne doit pas recevoir l'alerte de 3 h 12.
    """
    addresses = list(NOC_EMAIL_RECIPIENTS)
    db = SessionLocal()
    try:
        site_filter = User.role.in_(("directeur", "chef_noc"))
        if site:
            site_filter = or_(site_filter, User.site == site)
        rows = db.query(User.email).filter(
            User.is_active.is_(True),
            User.notify_email.is_(True),
            User.email.isnot(None),
            site_filter,
        ).order_by(User.username).all()
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


def send_email(
    alert_key: str,
    subject: str,
    html_body: str,
    text_body: str,
    site: str | None = None,
) -> None:
    if not SMTP_HOST:
        logger.info("Courriel non configuré (SMTP_HOST vide), envoi ignoré")
        return
    recipients = email_recipients(site)
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
        _schedule_retry(
            alert_key, "email", subject=subject, text_body=text_body,
            html_body=html_body, site=site, error=str(exc),
        )


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
    title = _one_line(f"[NOC] Alerte {label.upper()} — {node_name}")
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
    send_email(alert_key, title, html_body, text_body, site=site)


def notify_burst(alerts: list[dict]) -> None:
    """Un seul message pour une rafale d'alertes graves.

    Chaque alerte est réservée comme pour un envoi unitaire
    (`ops_alert_notified`) : un second backend, ou un cycle suivant, ne la
    notifie pas une seconde fois. Seules celles que ce backend a réservées
    figurent dans le récapitulatif.
    """
    claimed = [
        alert for alert in alerts
        if _claim(f"{alert.get('tool')}:{alert.get('ref')}")
    ]
    if not claimed:
        return
    count = len(claimed)
    critical = sum(1 for alert in claimed if alert.get("severity") == "critical")
    title = _one_line(f"[NOC] {count} nouvelles alertes graves dont {critical} critiques")
    lines = [
        f"{_SEVERITY_LABEL.get(a.get('severity'), a.get('severity'))} — "
        f"{a.get('node_name') or 'équipement inconnu'} ({a.get('site') or 'site non renseigné'}) : "
        f"{_one_line(a.get('message') or '')[:120]}"
        for a in claimed[:50]
    ]
    if count > 50:
        lines.append(f"… et {count - 50} autre(s), voir le NOC.")
    link = f"{DASHBOARD_URL}/alertes" if DASHBOARD_URL else ""
    text_body = "\n".join(
        [title, "", *lines] + (["", f"Ouvrir le NOC : {link}"] if link else [])
        + ["", f"— {REPORT_ORGANISATION}"]
    )
    esc = html.escape
    html_body = (
        '<html><body style="font-family:Arial,sans-serif;color:#222;">'
        f'<h2 style="color:#c0392b;">{esc(title)}</h2><ul>'
        + "".join(f"<li>{esc(line)}</li>" for line in lines)
        + "</ul>"
        + (f'<p><a href="{esc(link, quote=True)}">Ouvrir le NOC</a></p>' if link else "")
        + f'<p style="color:#777;font-size:12px;">{esc(REPORT_ORGANISATION)}</p></body></html>'
    )
    key = f"digest:{_now().strftime('%Y%m%dT%H%M%S')}"
    send_sms(key, f"{title}. Voir le NOC.")
    send_email(key, title, html_body, text_body)


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
        if len(alerts) > NOTIFY_BURST_MAX:
            notify_burst(alerts)
            return
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


# ---------------------------------------------------------------------------
# Nouvelles tentatives
# ---------------------------------------------------------------------------
# Délai avant la tentative suivante, selon le nombre de tentatives déjà
# faites : 1 -> 1 min, 2 -> 5 min, … ; au-delà, toutes les heures.
RETRY_DELAYS_MIN = (1, 5, 15, 30, 60)
RETRY_INTERVAL_S = 60
_RETRY_BATCH = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite (tests) rend des dates sans fuseau ; PostgreSQL, en UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _delay(attempts: int) -> timedelta:
    return timedelta(minutes=RETRY_DELAYS_MIN[min(attempts, len(RETRY_DELAYS_MIN)) - 1])


def _schedule_retry(
    alert_key: str,
    channel: str,
    *,
    text_body: str,
    error: str,
    subject: str | None = None,
    html_body: str | None = None,
    site: str | None = None,
    recipients: list[str] | None = None,
) -> None:
    """Range un envoi échoué pour une nouvelle tentative. Ne lève jamais."""
    if NOTIFY_RETRY_MAX_ATTEMPTS <= 1:
        return
    db = SessionLocal()
    try:
        db.add(
            NotificationRetry(
                alert_key=alert_key,
                channel=channel,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                site=site,
                recipients=",".join(recipients) if recipients else None,
                attempts=1,
                status="pending",
                last_error=error[:500],
                next_attempt_at=_now() + _delay(1),
                created_at=_now(),
                updated_at=_now(),
            )
        )
        db.commit()
    except IntegrityError:
        # Déjà en attente pour cette alerte et ce canal.
        db.rollback()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error(
            "Nouvelle tentative non enregistrée pour %s (%s) : %s", alert_key, channel, exc
        )
    finally:
        db.close()


def _attempt(job: NotificationRetry) -> tuple[bool, str, list[str]]:
    """Une tentative : (réussi, erreur, destinataires restants).

    Destinataires restants : pour le SMS, les numéros encore en échec ;
    pour le courriel, vide (relus à chaque tentative)."""
    if job.channel == "email":
        if not SMTP_HOST:
            return False, "courriel désactivé (SMTP_HOST vide)", []
        recipients = email_recipients(job.site)
        if not recipients:
            return False, "aucun destinataire courriel", []
        try:
            _deliver(
                job.subject or "[NOC] Alerte", job.html_body or job.text_body,
                job.text_body, recipients,
            )
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), []
        _log_notification(
            job.alert_key, "email", "sent",
            f"{len(recipients)} destinataire(s), tentative {job.attempts + 1}",
            ", ".join(recipients),
        )
        return True, "", []

    numbers = [n for n in (job.recipients or "").split(",") if n]
    if not (_sms_configured() and numbers):
        return False, "SMS désactivé ou sans destinataire", []
    failures = _send_sms_to(numbers, job.text_body)
    sent = [number for number in numbers if number not in failures]
    if sent:
        _log_notification(
            job.alert_key, "sms", "sent",
            f"{len(sent)} destinataire(s), tentative {job.attempts + 1}", ", ".join(sent),
        )
    if failures:
        return False, next(iter(failures.values())), list(failures)
    return True, "", []


def retry_due(active_keys: set[str] | None = None, now: datetime | None = None) -> dict:
    """Retente les envois échus. Rend les comptes {sent, failed, abandoned}.

    `active_keys` : clés des alertes encore actives dans l'instantané ; une
    alerte close n'est plus notifiée. None quand l'instantané est illisible :
    on retente alors sans ce filtre plutôt que de tout abandonner.

    Chaque ligne est prise dans sa propre transaction, avec FOR UPDATE SKIP
    LOCKED : deux backends ne retentent jamais le même envoi, et un envoi
    lent ne bloque pas les autres backends.
    """
    now = now or _now()
    counts = {"sent": 0, "failed": 0, "abandoned": 0}
    for _ in range(_RETRY_BATCH):
        db = SessionLocal()
        try:
            job = (
                db.query(NotificationRetry)
                .filter(
                    NotificationRetry.status == "pending",
                    NotificationRetry.next_attempt_at <= now,
                )
                .order_by(NotificationRetry.next_attempt_at)
                .with_for_update(skip_locked=True)
                .first()
            )
            if job is None:
                return counts

            reason = None
            created = _aware(job.created_at) or now
            if now - created > timedelta(minutes=NOTIFY_RETRY_MAX_AGE_MIN):
                reason = f"alerte trop ancienne (plus de {NOTIFY_RETRY_MAX_AGE_MIN} min)"
            elif (
                active_keys is not None
                and not job.alert_key.startswith("digest:")
                and job.alert_key not in active_keys
            ):
                reason = "alerte close entre-temps"

            if reason is None:
                ok, error, remaining = _attempt(job)
                job.attempts += 1
                if ok:
                    job.status = "sent"
                    job.last_error = None
                    counts["sent"] += 1
                else:
                    job.last_error = error[:500]
                    if remaining:
                        job.recipients = ",".join(remaining)
                    if job.attempts >= NOTIFY_RETRY_MAX_ATTEMPTS:
                        reason = f"{job.attempts} tentatives échouées : {error}"
                    else:
                        job.next_attempt_at = now + _delay(job.attempts)
                        counts["failed"] += 1
                        _log_notification(
                            job.alert_key, job.channel, "failed",
                            f"tentative {job.attempts}/{NOTIFY_RETRY_MAX_ATTEMPTS} : {error}",
                        )
            if reason is not None:
                job.status = "abandoned"
                counts["abandoned"] += 1
                logger.error(
                    "Notification abandonnée pour %s (%s) : %s",
                    job.alert_key, job.channel, reason,
                )
                _log_notification(job.alert_key, job.channel, "abandoned", reason)
            job.updated_at = now
            db.commit()
        except Exception:  # noqa: BLE001 — une ligne en erreur ne bloque pas les autres
            db.rollback()
            logger.exception("Nouvelle tentative de notification en erreur")
            return counts
        finally:
            db.close()
    return counts


def retry_status(now: datetime | None = None) -> dict:
    """État des envois à retenter, pour /api/health et la supervision."""
    now = now or _now()
    db = SessionLocal()
    try:
        pending = db.query(func.count(NotificationRetry.id)).filter(
            NotificationRetry.status == "pending"
        ).scalar()
        abandoned = db.query(func.count(NotificationRetry.id)).filter(
            NotificationRetry.status == "abandoned",
            NotificationRetry.updated_at >= now - timedelta(hours=24),
        ).scalar()
        return {"pending": pending or 0, "abandoned_24h": abandoned or 0}
    finally:
        db.close()


async def retry_loop(stop: asyncio.Event) -> None:
    """Toutes les minutes, retente les envois échus.

    Les envois sont faits dans un THREAD, comme les premiers envois : SMTP
    et Twilio sont synchrones et bloqueraient la boucle asyncio.
    """
    from app.services import live_service

    while not stop.is_set():
        try:
            try:
                active = {f"{a['tool']}:{a['ref']}" for a in await live_service.get_alerts()}
            except live_service.SnapshotUnavailable:
                active = None
            counts = await asyncio.to_thread(retry_due, active)
            if any(counts.values()):
                logger.info(
                    "Notifications retentées : %d envoyée(s), %d en échec, %d abandonnée(s)",
                    counts["sent"], counts["failed"], counts["abandoned"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.exception("Boucle de nouvelles tentatives en erreur")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=RETRY_INTERVAL_S)
