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


def _bcrypt_input(password: str) -> bytes:
    """Les 72 premiers octets du mot de passe : la limite de bcrypt.

    bcrypt 4 les tronquait sans le dire ; bcrypt 5 lève une erreur au-delà.
    Tronquer ici garde le comportement d'avant : les empreintes déjà en base
    restent valables, et un mot de passe long (jusqu'à 256 caractères
    acceptés) ne produit pas d'erreur 500.
    """
    return password.encode()[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_bcrypt_input(password), password_hash.encode())
    except ValueError:
        # Empreinte stockée dans un format non bcrypt (compte importé,
        # colonne remplie à la main) : refus, jamais d'exception 500.
        return False


DEVICE_COOKIE_NAME = "noc_device"


def _device_signature(device_id: str, issued: int) -> str:
    # Même garde que hash_pin : sans secret, la signature ne protège rien.
    if len(JWT_SECRET) < 32:
        raise RuntimeError("SECRET_KEY absente ou trop courte : poste reconnu impossible.")
    return hmac.new(
        JWT_SECRET.encode(), f"device:{device_id}:{issued}".encode(), hashlib.sha256
    ).hexdigest()


def create_device_token(now: int | None = None) -> str:
    """Jeton de poste reconnu : « identifiant.émission.signature ».

    Signé avec SECRET_KEY : il ne peut être ni fabriqué ni prolongé côté
    navigateur. Il ne désigne aucun compte — il atteste seulement qu'un mot
    de passe valide a été saisi sur ce navigateur.
    """
    import secrets
    import time

    device_id = secrets.token_urlsafe(16)
    issued = int(now if now is not None else time.time())
    return f"{device_id}.{issued}.{_device_signature(device_id, issued)}"


def is_known_device(token: str | None, max_age_days: int, now: int | None = None) -> bool:
    """Vrai si le jeton est intact (signature) et pas trop ancien."""
    import time

    if not token or token.count(".") != 2 or len(JWT_SECRET) < 32:
        return False
    device_id, issued_text, signature = token.split(".")
    try:
        issued = int(issued_text)
    except ValueError:
        return False
    if not hmac.compare_digest(signature, _device_signature(device_id, issued)):
        return False
    current = int(now if now is not None else time.time())
    return 0 <= current - issued <= max_age_days * 86400


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


def authenticate_with_pin(db: Session, username: str, pin: str) -> User:
    """Le PIN est vérifié pour le compte DÉSIGNÉ (A02). Même erreur que le
    compte soit inconnu, sans PIN ou que le code soit faux."""
    user = (
        db.query(User)
        .filter(User.username == username.strip(), User.is_active.is_(True))
        .first()
    )
    stored = (user.pin_hash if user is not None else None) or ""
    valid = hmac.compare_digest(stored, hash_pin(pin))
    legacy = hmac.compare_digest(stored, _legacy_pin_hash(pin))
    if user is None or not (valid or legacy):
        raise HTTPException(status_code=401, detail="Identifiant ou code PIN invalide.")
    if legacy:
        # Migration au fil de l'eau : l'empreinte non salée disparaît à la
        # première connexion réussie, enregistrée par _touch_last_login.
        user.pin_hash = hash_pin(pin)
    _touch_last_login(db, user)
    return user


def _touch_last_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.commit()


def find_for_password_reset(db: Session, identifier: str) -> User | None:
    """Compte ACTIF désigné par son identifiant ou son adresse électronique
    (sans tenir compte de la casse), ou None. Une adresse partagée par
    plusieurs comptes ne désigne personne : on ne choisit pas au hasard."""
    from sqlalchemy import func

    needle = identifier.strip().lower()
    if not needle:
        return None
    by_name = (
        db.query(User)
        .filter(func.lower(User.username) == needle, User.is_active.is_(True))
        .first()
    )
    if by_name is not None:
        return by_name
    matches = (
        db.query(User)
        .filter(func.lower(User.email) == needle, User.is_active.is_(True))
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def set_password(db: Session, user_id: int, new_password: str,
                 provisional: bool = False) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = provisional
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
