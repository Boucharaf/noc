"""Notifications : abonnements navigateur (Web Push) et chaîne courriel."""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import SMTP_HOST, VAPID_PUBLIC_KEY
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.schemas.notifications import (
    PushSubscriptionPayload,
    PushUnsubscribePayload,
    VapidPublicKeyResponse,
)
from app.services import notification_service, push_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class TestEmailPayload(BaseModel):
    # Au plus dix adresses : un test n'est pas un publipostage.
    to: list[Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]] | None = Field(
        default=None, max_length=10
    )


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
def get_vapid_public_key(_user: User = Depends(get_current_user)):
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="Notifications navigateur non configurées (VAPID absent).",
        )
    return VapidPublicKeyResponse(public_key=VAPID_PUBLIC_KEY)


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    payload: PushSubscriptionPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    push_service.save_subscription(
        db, user.id, payload.endpoint, payload.keys.p256dh, payload.keys.auth
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    payload: PushUnsubscribePayload,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    push_service.remove_subscription(db, payload.endpoint)


@router.get("/email/status")
def email_status(_admin: User = Depends(require_role("chef_noc"))):
    """Configuration SMTP et destinataires effectifs des alertes."""
    return notification_service.email_status()


@router.post("/email/test")
def send_test_email(
    payload: TestEmailPayload = Body(default_factory=TestEmailPayload),
    admin: User = Depends(require_role("chef_noc")),
):
    """Envoie un courriel de vérification.

    Indépendant de NOTIFICATIONS_ENABLED, délibérément : c'est ce qui permet
    de valider la configuration SMTP AVANT d'activer les alertes, plutôt que
    de découvrir un mot de passe erroné le jour d'une vraie panne.
    """
    if not SMTP_HOST:
        raise HTTPException(503, "Serveur SMTP non configuré (SMTP_HOST vide).")
    recipients = payload.to or notification_service.email_recipients()
    if not recipients:
        raise HTTPException(
            422,
            "Aucun destinataire : abonnez au moins un compte aux alertes par "
            "courriel, ou renseignez NOC_EMAIL_RECIPIENTS.",
        )
    try:
        notification_service.send_test_email(
            recipients, requested_by=admin.full_name or admin.username
        )
    except Exception as exc:  # noqa: BLE001 — le message SMTP est rendu tel quel
        raise HTTPException(502, f"Échec de l'envoi : {exc}") from exc
    return {"sent_to": recipients}
