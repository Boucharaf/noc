from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.constants import VAPID_PUBLIC_KEY
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notifications import PushSubscriptionPayload, VapidPublicKeyResponse
from app.services import push_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
def vapid_public_key():
    return VapidPublicKeyResponse(public_key=VAPID_PUBLIC_KEY)


@router.post("/subscribe", status_code=204)
def subscribe(
    payload: PushSubscriptionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    push_service.save_subscription(db, current_user.id, payload)


@router.delete("/subscribe", status_code=204)
def unsubscribe(
    payload: PushSubscriptionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    push_service.remove_subscription(db, payload.endpoint)
