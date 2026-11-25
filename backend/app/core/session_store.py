import hashlib
import logging
import os
import time
from datetime import UTC

from app.core.config import JWT_EXPIRATION_MINUTES
from app.db.redis_client import redis_sync as redis_client

logger = logging.getLogger(__name__)

# ⚠️ Ce module N'UTILISE PAS cache_service.py. cache_service avale les
# erreurs Redis par design ("Redis unavailable should never break the API"),
# ce qui est le bon choix pour du cache KPI recalculable. C'est le mauvais
# choix ici : si Redis est indisponible et qu'on avale l'erreur en
# considérant une session comme valide par défaut, un refresh token révoqué
# (logout, revoke-sessions) redeviendrait accepté tant que Redis reste down.
# Les opérations ci-dessous laissent donc les exceptions Redis remonter —
# une panne Redis fait légitimement échouer refresh/logout plutôt que de
# dégrader silencieusement la sécurité des sessions.
#
# UNE exception, argumentée sur place : is_access_token_revoked.

REFRESH_KEY = "refresh:{jti}"
USER_SESSIONS_KEY = "refresh_user:{user_id}"
ROTATED_REFRESH_KEY = "refresh_rotated:{jti}"
# Instant (en secondes) avant lequel les jetons d'accès d'un compte sont
# refusés. Sans lui, un jeton d'accès volé resterait valable jusqu'à son
# expiration, même après une réinitialisation de mot de passe.
ACCESS_REVOKED_KEY = "access_revoked_before:{user_id}"

FAILURES_KEY = "auth_failures:{scope}:{subject}"
LOCK_KEY = "auth_locked:{scope}:{subject}"

PIN_MAX_ATTEMPTS = 5
PIN_LOCK_WINDOW_SECONDS = 15 * 60
# Verrou GLOBAL du PIN (INC-43) : le verrou par IP n'arrête pas une
# énumération répartie sur plusieurs adresses. Au-delà de ce nombre d'échecs
# toutes IP confondues dans la fenêtre, la connexion par PIN est suspendue
# pour tout le monde ; la connexion par mot de passe reste ouverte.
PIN_GLOBAL_MAX_FAILURES = int(os.getenv("PIN_GLOBAL_MAX_FAILURES", "30"))

_STORE_REFRESH_SCRIPT = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SADD', KEYS[2], ARGV[3])
for _, jti in ipairs(redis.call('SMEMBERS', KEYS[2])) do
    if redis.call('EXISTS', ARGV[4] .. jti) == 0 then
        redis.call('SREM', KEYS[2], jti)
    end
end
return 1
"""

_ROTATE_REFRESH_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current then
    if redis.call('EXISTS', KEYS[4]) == 1 then
        return 1
    end
    return 0
end
if current ~= ARGV[1] then
    return 0
end

redis.call('DEL', KEYS[1])
redis.call('SREM', KEYS[2], ARGV[2])
redis.call('SET', KEYS[3], ARGV[1], 'EX', ARGV[3])
redis.call('SADD', KEYS[2], ARGV[4])
redis.call('SET', KEYS[4], ARGV[4], 'EX', ARGV[5])
for _, jti in ipairs(redis.call('SMEMBERS', KEYS[2])) do
    if redis.call('EXISTS', ARGV[6] .. jti) == 0 then
        redis.call('SREM', KEYS[2], jti)
    end
end
return 2
"""

_REVOKE_ONE_SCRIPT = """
redis.call('DEL', KEYS[1], KEYS[3])
redis.call('SREM', KEYS[2], ARGV[1])
return 1
"""

_REVOKE_ALL_SCRIPT = """
for _, jti in ipairs(redis.call('SMEMBERS', KEYS[1])) do
    redis.call('DEL', ARGV[1] .. jti)
end
redis.call('DEL', KEYS[1])
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
return 1
"""


def _ttl_seconds(expire_at) -> int:
    from datetime import datetime

    return max(1, int((expire_at - datetime.now(UTC)).total_seconds()))


