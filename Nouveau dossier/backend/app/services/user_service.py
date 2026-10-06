"""Gestion des comptes (table noc_user)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import VALID_ROLES
from app.models import User
from app.services import auth_service

# Champs facultatifs : None les EFFACE. C'est ainsi qu'on retire un téléphone
# ou une adresse — les ignorer quand ils valent None rendrait l'effacement
# impossible depuis l'interface.
_CLEARABLE_FIELDS = (
    "phone_number", "email", "site", "organisation", "employee_code", "team",
)


def _serialize(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": bool(user.is_active),
        # Rattachement en TEXTE : la géographie appartient désormais aux
        # outils sources (groupes Zabbix/Centreon, Location iTop). Le NOC
        # n'en tient plus de référentiel propre, qui finirait par diverger.
        "site": user.site,
        "organisation": user.organisation,
        "phone_number": user.phone_number,
        "email": user.email,
        "notify_email": bool(user.notify_email),
        "employee_code": user.employee_code,
        "team": user.team,
        "has_pin": user.pin_hash is not None,
        "last_login_at": user.last_login_at,
    }


def _require_address_for_notifications(user: User) -> None:
    """Un abonnement sans adresse serait une promesse non tenue : le compte
    se croirait prévenu des alertes et ne recevrait rien."""
    if user.notify_email and not user.email:
        raise HTTPException(
            status_code=422,
            detail="Renseignez une adresse courriel pour recevoir les alertes.",
        )


def list_users(db: Session, include_inactive: bool = True) -> list[dict]:
    query = db.query(User)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    return [_serialize(u) for u in query.order_by(User.full_name, User.username).all()]


def get_user(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return _serialize(user)


def create_user(db: Session, payload: dict) -> dict:
    if payload["role"] not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Rôle inconnu.")
    if db.query(User).filter(User.username == payload["username"]).first():
        raise HTTPException(status_code=409, detail="Ce nom d'utilisateur existe déjà.")
    if payload.get("pin") and auth_service.pin_in_use(db, payload["pin"]):
        raise HTTPException(
            status_code=409, detail="Ce code PIN est déjà attribué à un autre compte."
        )

    user = User(
        username=payload["username"],
        full_name=payload["full_name"],
        role=payload["role"],
        password_hash=auth_service.hash_password(payload["password"]),
        pin_hash=auth_service.hash_pin(payload["pin"]) if payload.get("pin") else None,
        phone_number=payload.get("phone_number"),
        email=payload.get("email") or None,
        notify_email=bool(payload.get("notify_email")),
        site=payload.get("site"),
        organisation=payload.get("organisation"),
        employee_code=payload.get("employee_code"),
        team=payload.get("team"),
        is_active=True,
    )
    _require_address_for_notifications(user)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


def update_user(db: Session, user_id: int, payload: dict) -> dict:
    """Modification par le Chef NOC. `payload` ne contient que les champs
    effectivement envoyés (exclude_unset côté route)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    if payload.get("role") and payload["role"] not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Rôle inconnu.")

    # Champs obligatoires : None n'y a pas de sens, il est ignoré.
    for field in ("full_name", "role", "is_active", "notify_email"):
        if payload.get(field) is not None:
            setattr(user, field, payload[field])
    for field in _CLEARABLE_FIELDS:
        if field in payload:
            setattr(user, field, payload[field] or None)

    _require_address_for_notifications(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


def update_self(db: Session, user: User, payload: dict) -> dict:
    """Modification de son propre compte, ouverte à tous les rôles.

    Le rôle n'est pas modifiable ici : le schéma UserSelfUpdate le refuse
    avant même d'arriver à cette fonction.
    """
    new_username = payload.get("username")
    if new_username and new_username != user.username:
        # verify_password et non authenticate_with_password : ce dernier
        # mettrait à jour la date de dernière connexion, ce qui fausserait
        # l'audit pour une simple confirmation.
        if not auth_service.verify_password(
            payload.get("current_password") or "", user.password_hash
        ):
            raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect.")
        taken = (
            db.query(User)
            .filter(User.username == new_username, User.id != user.id)
            .first()
        )
        if taken:
            raise HTTPException(status_code=409, detail="Ce nom d'utilisateur existe déjà.")
        user.username = new_username

    if payload.get("full_name") is not None:
        user.full_name = payload["full_name"]
    if payload.get("notify_email") is not None:
        user.notify_email = payload["notify_email"]
    for field in ("phone_number", "email"):
        if field in payload:
            setattr(user, field, payload[field] or None)

    _require_address_for_notifications(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


def deactivate_user(db: Session, user_id: int) -> None:
    """Désactivation, jamais suppression.

    Un compte supprimé emporterait ses lignes de ops_alert_timeline et
    ops_field_intervention, ou en casserait les clés étrangères : la
    traçabilité « qui a résolu cet incident » disparaîtrait avec lui.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.is_active = False
    user.pin_hash = None  # le PIN d'un compte désactivé ne doit plus ouvrir de session
    user.notify_email = False  # ni continuer à recevoir les alertes
    db.commit()
