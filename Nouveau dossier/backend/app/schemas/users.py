"""Schémas des comptes utilisateurs."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.core.config import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, PIN_LENGTH

# Volontairement permissif : la seule validation qui prouve qu'une adresse
# existe est un courriel reçu (voir POST /api/notifications/email/test). Ce
# motif n'écarte que les fautes de frappe grossières — espace, @ absent.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# Pas d'espace ni d'accent dans un identifiant : il se tape sur un clavier
# de téléphone et se lit dans les journaux d'audit.
_USERNAME_PATTERN = r"^[A-Za-z0-9._-]+$"


def _bcrypt_compatible(value: str) -> str:
    # bcrypt ignore tout au-delà de 72 octets : deux mots de passe qui ne
    # diffèrent qu'après seraient interchangeables. Contrôle en OCTETS, une
    # lettre accentuée en occupant deux.
    if len(value.encode()) > 72:
        raise ValueError("Mot de passe trop long : 72 octets au plus.")
    return value


NewPassword = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    AfterValidator(_bcrypt_compatible),
]

# Tout NOUVEAU code : exactement PIN_LENGTH chiffres. La connexion accepte
# encore les codes plus courts définis auparavant (schemas/auth.py).
NewPin = Annotated[
    str,
    Field(min_length=PIN_LENGTH, max_length=PIN_LENGTH, pattern=rf"^\d{{{PIN_LENGTH}}}$"),
]


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


class UserSummary(BaseModel):
    """Ce que voit d'un collègue un compte qui ne gère pas les comptes.

    Assez pour choisir à qui affecter une alerte ; ni téléphone, ni
    courriel, ni matricule, ni date de dernière connexion — ces données
    personnelles ne servent qu'au Chef NOC.
    """

    id: int
    username: str
    full_name: str | None = None
    role: RoleEnum
    is_active: bool = True
    site: str | None = None
    team: str | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=_USERNAME_PATTERN)
    full_name: str = Field(min_length=1, max_length=150)
    role: RoleEnum
    password: NewPassword
    pin: NewPin | None = None
    phone_number: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    notify_email: bool = False
    site: str | None = Field(default=None, max_length=150)
    organisation: str | None = Field(default=None, max_length=150)
    employee_code: str | None = Field(default=None, max_length=50)
    team: str | None = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    """Modification d'un compte par le Chef NOC."""

    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role: RoleEnum | None = None
    phone_number: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    notify_email: bool | None = None
    site: str | None = Field(default=None, max_length=150)
    organisation: str | None = Field(default=None, max_length=150)
    employee_code: str | None = Field(default=None, max_length=50)
    team: str | None = Field(default=None, max_length=100)
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
    current_password: str | None = Field(default=None, max_length=256)


class PinResetPayload(BaseModel):
    new_pin: NewPin


class PasswordResetPayload(BaseModel):
    new_password: NewPassword