def store_refresh_session(user_id: int, jti: str, expire_at) -> None:
    ttl = _ttl_seconds(expire_at)
    redis_client.eval(
        _STORE_REFRESH_SCRIPT,
        2,
        REFRESH_KEY.format(jti=jti),
        USER_SESSIONS_KEY.format(user_id=user_id),
        user_id,
        ttl,
        jti,
        "refresh:",
    )


def is_refresh_session_valid(jti: str, user_id: int) -> bool:
    stored_user_id = redis_client.get(REFRESH_KEY.format(jti=jti))
    return stored_user_id is not None and int(stored_user_id) == user_id


def rotate_refresh_session(
    old_jti: str, user_id: int, new_jti: str, new_expire_at
) -> str:
    """Fait une rotation atomique, en tolérant un bref doublon de requêtes."""
    result = redis_client.eval(
        _ROTATE_REFRESH_SCRIPT,
        4,
        REFRESH_KEY.format(jti=old_jti),
        USER_SESSIONS_KEY.format(user_id=user_id),
        REFRESH_KEY.format(jti=new_jti),
        ROTATED_REFRESH_KEY.format(jti=old_jti),
        user_id,
        old_jti,
        _ttl_seconds(new_expire_at),
        new_jti,
        5,
        "refresh:",
    )
    return {0: "invalid", 1: "recently_rotated", 2: "rotated"}.get(
        int(result), "invalid"
    )


def revoke_refresh_session(jti: str, user_id: int) -> None:
    redis_client.eval(
        _REVOKE_ONE_SCRIPT,
        3,
        REFRESH_KEY.format(jti=jti),
        USER_SESSIONS_KEY.format(user_id=user_id),
        ROTATED_REFRESH_KEY.format(jti=jti),
        jti,
    )


def revoke_all_sessions(user_id: int) -> None:
    """POST /users/{id}/revoke-sessions (Directeur), et réutilisation
    détectée d'un refresh token déjà tourné/révoqué (vol probable : on tue
    toutes les sessions du compte par précaution, pas juste celle rejouée).

    Les jetons d'accès déjà émis tombent aussi, sans attendre leur
    expiration. La marque n'a pas à survivre au plus long d'entre eux.
    """
    redis_client.eval(
        _REVOKE_ALL_SCRIPT,
        2,
        USER_SESSIONS_KEY.format(user_id=user_id),
        ACCESS_REVOKED_KEY.format(user_id=user_id),
        "refresh:",
        int(time.time()),
        JWT_EXPIRATION_MINUTES * 60 + 60,
    )


