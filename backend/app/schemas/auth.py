"""Schémas d'authentification."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.users import NewPassword, UserOut


class LoginPayload(BaseModel):
    # Bornes larges mais bornes : sans elles, un corps de plusieurs mégaoctets
    # serait haché par bcrypt à chaque tentative.
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)


class PinLoginPayload(BaseModel):
    # 4 à 8 chiffres ACCEPTÉS à la connexion, pour les codes définis avant le
    # passage à 6 chiffres. Tout nouveau code en compte exactement 6
    # (schemas/users.py::NewPin).
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class PasswordChangePayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: NewPassword


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
