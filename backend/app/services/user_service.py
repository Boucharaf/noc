"""Gestion des comptes (dim_user)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import VALID_ROLES
from app.models.operations import User
from app.services import auth_service


def _serialize(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": bool(user.is_active),
        "region_id": user.region_id,
        "locality_id": user.locality_id,
        "ministry_id": user.ministry_id,
        "phone_number": user.phone_number,
        "employee_code": user.employee_code,
        "team": user.team,
        "has_pin": user.pin_hash is not None,
        "last_login_at": user.last_login_at,
    }


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

    user = User(
        username=payload["username"],
        full_name=payload["full_name"],
        role=payload["role"],
        password_hash=auth_service.hash_password(payload["password"]),
        pin_hash=auth_service.hash_pin(payload["pin"]) if payload.get("pin") else None,
        phone_number=payload.get("phone_number"),
        region_id=payload.get("region_id"),
        locality_id=payload.get("locality_id"),
        ministry_id=payload.get("ministry_id"),
        employee_code=payload.get("employee_code"),
        team=payload.get("team"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


def update_user(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    if payload.get("role") and payload["role"] not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Rôle inconnu.")

    for field in (
        "full_name", "role", "phone_number", "region_id", "locality_id",
        "ministry_id", "employee_code", "team", "is_active",
    ):
        if field in payload and payload[field] is not None:
            setattr(user, field, payload[field])

    db.commit()
    db.refresh(user)
    return _serialize(user)


def deactivate_user(db: Session, user_id: int) -> None:
    """Désactivation, jamais suppression.

    Un compte supprimé emporterait ses lignes de ops_incident_timeline et
    ops_field_intervention, ou en casserait les clés étrangères : la
    traçabilité « qui a résolu cet incident » disparaîtrait avec lui.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.is_active = False
    user.pin_hash = None  # le PIN d'un compte désactivé ne doit plus ouvrir de session
    db.commit()
