"""Schémas des comptes utilisateurs."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# Volontairement permissif : la seule validation qui prouve qu'une adresse
# existe est un courriel reçu (voir POST /api/notifications/email/test). Ce
# motif n'écarte que les fautes de frappe grossières — espace, @ absent.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# Pas d'espace ni d'accent dans un identifiant : il se tape sur un clavier
# de téléphone et se lit dans les journaux d'audit.
_USERNAME_PATTERN = r"^[A-Za-z0-9._-]+$"


class RoleEnum(StrEnum):
    """Miroir exact de VALID_ROLES (core/config.py) et de ROLES dans
    frontend/src/lib/permissions.js. Un nouveau rôle doit être ajouté aux
    trois endroits."""

    directeur = "directeur"
    chef_noc = "chef_noc"
    technicien = "technicien"
    agent_terrain = "agent_terrain"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    role: RoleEnum
    is_active: bool = True
    phone_number: str | None = None
    email: str | None = None
    notify_email: bool = False
    site: str | None = None
    organisation: str | None = None
    employee_code: str | None = None
    team: str | None = None
    has_pin: bool = False
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=_USERNAME_PATTERN)
    full_name: str = Field(min_length=1, max_length=150)
    role: RoleEnum
    password: str = Field(min_length=8)
    pin: str | None = Field(default=None, min_length=4, max_length=6, pattern=r"^\d+$")
    phone_number: str | None = None
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    notify_email: bool = False
    site: str | None = None
    organisation: str | None = None
    employee_code: str | None = None
    team: str | None = None


class UserUpdate(BaseModel):
    """Modification d'un compte par le Chef NOC."""

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role: RoleEnum | None = None
    phone_number: str | None = None
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    notify_email: bool | None = None
    site: str | None = None
    organisation: str | None = None
    employee_code: str | None = None
    team: str | None = None
    is_active: bool | None = None


class UserSelfUpdate(BaseModel):
    """Ce qu'un utilisateur modifie lui-même, depuis « Mon compte ».

    Le rôle N'Y FIGURE PAS, et `extra="forbid"` fait refuser explicitement
    (422) une requête qui l'enverrait, plutôt que de l'ignorer en silence :
    le client doit apprendre que la demande n'est pas recevable, pas croire
    qu'elle a abouti. Seul un Chef NOC attribue un rôle (routes/users.py).
    """

    model_config = {"extra": "forbid"}

    username: str | None = Field(
        default=None, min_length=3, max_length=50, pattern=_USERNAME_PATTERN
    )
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone_number: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    notify_email: bool | None = None
    # Exigé seulement pour changer d'identifiant : c'est changer le moyen de
    # se connecter, ce qui ne doit pas être à la portée de quiconque trouve
    # une session restée ouverte sur un poste de salle.
    current_password: str | None = None


class PinResetPayload(BaseModel):
    new_pin: str = Field(min_length=4, max_length=6, pattern=r"^\d+$")


class PasswordResetPayload(BaseModel):
    new_password: str = Field(min_length=8)
