"""
Browser/PWA Web Push notifications on critical incidents.

Runs as a FastAPI background task (see routes/incidents.py), so it opens its
own DB session rather than reusing the request-scoped one, which is already
closed by the time the task runs. Degrades gracefully like notification_service:
VAPID not configured, no subscriptions, or a delivery failure must never break
incident ingestion. A 404/410 response means the browser dropped the
subscription (uninstalled, permission revoked) — prune it so we stop retrying.
"""

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from app.core.constants import VAPID_CLAIMS_EMAIL, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
from app.db.session import SessionLocal
from app.models.push_subscription import PushSubscription
from app.schemas.notifications import PushSubscriptionPayload

logger = logging.getLogger(__name__)


def _vapid_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def save_subscription(db: Session, user_id: int, payload: PushSubscriptionPayload) -> PushSubscription:
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=payload.endpoint, user_id=user_id)
        db.add(sub)
    sub.user_id = user_id
    sub.p256dh = payload.keys.p256dh
    sub.auth = payload.keys.auth
    db.commit()
    db.refresh(sub)
    return sub


def remove_subscription(db: Session, endpoint: str) -> None:
    db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).delete()
    db.commit()


def _send_one(db: Session, sub: PushSubscription, title: str, body: str) -> None:
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            timeout=5,
        )
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            logger.info("Pruning expired push subscription id=%s", sub.id)
            db.delete(sub)
            db.commit()
        else:
            logger.error("Push delivery failed for subscription id=%s: %s", sub.id, exc)


def notify_critical_incident_push(
    incident_id: int, node_code: str, node_name: str, severity: str, description: str | None
) -> None:
    """Push a browser notification to every subscribed device. Never raises."""
    if not _vapid_configured():
        logger.info("VAPID not configured, skipping push notification")
        return
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).all()
        if not subs:
            return
        title = f"[NOC] Incident {severity.upper()} — {node_code}"
        body = description or f"Incident détecté sur {node_name}"
        for sub in subs:
            _send_one(db, sub, title, body)
        logger.info("Critical incident #%s pushed to %d subscription(s)", incident_id, len(subs))
    except Exception as exc:  # push failures must never break ingestion
        logger.exception("Push notification for incident #%s failed: %s", incident_id, exc)
    finally:
        db.close()
