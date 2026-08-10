from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.constants import JWT_EXPIRATION_MINUTES
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginPayload, PinLoginPayload, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=auth_service.create_access_token(user),
        expires_in=JWT_EXPIRATION_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = auth_service.authenticate_with_password(db, payload.username, payload.password)
    return _token_response(user)


@router.post("/pin-login", response_model=TokenResponse)
def pin_login(payload: PinLoginPayload, db: Session = Depends(get_db)):
    user = auth_service.authenticate_with_pin(db, payload.pin)
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(current_user: User = Depends(get_current_user)):
    """Exchange a still-valid token for a fresh one.

    Makes the session sliding rather than fixed: it stays alive while somebody
    is using the dashboard, and still lapses JWT_EXPIRATION_MINUTES after the
    last activity. The alternative — simply raising the lifetime — buys the
    same convenience by leaving a long-lived bearer token in localStorage,
    which is the thing actually worth avoiding.

    Deliberately not a refresh *token*: this renews from the access token
    itself, so an expired session cannot be revived and the user logs in
    again. That is the intended end state for a console left unattended.
    """
    return _token_response(current_user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
