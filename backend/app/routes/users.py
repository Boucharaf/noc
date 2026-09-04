# app/routes/users.py — nouveau fichier
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserCreate, UserOut, UserUpdate, PinResetPayload
from app.services import user_service

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],
)

# Seuls Directeur/Chef NOC gèrent les comptes
_MANAGE_USERS = Depends(require_role("directeur", "chef_noc"))


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = _MANAGE_USERS):
    return user_service.list_users(db)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = _MANAGE_USERS):
    return user_service.create_user(db, payload)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), _: User = _MANAGE_USERS):
    user = user_service.update_user(db, user_id, payload)
    if user is None:
        raise HTTPException(404, "Utilisateur introuvable")
    return user


@router.post("/{user_id}/deactivate", status_code=204)
def deactivate_user(user_id: int, db: Session = Depends(get_db), _: User = _MANAGE_USERS):
    user_service.set_active(db, user_id, False)


@router.post("/{user_id}/reset-pin", status_code=204)
def reset_pin(user_id: int, payload: PinResetPayload, db: Session = Depends(get_db), _: User = _MANAGE_USERS):
    user_service.set_pin(db, user_id, payload.new_pin)

# Changement de son propre mot de passe : voir PATCH /api/auth/me/password
# (app/routes/auth.py). Un doublon existait ici, sans vérification du mot de
# passe actuel avant remplacement — n'importe quel utilisateur connecté
# aurait pu changer son propre mot de passe sans le prouver. Supprimé plutôt
# que corrigé sur place, pour ne garder qu'un seul endroit où ce flux vit.