"""Authentification : connexion, PIN, rafraîchissement, déconnexion."""
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.core import session_store
from app.core.config import (
    JWT_EXPIRATION_MINUTES,
    LOGIN_LOCK_WINDOW_SECONDS,
    LOGIN_MAX_FAILURES_PER_IP,
    LOGIN_MAX_FAILURES_PER_USER,
    PIN_DEVICE_DAYS,
    PIN_REQUIRE_KNOWN_DEVICE,
    REFRESH_COOKIE_SECURE,
)
from app.core.rate_limit import client_ip
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.schemas.auth import (
    LockStatusPayload,
    LoginPayload,
    PasswordChangePayload,
    PasswordResetConfirmPayload,
    PasswordResetRequestPayload,
    PinLoginPayload,
    TokenResponse,
)
from app.schemas.users import UserOut, UserSelfUpdate
from app.services import audit_service, auth_service, user_service

router = APIRouter(prefix="/api/auth", tags=["authentification"])


@router.get("/support")
def support_contacts() -> dict:
    """Contact du support, affiché sur l'écran de connexion (INC-45).

    PUBLIC par nature : il sert précisément à qui ne peut pas se connecter.
    Ne contient que ce que l'agence choisit de publier (SUPPORT_EMAIL,
    SUPPORT_PHONE, SUPPORT_HOURS) ; vide si rien n'est configuré.
    """
    import os

    from app.core.config import SMTP_HOST

    return {
        "email": os.getenv("SUPPORT_EMAIL", "").strip() or None,
        "phone": os.getenv("SUPPORT_PHONE", "").strip() or None,
        "hours": os.getenv("SUPPORT_HOURS", "").strip() or None,
        # Sans serveur de courriel, aucun lien ne peut partir : l'écran le dit
        # au lieu de faire attendre un message qui ne viendra pas.
        "password_reset_by_email": bool(SMTP_HOST),
    }

REFRESH_COOKIE_NAME = "noc_refresh"
# Chemin restreint : le navigateur n'envoie le cookie que sur les routes
# d'authentification, jamais sur le reste de l'API.
REFRESH_COOKIE_PATH = "/api/auth"

# Rôles autorisés à se connecter par PIN. Jamais Directeur ni Chef NOC :
# leurs comptes portent bien plus de privilèges et doivent rester sur un
# facteur fort. Le PIN est un confort pour la relève d'équipe sur une
# console partagée — voir auth_service.hash_pin.
PIN_LOGIN_ALLOWED_ROLES = {"agent_terrain"}


def _set_refresh_cookie(response: Response, token: str, expire_at: datetime) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=int((expire_at - datetime.now(UTC)).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        # `strict` : l'interface et l'API sont servies par la même origine,
        # le cookie n'a aucune raison de partir d'une page tierce.
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _login_scopes(ip: str, username: str) -> tuple[tuple[str, str, int], ...]:
    """Les trois compteurs d'échecs de la connexion par mot de passe.

    login_ip       une source qui essaie beaucoup d'identifiants ;
    login_user_ip  une source qui s'acharne sur un compte ;
    login_user     un compte attaqué depuis de nombreuses sources. Seuil
                   cinq fois plus haut : quelques essais depuis n'importe où
                   ne doivent pas suffire à bloquer le Chef NOC en pleine
                   crise.
    """
    account = username.strip().lower()
    return (
        ("login_ip", ip, LOGIN_MAX_FAILURES_PER_IP),
        ("login_user_ip", f"{account}|{ip}", LOGIN_MAX_FAILURES_PER_USER),
        ("login_user", account, LOGIN_MAX_FAILURES_PER_USER * 5),
    )


def _lock_remaining(scopes) -> int:
    return max((session_store.lock_ttl(scope, subject) or 0) for scope, subject, _ in scopes)


def _ensure_not_locked(scopes) -> None:
    remaining = _lock_remaining(scopes)
    if remaining:
        # Même forme de détail que le verrouillage du PIN : l'écran de
        # connexion sait déjà l'afficher (LoginPage.jsx).
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Trop de tentatives — réessayez plus tard.",
                "retry_after_seconds": remaining,
            },
            headers={"Retry-After": str(remaining)},
        )


