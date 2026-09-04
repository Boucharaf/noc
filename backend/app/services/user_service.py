"""Account management for the four NOC roles (Directeur, Chef NOC,
Technicien/Ingénieur, Agent terrain).

Deliberately separate from auth_service: auth_service is about proving who
you are (login, tokens, PIN, password hashing primitives); this module is
about the lifecycle of the accounts themselves (create, list, deactivate),
used by the /api/users routes reserved for Directeur/Chef NOC.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import VALID_ROLES, User
from app.schemas.auth import UserCreate, UserUpdate
from app.services.auth_service import hash_password, hash_pin


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Rôle invalide '{role}'. Valeurs acceptées : {', '.join(VALID_ROLES)}",
        )


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.full_name).all()


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def create_user(db: Session, payload: UserCreate) -> User:
    _validate_role(payload.role)

    existing = db.query(User).filter(User.username == payload.username).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Ce nom d'utilisateur existe déjà")

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role.value,
        password_hash=hash_password(payload.password),
        pin_hash=hash_pin(payload.pin) if payload.pin else None,
        is_active=True,
        phone_number=payload.phone_number,
        region_id=payload.region_id,
        locality_id=payload.locality_id,
        employee_code=payload.employee_code,
        team=payload.team,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, payload: UserUpdate) -> User | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        _validate_role(payload.role)
        user.role = payload.role.value
    if payload.phone_number is not None:
        user.phone_number = payload.phone_number
    if payload.region_id is not None:
        user.region_id = payload.region_id
    if payload.locality_id is not None:
        user.locality_id = payload.locality_id
    if payload.employee_code is not None:
        user.employee_code = payload.employee_code
    if payload.team is not None:
        user.team = payload.team
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user


def set_active(db: Session, user_id: int, is_active: bool) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def set_pin(db: Session, user_id: int, new_pin: str) -> User:
    """Admin-driven PIN reset used by the user management routes."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.pin_hash = hash_pin(new_pin)
    db.commit()
    db.refresh(user)
    return user