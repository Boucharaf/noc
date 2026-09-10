"""Gestion des comptes — réservée au Chef NOC.

Créer un compte et attribuer un rôle sont des gestes d'exploitation de la
salle : le Chef NOC est seul à les faire. Chaque utilisateur garde en
revanche la main sur SES identifiants depuis « Mon compte » (PATCH
/api/auth/me et /api/auth/me/password, routes/auth.py) — jamais sur son rôle.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import session_store
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.schemas.users import (
    PasswordResetPayload,
    PinResetPayload,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import auth_service, user_service

router = APIRouter(prefix="/api/users", tags=["utilisateurs"])

# Miroir de PERMISSIONS.MANAGE_USERS dans frontend/src/lib/permissions.js.
_MANAGE_USERS = ("chef_noc",)


def _forbid_self_lockout(user_id: int, admin: User) -> None:
    """Un Chef NOC ne retire pas ses propres droits.

    Rétrogradé ou désactivé de sa propre main, le dernier Chef NOC laisserait
    la plateforme sans personne capable de créer un compte : il ne resterait
    que la ligne de commande (scripts/create_user.py). Un autre Chef NOC peut
    le faire à sa place.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Vous ne pouvez ni changer votre propre rôle ni désactiver votre "
                "propre compte : demandez-le à un autre Chef NOC."
            ),
        )


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
    admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    # Comparé au rôle ACTUEL du compte, et non à la simple présence du champ :
    # renvoyer le même rôle en corrigeant un numéro de téléphone ne doit ni
    # être refusé ni couper les sessions de l'intéressé.
    target = db.get(User, user_id)
    role_changes = (
        target is not None and payload.role is not None and payload.role != target.role
    )
    access_changes = role_changes or payload.is_active is False
    if access_changes:
        _forbid_self_lockout(user_id, admin)

    updated = user_service.update_user(db, user_id, payload.model_dump(exclude_unset=True))
    # Un changement de rôle doit prendre effet tout de suite : les jetons
    # en cours portent l'ancien rôle et get_current_user les rejettera,
    # mais couper les sessions évite d'attendre ce rejet.
    if access_changes:
        session_store.revoke_all_sessions(user_id)
    return updated


@router.post("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    _forbid_self_lockout(user_id, admin)
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


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    payload: PasswordResetPayload,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(*_MANAGE_USERS)),
):
    """Mot de passe oublié : le Chef NOC en fixe un provisoire.

    Les sessions en cours sont coupées — si l'oubli cache en réalité une
    compromission, l'ancien mot de passe ne doit plus rien ouvrir, pas même
    une session déjà établie.
    """
    auth_service.set_password(db, user_id, payload.new_password)
    session_store.revoke_all_sessions(user_id)
