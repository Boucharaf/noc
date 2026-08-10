from pydantic import BaseModel, Field


class LoginPayload(BaseModel):
    username: str
    password: str


class PinLoginPayload(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Seconds the token stays valid. Sent so the client can renew ahead of
    # expiry without parsing the JWT — the lifetime is a server policy, and a
    # client that reads it from the token would silently follow a stale copy
    # of that policy after any change here.
    expires_in: int
    user: UserOut
