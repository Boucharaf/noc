"""Authentification : connexion, PIN, rafraîchissement, déconnexion."""
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core import session_store
from app.core.config import JWT_EXPIRATION_MINUTES, REFRESH_COOKIE_SECURE
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.schemas.auth import (
    LoginPayload,
    PasswordChangePayload,
    PinLoginPayload,
    TokenResponse,
)
from app.schemas.users import UserOut, UserSelfUpdate
from app.services import auth_service, user_service

router = APIRouter(prefix="/api/auth", tags=["authentification"])

REFRESH_COOKIE_NAME = "noc_refresh"
# Chemin restreint : le navigateur n'envoie le cookie que sur les routes
# d'authentification, jamais sur le reste de l'API.
REFRESH_COOKIE_PATH = "/api/auth"

# Rôles autorisés à se connecter par PIN. Jamais Directeur ni Chef NOC :
# leurs comptes portent bien plus de privilèges et doivent rester sur un
# facteur fort. Le PIN est un confort pour la relève d'équipe sur une
# console partagée — voir auth_service.hash_pin.
PIN_LOGIN_ALLOWED_ROLES = {"agent_terrain"}


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "unknown"
    )


def _set_refresh_cookie(response: Response, token: str, expire_at: datetime) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=int((expire_at - datetime.now(UTC)).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _issue_session(db: Session, user: User, response: Response) -> TokenResponse:
    access_token = auth_service.create_access_token(user)
    refresh_token, jti, expire_at = auth_service.create_refresh_token(user)
    session_store.store_refresh_session(user.id, jti, expire_at)
    _set_refresh_cookie(response, refresh_token, expire_at)
    return TokenResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_MINUTES * 60,
        user=UserOut(**user_service.get_user(db, user.id)),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)):
    user = auth_service.authenticate_with_password(db, payload.username, payload.password)
    return _issue_session(db, user, response)


@router.post("/pin-login", response_model=TokenResponse)
def pin_login(
    payload: PinLoginPayload,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    locked_ttl = session_store.is_pin_locked(ip)
    if locked_ttl is not None:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            detail={
                "message": "Trop de tentatives — réessayez plus tard.",
                "retry_after_seconds": locked_ttl,
            },
        )

    try:
        user = auth_service.authenticate_with_pin(db, payload.pin)
    except HTTPException:
        session_store.register_pin_failure(ip)
        raise

    if user.role not in PIN_LOGIN_ALLOWED_ROLES:
        # Même erreur générique qu'un PIN invalide : révéler que le compte
        # existe mais n'a pas le droit d'utiliser ce mode renseignerait un
        # attaquant sur la validité du PIN saisi.
        session_store.register_pin_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code PIN invalide.")

    session_store.clear_pin_failures(ip)
    return _issue_session(db, user, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    noc_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if not noc_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Aucune session à rafraîchir.")

    try:
        payload = auth_service.decode_refresh_token(noc_refresh)
    except HTTPException:
        _clear_refresh_cookie(response)
        raise

    user_id, jti = int(payload["sub"]), payload["jti"]

    if not session_store.is_refresh_session_valid(jti, user_id):
        # Signature valide mais jti absent du registre : soit il a déjà
        # été consommé par une rotation (réutilisation = vol probable),
        # soit il a été révoqué. Dans les deux cas, on tue TOUTES les
        # sessions du compte, pas seulement celle-ci.
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou déjà utilisée.")

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")

    new_token, new_jti, new_expire = auth_service.create_refresh_token(user)
    session_store.rotate_refresh_session(jti, user_id, new_jti, new_expire)
    _set_refresh_cookie(response, new_token, new_expire)

    return TokenResponse(
        access_token=auth_service.create_access_token(user),
        expires_in=JWT_EXPIRATION_MINUTES * 60,
        user=UserOut(**user_service.get_user(db, user.id)),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    noc_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if noc_refresh:
        try:
            payload = auth_service.decode_refresh_token(noc_refresh)
            session_store.revoke_refresh_session(payload["jti"], int(payload["sub"]))
        except HTTPException:
            pass  # cookie déjà invalide : rien à révoquer, on nettoie côté navigateur
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return UserOut(**user_service.get_user(db, current_user.id))


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserSelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mise à jour de ses propres identifiants — ouverte à tous les rôles.

    Identifiant, nom, téléphone, adresse et abonnement aux alertes. Le rôle
    n'est pas modifiable ici (le schéma refuse le champ) : seul un Chef NOC
    l'attribue, depuis la gestion des comptes.
    """
    return UserOut(
        **user_service.update_self(db, current_user, payload.model_dump(exclude_unset=True))
    )


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    payload: PasswordChangePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    auth_service.authenticate_with_password(
        db, current_user.username, payload.current_password
    )
    auth_service.set_password(db, current_user.id, payload.new_password)
    # Changer son mot de passe invalide les autres sessions : c'est le
    # geste attendu quand on soupçonne une compromission.
    session_store.revoke_all_sessions(current_user.id)


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: int,
    _admin: User = Depends(require_role("chef_noc")),
):
    session_store.revoke_all_sessions(user_id)
