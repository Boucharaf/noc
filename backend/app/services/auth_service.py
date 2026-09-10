"""Authentification : mots de passe, PIN, jetons JWT."""
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import (
    JWT_ALGORITHM,
    JWT_EXPIRATION_MINUTES,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRATION_DAYS,
)
from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # Empreinte stockée dans un format non bcrypt (compte importé,
        # colonne remplie à la main) : refus, jamais d'exception 500.
        return False


def hash_pin(pin: str) -> str:
    """SHA-256 non salé, pour permettre la recherche du compte PAR le hash.

    C'est un affaiblissement réel et assumé : l'espace des PIN numériques
    courts s'énumère en une fraction de seconde, donc quiconque obtient
    noc_user.pin_hash retrouve tous les PIN, et deux PIN identiques ont
    la même empreinte. Acceptable uniquement parce que le PIN est un
    facteur de confort pour la relève d'équipe sur une console partagée,
    jamais la seule protection d'un compte : voir la restriction de rôle
    dans routes/auth.py (PIN_LOGIN_ALLOWED_ROLES) et le verrouillage par
    IP dans core/session_store.py.
    """
    return hashlib.sha256(pin.encode()).hexdigest()


def create_access_token(user: User) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "type": "access",
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        # `from exc` conserve la cause réelle (signature, expiration) dans
        # la trace serveur, sans jamais l'exposer au client.
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré.") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Type de jeton invalide.")
    return payload


def create_refresh_token(user: User) -> tuple[str, str, datetime]:
    """Retourne (jeton, jti, expiration).

    Le jti est enregistré côté serveur (core/session_store.py) : c'est ce
    qui rend la révocation possible, un JWT signé seul ne pouvant pas
    être invalidé avant son expiration.
    """
    jti = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)
    payload = {"sub": str(user.id), "type": "refresh", "jti": jti, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), jti, expires_at


def decode_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Session invalide.") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Type de jeton invalide.")
    return payload


def authenticate_with_password(db: Session, username: str, password: str) -> User:
    user = (
        db.query(User)
        .filter(User.username == username, User.is_active.is_(True))
        .first()
    )
    # Message identique que le compte n'existe pas ou que le mot de passe
    # soit faux : sinon on offre un oracle d'énumération des comptes.
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants invalides.")
    _touch_last_login(db, user)
    return user


def authenticate_with_pin(db: Session, pin: str) -> User:
    user = (
        db.query(User)
        .filter(User.pin_hash == hash_pin(pin), User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Code PIN invalide.")
    _touch_last_login(db, user)
    return user


def _touch_last_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.commit()


def set_password(db: Session, user_id: int, new_password: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def set_pin(db: Session, user_id: int, new_pin: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.pin_hash = hash_pin(new_pin)
    db.commit()
    db.refresh(user)
    return user
