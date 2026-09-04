# app/routes/auth.py
#
# Corrigé : la version précédente de ce fichier importait des modules
# inexistants dans ce projet (core.database, core.security sans préfixe
# app., dependencies.auth sans préfixe app., models.user.DimUser — la classe
# s'appelle User —, schemas.auth.LoginRequest/PinLoginRequest — les classes
# s'appellent LoginPayload/PinLoginPayload) et appelait create_access_token /
# create_refresh_token avec une signature différente de celle réellement
# définie dans auth_service.py (qui prend l'objet User, pas son id et son
# rôle séparément). Comme app/main.py charge tous les routers au démarrage,
# cela faisait planter l'application entière avant même de recevoir une
# requête. Réécrit pour n'utiliser que les modules et signatures qui
# existent réellement dans ce projet.

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.constants import JWT_EXPIRATION_MINUTES, REFRESH_COOKIE_SECURE
from app.core import session_store
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.user import User
from app.schemas.auth import (
    LoginPayload,
    PasswordChangePayload,
    PinLoginPayload,
    TokenResponse,
    UserOut,
)
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "noc_refresh"
# Path restreint : le cookie n'est envoyé par le navigateur que sur les
# routes d'auth, jamais sur le reste de l'API — réduit la surface exposée
# en cas de XSS ailleurs dans l'app (le cookie httpOnly n'est de toute façon
# pas lisible en JS, mais restreindre le path limite aussi son envoi).
REFRESH_COOKIE_PATH = "/api/auth"

# Rôles autorisés à se connecter par PIN — jamais Directeur/Chef NOC, dont
# les comptes portent plus de privilèges et doivent rester sur un facteur
# fort (mot de passe, éventuellement MFA plus tard). Le PIN est un facteur
# de confort pour la relève d'équipe sur une console partagée sur le terrain.
PIN_LOGIN_ALLOWED_ROLES = {"agent_terrain"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_refresh_cookie(response: Response, token: str, expire_at: datetime) -> None:
    max_age = int((expire_at - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,  # cf. app/core/constants.py — désactiver seulement en dev http:// local
        samesite="Lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _issue_session(user: User, response: Response) -> TokenResponse:
    access_token = auth_service.create_access_token(user)
    refresh_token, jti, refresh_expire = auth_service.create_refresh_token(user)
    session_store.store_refresh_session(user.id, jti, refresh_expire)
    _set_refresh_cookie(response, refresh_token, refresh_expire)

    return TokenResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login_with_password(payload: LoginPayload, response: Response, db: Session = Depends(get_db)):
    # authenticate_with_password lève déjà un 401 générique (identifiants
    # invalides) sur mauvais mot de passe ou compte inexistant/inactif — pas
    # de distinction, pour ne pas laisser un attaquant énumérer les usernames.
    user = auth_service.authenticate_with_password(db, payload.username, payload.password)
    return _issue_session(user, response)


@router.post("/pin-login", response_model=TokenResponse)
def login_with_pin(payload: PinLoginPayload, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    locked_ttl = session_store.is_pin_locked(ip)
    if locked_ttl is not None:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            detail={"message": "Trop de tentatives — réessayez plus tard.", "retry_after_seconds": locked_ttl},
        )

    try:
        user = auth_service.authenticate_with_pin(db, payload.pin)
    except HTTPException:
        session_store.register_pin_failure(ip)
        raise

    if user.role not in PIN_LOGIN_ALLOWED_ROLES:
        # Rôle non éligible au PIN : même erreur générique que "PIN
        # invalide", pour ne pas révéler que le compte existe mais n'a pas
        # le droit d'utiliser ce mode de connexion.
        session_store.register_pin_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code PIN invalide")

    session_store.clear_pin_failures(ip)
    return _issue_session(user, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(
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

    user_id = int(payload["sub"])
    jti = payload["jti"]

    if not session_store.is_refresh_session_valid(jti, user_id):
        # jti absent du registre Redis alors que la signature JWT est
        # valide : soit il a déjà été consommé par une rotation précédente
        # (réutilisation = vol probable), soit il a été révoqué (logout /
        # revoke-sessions). Dans les deux cas, principe de précaution : on
        # tue TOUTES les sessions de ce compte, pas seulement celle-ci.
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou déjà utilisée.")

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")

    new_refresh_token, new_jti, new_expire = auth_service.create_refresh_token(user)
    session_store.rotate_refresh_session(jti, user_id, new_jti, new_expire)
    _set_refresh_cookie(response, new_refresh_token, new_expire)

    access_token = auth_service.create_access_token(user)
    return TokenResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_MINUTES * 60,
        user=UserOut.model_validate(user),
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
            pass  # cookie déjà invalide/expiré : rien à révoquer, on nettoie quand même côté navigateur
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    payload: PasswordChangePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not auth_service.authenticate_with_password(db, current_user.username, payload.current_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe actuel incorrect.")
    auth_service.set_password(db, current_user.id, payload.new_password)


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: int,
    _admin: User = Depends(require_role("directeur")),
):
    # Coupe l'accès immédiatement (poste volé, agent quittant l'agence) sans
    # attendre l'expiration naturelle des tokens. La session actuelle du
    # Directeur qui déclenche ceci n'est pas concernée si user_id != son
    # propre id.
    session_store.revoke_all_sessions(user_id)
