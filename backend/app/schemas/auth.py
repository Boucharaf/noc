from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.users import RoleEnum


class LoginPayload(BaseModel):
    username: str
    password: str


class PinLoginPayload(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: RoleEnum
    region_id: Optional[int] = None
    locality_id: Optional[int] = None
    phone_number: Optional[str] = None
    employee_code: Optional[str] = None
    team: Optional[str] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=100)
    role: RoleEnum
    password: str = Field(..., min_length=8)
    pin: str | None = Field(None, min_length=4, max_length=6, pattern="^[0-9]+$")
    phone_number: Optional[str] = None
    region_id: Optional[int] = None
    locality_id: Optional[int] = None
    employee_code: Optional[str] = None
    team: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=100)
    role: RoleEnum | None = None
    phone_number: Optional[str] = None
    region_id: Optional[int] = None
    locality_id: Optional[int] = None
    employee_code: Optional[str] = None
    team: Optional[str] = None
    is_active: Optional[bool] = None


class PinResetPayload(BaseModel):
    new_pin: str = Field(..., min_length=4, max_length=6, pattern="^[0-9]+$")


class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)