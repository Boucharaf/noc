"""Abonnements aux notifications navigateur (Web Push)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import VAPID_PUBLIC_KEY
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.notifications import (
    PushSubscriptionPayload,
    PushUnsubscribePayload,
    VapidPublicKeyResponse,
)
from app.services import push_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


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