def _record_failure(scopes) -> None:
    for scope, subject, limit in scopes:
        session_store.register_failure(scope, subject, limit, LOGIN_LOCK_WINDOW_SECONDS)


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


@router.post("/lock-status")
def lock_status(payload: LockStatusPayload, request: Request) -> dict:
    """Temps d'attente restant avant une nouvelle tentative (0 : aucun).

    Lu par l'écran de connexion au chargement : le décompte survit ainsi à une
    actualisation, et disparaît si le verrou a été levé entre-temps. Ne dit
    rien de plus que la connexion elle-même : un identifiant inconnu se
    verrouille comme un autre.
    """
    ip = client_ip(request)
    if payload.mode == "pin":
        remaining = session_store.is_pin_locked(ip, payload.username) or 0
    else:
        remaining = _lock_remaining(_login_scopes(ip, payload.username))
    return {"retry_after_seconds": remaining}


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginPayload,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    scopes = _login_scopes(client_ip(request), payload.username)
    _ensure_not_locked(scopes)

    try:
        user = auth_service.authenticate_with_password(db, payload.username, payload.password)
    except HTTPException:
        _record_failure(scopes)
        # L'identifiant tenté, jamais le mot de passe.
        audit_service.record(
            db, "auth.login_failed", target=payload.username[:150], request=request
        )
        # L'échec qui déclenche le verrou l'annonce tout de suite, avec sa
        # durée, au lieu d'un « identifiants invalides » trompeur.
        _ensure_not_locked(scopes)
        raise

    # Le compteur de l'IP n'est PAS remis à zéro : un attaquant qui détient
    # un compte valide effacerait sinon ses échecs en s'y connectant.
    for scope, subject, _ in scopes[1:]:
        session_store.clear_failures(scope, subject)
    audit_service.record(db, "auth.login", actor=user, target=user.username, request=request)
    _remember_device(request, response)
    return _issue_session(db, user, response)


def _remember_device(request: Request, response: Response) -> None:
    """Marque ce navigateur comme poste reconnu (INC-43), ou prolonge la
    marque : un mot de passe valide vient d'y être saisi.

    Cookie HttpOnly, limité aux routes d'authentification, SameSite strict.
    La déconnexion ne l'efface pas : il décrit le POSTE, pas la session —
    c'est ce qui permet la relève par PIN sur une console partagée.
    """
    current = request.cookies.get(auth_service.DEVICE_COOKIE_NAME)
    # Renouvelé au-delà de la moitié de sa vie, pour ne pas expirer en
    # pleine relève sur un poste utilisé tous les jours.
    if auth_service.is_known_device(current, PIN_DEVICE_DAYS // 2):
        return
    response.set_cookie(
        key=auth_service.DEVICE_COOKIE_NAME,
        value=auth_service.create_device_token(),
        max_age=PIN_DEVICE_DAYS * 86400,
        path="/api/auth",
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite="strict",
    )


def _ensure_pin_not_locked(ip: str, username: str) -> None:
    locked_ttl = session_store.is_pin_locked(ip, username)
    if locked_ttl is not None:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            detail={
                "message": "Trop de tentatives — réessayez plus tard.",
                "retry_after_seconds": locked_ttl,
            },
        )