def is_access_token_revoked(user_id: int, issued_at) -> bool:
    """Vrai si le jeton d'accès a été émis avant une révocation du compte.

    Échoue en mode OUVERT, à l'inverse du reste du module : ce contrôle
    n'est qu'un raccourci. L'expiration du jeton, la relecture en base du
    rôle et du statut du compte, et le refus du rafraîchissement continuent
    de s'appliquer. Refuser toutes les requêtes parce que Redis hoquette
    éteindrait le NOC pour un gain de quelques minutes.

    `<=` et non `<` : un jeton émis dans la seconde même de la révocation
    est refusé. Au pire, le client rafraîchit sa session de façon
    transparente ; l'inverse laisserait passer un jeton d'avant révocation.
    """
    try:
        raw = redis_client.get(ACCESS_REVOKED_KEY.format(user_id=user_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Contrôle de révocation des jetons indisponible : %s", exc)
        return False
    if raw is None:
        return False
    try:
        return int(issued_at) <= int(raw)
    except (TypeError, ValueError):
        return True


# --- Verrouillage après échecs -----------------------------------------------
# Partagé par le PIN (par IP) et le mot de passe (par IP, par compte, par
# couple compte + IP — voir routes/auth.py). Le sujet est haché : un
# identifiant tapé par un inconnu n'a rien à faire en clair dans Redis, et la
# longueur des clés reste bornée.

def _subject(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def lock_ttl(scope: str, value: str) -> int | None:
    """Retourne le TTL restant en secondes si verrouillé, sinon None."""
    ttl = redis_client.ttl(LOCK_KEY.format(scope=scope, subject=_subject(value)))
    return ttl if ttl and ttl > 0 else None


def register_failure(scope: str, value: str, max_failures: int, window_seconds: int) -> None:
    subject = _subject(value)
    key = FAILURES_KEY.format(scope=scope, subject=subject)
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, window_seconds)
    if attempts >= max_failures:
        redis_client.set(LOCK_KEY.format(scope=scope, subject=subject), "1", ex=window_seconds)
        redis_client.delete(key)


def clear_failures(scope: str, value: str) -> None:
    redis_client.delete(FAILURES_KEY.format(scope=scope, subject=_subject(value)))


def clear_lock(scope: str, value: str) -> None:
    """Lève un verrou en cours et son compteur. Réservé à une preuve forte :
    réinitialisation du mot de passe par courriel."""
    subject = _subject(value)
    redis_client.delete(LOCK_KEY.format(scope=scope, subject=subject))
    clear_failures(scope, value)


# --- Verrouillage du PIN ------------------------------------------------------
# Trois compteurs : le compte désigné (un code court ne doit pas s'essayer
# depuis plusieurs adresses), l'adresse, et tous confondus.

def is_pin_locked(ip: str, username: str) -> int | None:
    """Retourne le TTL restant en secondes si verrouillé, sinon None."""
    remaining = [
        ttl for ttl in (
            lock_ttl("pin_user", username.strip().lower()),
            lock_ttl("pin_ip", ip), lock_ttl("pin_all", "*"),
        ) if ttl
    ]
    return max(remaining) if remaining else None


def register_pin_failure(ip: str, username: str) -> None:
    register_failure(
        "pin_user", username.strip().lower(), PIN_MAX_ATTEMPTS, PIN_LOCK_WINDOW_SECONDS
    )
    register_failure("pin_ip", ip, PIN_MAX_ATTEMPTS, PIN_LOCK_WINDOW_SECONDS)
    register_failure("pin_all", "*", PIN_GLOBAL_MAX_FAILURES, PIN_LOCK_WINDOW_SECONDS)


def clear_pin_failures(ip: str, username: str) -> None:
    clear_failures("pin_user", username.strip().lower())
    # Le compteur de l'adresse reste : un compte valide n'efface pas les
    # essais faits sur les autres.


# --- Réinitialisation du mot de passe par courriel --------------------------
# Le jeton envoyé par courriel n'est JAMAIS stocké en clair : seule son
# empreinte SHA-256 sert de clé. Une copie de Redis ne permet donc pas de
# réinitialiser un compte. Usage unique (GETDEL atomique), durée de vie
# courte, et une nouvelle demande annule la précédente.
PASSWORD_RESET_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "30")) * 60
PASSWORD_RESET_KEY = "pwreset:{digest}"
PASSWORD_RESET_USER_KEY = "pwreset_user:{user_id}"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def store_password_reset(user_id: int) -> str:
    """Crée le jeton de réinitialisation d'un compte et le rend (en clair,
    pour le courriel). L'éventuel jeton précédent du compte est annulé."""
    import secrets

    token = secrets.token_urlsafe(32)
    digest = _token_digest(token)
    user_key = PASSWORD_RESET_USER_KEY.format(user_id=user_id)
    previous = redis_client.get(user_key)
    if previous:
        if isinstance(previous, bytes):
            previous = previous.decode()
        redis_client.delete(PASSWORD_RESET_KEY.format(digest=previous))
    redis_client.set(PASSWORD_RESET_KEY.format(digest=digest), str(user_id),
                     ex=PASSWORD_RESET_TTL_SECONDS)
    redis_client.set(user_key, digest, ex=PASSWORD_RESET_TTL_SECONDS)
    return token


def consume_password_reset(token: str) -> int | None:
    """Identifiant du compte si le jeton est valide, None sinon. Le jeton est
    consommé dans la même opération : il ne sert qu'une fois."""
    if not token:
        return None
    value = redis_client.getdel(PASSWORD_RESET_KEY.format(digest=_token_digest(token)))
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode()
    try:
        user_id = int(value)
    except (TypeError, ValueError):
        return None
    redis_client.delete(PASSWORD_RESET_USER_KEY.format(user_id=user_id))
    return user_id
