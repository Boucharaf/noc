"""Authentification : mots de passe, PIN, jetons JWT."""
import hashlib
import hmac
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

# Empreinte d'un mot de passe que personne ne connaît, vérifiée quand le
# compte demandé n'existe pas. Sans elle, « compte inconnu » répond en une
# milliseconde et « mauvais mot de passe » en deux cents : le chronomètre
# suffirait à énumérer les identifiants, malgré le message identique.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt()).decode()


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
    """HMAC-SHA256 du PIN, clé = SECRET_KEY.

    Déterministe, pour permettre la recherche du compte PAR l'empreinte : le
    PIN se saisit sans identifiant, un sel aléatoire l'interdirait. La clé
    secrète conserve cette recherche tout en rendant la colonne inutile à qui
    la vole sans le secret — l'espace des PIN s'énumère en une fraction de
    seconde contre un SHA-256 nu, pas contre un HMAC dont on ignore la clé.

    À savoir : changer SECRET_KEY invalide tous les PIN, qu'il faut alors
    redéfinir depuis l'écran Utilisateurs.

    Le PIN reste un facteur faible : voir la restriction de rôle dans
    routes/auth.py (PIN_LOGIN_ALLOWED_ROLES) et le verrouillage par IP dans
    core/session_store.py.
    """
    if len(JWT_SECRET) < 32:
        # Sans clé, l'empreinte redeviendrait énumérable — et différente de
        # celle calculée par le backend, ce qui rendrait le PIN inutilisable
        # sans le moindre message.
        raise RuntimeError("SECRET_KEY absente ou trop courte : empreinte de PIN impossible.")
    return hmac.new(JWT_SECRET.encode(), pin.encode(), hashlib.sha256).hexdigest()


def _legacy_pin_hash(pin: str) -> str:
    """Ancien format (SHA-256 non salé), relu une fois pour migrer le PIN."""
    return hashlib.sha256(pin.encode()).hexdigest()


def pin_in_use(db: Session, pin: str, exclude_user_id: int | None = None) -> bool:
    """Un PIN désigne le compte à lui seul : deux comptes actifs qui le
    partageraient, et le premier trouvé ouvrirait la session de l'autre."""
    query = db.query(User.id).filter(
        User.pin_hash.in_((hash_pin(pin), _legacy_pin_hash(pin))),
        User.is_active.is_(True),
    )
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.first() is not None


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "type": "access",
        # Sert à la révocation immédiate : session_store.is_access_token_revoked.
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRATION_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
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
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), jti, expires_at


def decode_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            # `iat` n'est pas exigé ici : les cookies émis avant son ajout
            # doivent rester valables jusqu'à leur expiration.
            options={"require": ["exp", "sub", "jti", "type"]},
        )
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
    # soit faux : sinon on offre un oracle d'énumération des comptes. Même
    # durée aussi — voir _DUMMY_PASSWORD_HASH.
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Identifiants invalides.")
    if not verify_password(password, user.password_hash):
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
        user = (
            db.query(User)
            .filter(User.pin_hash == _legacy_pin_hash(pin), User.is_active.is_(True))
            .first()
        )
        if user is not None:
            # Migration au fil de l'eau : l'empreinte non salée disparaît à la
            # première connexion réussie, enregistrée par _touch_last_login.
            user.pin_hash = hash_pin(pin)
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
    if pin_in_use(db, new_pin, exclude_user_id=user_id):
        raise HTTPException(status_code=409, detail="Ce code PIN est déjà attribué à un autre compte.")
    user.pin_hash = hash_pin(new_pin)
    db.commit()
    db.refresh(user)
    return user
