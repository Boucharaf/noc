"""
Notifications Web Push (navigateur / PWA).

Ouvre sa propre session : appelé depuis le veilleur, hors du cycle de vie
d'une requête HTTP. Une réponse 404 ou 410 signifie que le navigateur a
abandonné l'abonnement (application désinstallée, permission retirée) —
on le purge alors pour cesser de réessayer indéfiniment.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.config import VAPID_CLAIMS_EMAIL, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
from app.db.session import SessionLocal
from app.models.operations import PushSubscription

logger = logging.getLogger(__name__)


def vapid_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def save_subscription(db: Session, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    subscription = (
        db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    )
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint, user_id=user_id)
        db.add(subscription)
    subscription.user_id = user_id
    subscription.p256dh = p256dh
    subscription.auth = auth
    db.commit()


def remove_subscription(db: Session, endpoint: str, user_id: int) -> None:
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id
    ).delete()
    db.commit()


def _send_one(db: Session, subscription: PushSubscription, title: str, body: str) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            timeout=5,
        )
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            logger.info("Abonnement push expiré, purge de l'id=%s", subscription.id)
            db.delete(subscription)
            db.commit()
        else:
            logger.error("Push échoué pour l'abonnement id=%s : %s", subscription.id, exc)


def notify_critical_incident_push(
    *, incident_id: int, node_code: str, node_name: str, severity: str, description: str | None
) -> None:
    if not vapid_configured():
        logger.info("VAPID non configuré, push ignoré")
        return

    db = SessionLocal()
    try:
        subscriptions = db.query(PushSubscription).all()
        if not subscriptions:
            return
        title = f"[NOC] Incident {severity.upper()} — {node_code}"
        body = description or f"Incident détecté sur {node_name}"
        for subscription in subscriptions:
            _send_one(db, subscription, title, body)
        logger.info("Incident #%s poussé vers %d abonnement(s)", incident_id, len(subscriptions))
    except Exception as exc:
        logger.exception("Push de l'incident #%s en échec : %s", incident_id, exc)
    finally:
        db.close()
