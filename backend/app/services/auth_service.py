import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.constants import JWT_ALGORITHM, JWT_EXPIRATION_MINUTES, JWT_SECRET
from app.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def hash_pin(pin: str) -> str:
    """Hash a quick-login PIN for direct lookup by hash.

    Unsalted SHA-256, unlike hash_password above, which uses bcrypt. This is
    a real weakening and worth understanding before reusing the pattern: the
    keyspace of a short numeric PIN is small enough to enumerate completely in
    well under a second, so anyone who obtains dim_user.pin_hash recovers every
    PIN, and identical PINs are visible as identical hashes. It is accepted
    here only because the PIN is a convenience credential for shift handover on
    a shared NOC console — a second factor for someone already physically at
    the console, never the sole protection on an account.

    Two consequences follow. Do not let a PIN stand in for the password on any
    path that matters, and if PINs ever become longer, user-chosen, or reused
    from another system, replace this with a salted adaptive hash and the
    lookup-by-hash that depends on it.
    """
    return hashlib.sha256(pin.encode()).hexdigest()


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def authenticate_with_password(db: Session, username: str, password: str) -> User:
    user = (
        db.query(User)
        .filter(User.username == username, User.is_active.is_(True))
        .first()
    )
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    _touch_last_login(db, user)
    return user


def authenticate_with_pin(db: Session, pin: str) -> User:
    user = (
        db.query(User)
        .filter(User.pin_hash == hash_pin(pin), User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Code PIN invalide")
    _touch_last_login(db, user)
    return user


def _touch_last_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
