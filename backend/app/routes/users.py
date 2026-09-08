"""Gestion des comptes — réservée au Directeur et au Chef NOC."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core import session_store
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.operations import User
from app.schemas.users import PinResetPayload, UserCreate, UserOut, UserUpdate
from app.services import auth_service, user_service

router = APIRouter(prefix="/api/users", tags=["utilisateurs"])

_MANAGE_USERS = ("directeur", "chef_noc")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    # Lecture ouverte à tout compte connecté : la liste sert aussi à
    # peupler les sélecteurs d'assignation d'incident, utilisés par les
    # techniciens.
    return user_service.list_users(db)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    return user_service.create_user(db, payload.model_dump())


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    updated = user_service.update_user(db, user_id, payload.model_dump(exclude_unset=True))
    # Un changement de rôle doit prendre effet tout de suite : les jetons
    # en cours portent l'ancien rôle et get_current_user les rejettera,
    # mais couper les sessions évite d'attendre ce rejet.
    if payload.role is not None or payload.is_active is False:
        session_store.revoke_all_sessions(user_id)
    return updated


@router.post("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    user_service.deactivate_user(db, user_id)
    session_store.revoke_all_sessions(user_id)


@router.post("/{user_id}/reset-pin", status_code=status.HTTP_204_NO_CONTENT)
def reset_pin(
    user_id: int,
    payload: PinResetPayload,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    auth_service.set_pin(db, user_id, payload.new_pin)