@router.post("/pin-login", response_model=TokenResponse)
def pin_login(
    payload: PinLoginPayload,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    # INC-43 : PIN refusé sur un navigateur où aucun mot de passe n'a été
    # saisi. Vérifié AVANT le PIN : rien n'est essayé, donc rien n'est appris
    # du code saisi, depuis un poste inconnu.
    if PIN_REQUIRE_KNOWN_DEVICE and not auth_service.is_known_device(
        request.cookies.get(auth_service.DEVICE_COOKIE_NAME), PIN_DEVICE_DAYS
    ):
        audit_service.record(
            db, "auth.pin_login_failed", target=payload.username,
            detail={"reason": "unknown_device"}, request=request,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error": "unknown_device",
                "message": (
                    "Ce poste n'est pas reconnu pour la connexion par PIN. Connectez-vous "
                    "une première fois avec un identifiant et un mot de passe sur ce navigateur."
                ),
            },
        )
    _ensure_pin_not_locked(ip, payload.username)

    try:
        user = auth_service.authenticate_with_pin(db, payload.username, payload.pin)
    except HTTPException:
        session_store.register_pin_failure(ip, payload.username)
        audit_service.record(
            db, "auth.pin_login_failed", target=payload.username, request=request
        )
        _ensure_pin_not_locked(ip, payload.username)
        raise

    if user.role not in PIN_LOGIN_ALLOWED_ROLES:
        # Même erreur générique qu'un PIN invalide : révéler que le compte
        # existe mais n'a pas le droit d'utiliser ce mode renseignerait un
        # attaquant sur la validité du PIN saisi.
        session_store.register_pin_failure(ip, payload.username)
        # Le journal, lui, peut nommer le compte : il n'est lu que par la salle.
        audit_service.record(
            db, "auth.pin_login_failed", actor=user, target=user.username,
            detail={"reason": "role"}, request=request,
        )
        _ensure_pin_not_locked(ip, payload.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiant ou code PIN invalide.")

    session_store.clear_pin_failures(ip, payload.username)
    audit_service.record(db, "auth.pin_login", actor=user, target=user.username, request=request)
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

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte introuvable ou désactivé.")

    new_token, new_jti, new_expire = auth_service.create_refresh_token(user)
    rotation = session_store.rotate_refresh_session(
        jti, user_id, new_jti, new_expire
    )
    if rotation == "recently_rotated":
        # Deux onglets peuvent avoir envoyé le même cookie avant que la
        # première réponse ne le remplace. Ne pas effacer ce nouveau cookie
        # ni révoquer toutes les sessions pour ce doublon concurrent.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Session déjà actualisée par une requête concurrente.",
        )
    if rotation != "rotated":
        session_store.revoke_all_sessions(user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Session invalide ou déjà utilisée.",
        )
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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mise à jour de ses propres identifiants — ouverte à tous les rôles.

    Identifiant, nom, téléphone, adresse et abonnement aux alertes. Le rôle
    n'est pas modifiable ici (le schéma refuse le champ) : seul un Chef NOC
    l'attribue, depuis la gestion des comptes.
    """
    changes = payload.model_dump(exclude_unset=True)
    previous_username = current_user.username
    updated = user_service.update_self(db, current_user, changes)
    detail = {"fields": sorted(field for field in changes if field != "current_password")}
    if updated["username"] != previous_username:
        detail["username"] = {"from": previous_username, "to": updated["username"]}
    audit_service.record(
        db, "auth.profile_updated", actor=current_user, target=updated["username"],
        detail=detail, request=request,
    )
    return UserOut(**updated)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    payload: PasswordChangePayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Mêmes compteurs que la connexion : une session restée ouverte sur un
    # poste de salle ne doit pas servir à deviner le mot de passe du compte.
    scopes = _login_scopes(client_ip(request), current_user.username)
    _ensure_not_locked(scopes)
    try:
        auth_service.authenticate_with_password(
            db, current_user.username, payload.current_password
        )
    except HTTPException:
        _record_failure(scopes)
        raise
    if payload.new_password == payload.current_password:
        raise HTTPException(
            422, "Le nouveau mot de passe doit être différent de l'ancien."
        )
    auth_service.set_password(db, current_user.id, payload.new_password)
    # Changer son mot de passe invalide les autres sessions : c'est le
    # geste attendu quand on soupçonne une compromission.
    session_store.revoke_all_sessions(current_user.id)
    audit_service.record(
        db, "auth.password_changed", actor=current_user, target=current_user.username,
        request=request,
    )


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("chef_noc")),
):
    session_store.revoke_all_sessions(user_id)
    target = db.get(User, user_id)
    audit_service.record(
        db, "auth.sessions_revoked", actor=admin,
        target=target.username if target is not None else None,
        detail={"user_id": user_id}, request=request,
    )


# ---------------------------------------------------------------------------
# Réinitialisation du mot de passe par courriel (INC-45)
# ---------------------------------------------------------------------------
_RESET_SENT = {
    "message": (
        "Si un compte actif correspond et qu'une adresse électronique y est "
        "associée, un lien de réinitialisation vient d'y être envoyé. Pensez à "
        "vérifier les courriels indésirables."
    )
}
# Demandes par adresse IP et par compte, dans la fenêtre de verrouillage.
RESET_MAX_PER_IP = 5
RESET_MAX_PER_ACCOUNT = 3


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: PasswordResetRequestPayload,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Envoie un lien de réinitialisation au compte désigné.

    La réponse est la MÊME que le compte existe ou non, ait une adresse ou
    non : la route ne doit pas servir à découvrir des identifiants. L'envoi
    se fait après la réponse (tâche de fond), pour que la durée de réponse
    ne le trahisse pas non plus. Les comptes à PIN seul (agents terrain) se
    réinitialisent par le Chef NOC.
    """
    from app.core.config import NOC_PUBLIC_URL
    from app.services import notification_service

    ip = client_ip(request)
    identifier = payload.identifier.strip().lower()
    scopes = (
        ("pwreset_ip", ip, RESET_MAX_PER_IP),
        ("pwreset_account", identifier, RESET_MAX_PER_ACCOUNT),
    )
    _ensure_not_locked(scopes)
    # Chaque DEMANDE compte (pas seulement les échecs) : on limite le
    # nombre de courriels qu'un tiers peut faire envoyer à quelqu'un.
    _record_failure(scopes)

    user = auth_service.find_for_password_reset(db, identifier)
    audit_service.record(
        db, "auth.password_reset_requested",
        actor=user, target=user.username if user else None,
        detail={"account_found": bool(user), "has_email": bool(user and user.email)},
        request=request,
    )
    # Un compte à PIN seul n'a pas de mot de passe à réinitialiser : lui en
    # donner un ouvrirait un second mode de connexion.
    if user is not None and user.email and user.password_hash:
        token = session_store.store_password_reset(user.id)
        # Après « # » : le navigateur n'envoie jamais cette partie au serveur,
        # le jeton n'apparaît donc dans aucun journal d'accès.
        link = f"{NOC_PUBLIC_URL}/reinitialiser#jeton={token}"
        background.add_task(
            notification_service.send_password_reset_email,
            user.email,
            user.full_name or user.username,
            link,
            session_store.PASSWORD_RESET_TTL_SECONDS // 60,
        )
    return _RESET_SENT


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(
    payload: PasswordResetConfirmPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Fixe le nouveau mot de passe avec un jeton reçu par courriel.

    Le jeton est consommé même si la suite échoue : un lien ne sert qu'une
    fois. Toutes les sessions ouvertes du compte sont coupées — c'est le
    geste attendu si la réinitialisation fait suite à une compromission.
    """
    ip = client_ip(request)
    scopes = (("pwreset_confirm_ip", ip, RESET_MAX_PER_IP * 2),)
    _ensure_not_locked(scopes)
    user_id = session_store.consume_password_reset(payload.token)
    user = db.get(User, user_id) if user_id is not None else None
    # Le compte a pu être désactivé ou passer au PIN seul depuis l'envoi.
    if user is None or not user.is_active or not user.password_hash:
        _record_failure(scopes)
        audit_service.record(db, "auth.password_reset_failed", request=request)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Lien invalide, expiré ou déjà utilisé. Demandez un nouveau lien.",
        )
    auth_service.set_password(db, user.id, payload.new_password)
    session_store.revoke_all_sessions(user.id)
    # Le compte était peut-être verrouillé par des échecs : le nouveau mot de
    # passe doit être utilisable tout de suite.
    # Pas le compteur de l'IP : il protège aussi les autres comptes.
    for scope, subject, _limit in _login_scopes(ip, user.username)[1:]:
        session_store.clear_lock(scope, subject)
    audit_service.record(
        db, "auth.password_reset_completed", actor=user, target=user.username, request=request,
    )
