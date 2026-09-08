"""Schémas des comptes utilisateurs."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RoleEnum(StrEnum):
    """Miroir exact de VALID_ROLES (core/config.py), de la contrainte
    chk_dim_user_role en base et de ROLES dans
    frontend/src/api/permissions.js. Un nouveau rôle doit être ajouté aux
    quatre endroits."""

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
    region_id: int | None = None
    locality_id: int | None = None
    ministry_id: int | None = None
    phone_number: str | None = None
    employee_code: str | None = None
    team: str | None = None
    has_pin: bool = False
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=1, max_length=150)
    role: RoleEnum
    password: str = Field(min_length=8)
    pin: str | None = Field(default=None, min_length=4, max_length=6, pattern=r"^\d+$")
    phone_number: str | None = None
    region_id: int | None = None
    locality_id: int | None = None
    ministry_id: int | None = None
    employee_code: str | None = None
    team: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role: RoleEnum | None = None
    phone_number: str | None = None
    region_id: int | None = None
    locality_id: int | None = None
    ministry_id: int | None = None
    employee_code: str | None = None
    team: str | None = None
    is_active: bool | None = None


class PinResetPayload(BaseModel):
    new_pin: str = Field(min_length=4, max_length=6, pattern=r"^\d+$")
