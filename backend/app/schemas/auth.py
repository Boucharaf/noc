"""Schémas d'authentification."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.users import UserOut


class LoginPayload(BaseModel):
    username: str
    password: str


class PinLoginPayload(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
