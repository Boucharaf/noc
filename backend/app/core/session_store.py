import hashlib
import logging
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
# Instant (en secondes) avant lequel les jetons d'accès d'un compte sont
# refusés. Sans lui, un jeton d'accès volé resterait valable jusqu'à son
# expiration, même après une réinitialisation de mot de passe.
ACCESS_REVOKED_KEY = "access_revoked_before:{user_id}"

FAILURES_KEY = "auth_failures:{scope}:{subject}"
LOCK_KEY = "auth_locked:{scope}:{subject}"

PIN_MAX_ATTEMPTS = 5
PIN_LOCK_WINDOW_SECONDS = 15 * 60


def _ttl_seconds(expire_at) -> int:
    from datetime import datetime

    return max(1, int((expire_at - datetime.now(UTC)).total_seconds()))


def store_refresh_session(user_id: int, jti: str, expire_at) -> None:
    ttl = _ttl_seconds(expire_at)
    redis_client.set(REFRESH_KEY.format(jti=jti), user_id, ex=ttl)
    redis_client.sadd(USER_SESSIONS_KEY.format(user_id=user_id), jti)


def is_refresh_session_valid(jti: str, user_id: int) -> bool:
    stored_user_id = redis_client.get(REFRESH_KEY.format(jti=jti))
    return stored_user_id is not None and int(stored_user_id) == user_id


def rotate_refresh_session(old_jti: str, user_id: int, new_jti: str, new_expire_at) -> None:
    """Invalide l'ancien jti et enregistre le nouveau. Appelé uniquement
    après validation de old_jti : un ancien refresh token rejoué après
    rotation retombera sur is_refresh_session_valid() == False."""
    redis_client.delete(REFRESH_KEY.format(jti=old_jti))
    redis_client.srem(USER_SESSIONS_KEY.format(user_id=user_id), old_jti)
    store_refresh_session(user_id, new_jti, new_expire_at)


def revoke_refresh_session(jti: str, user_id: int) -> None:
    redis_client.delete(REFRESH_KEY.format(jti=jti))
    redis_client.srem(USER_SESSIONS_KEY.format(user_id=user_id), jti)


def revoke_all_sessions(user_id: int) -> None:
    """POST /users/{id}/revoke-sessions (Directeur), et réutilisation
    détectée d'un refresh token déjà tourné/révoqué (vol probable : on tue
    toutes les sessions du compte par précaution, pas juste celle rejouée).

    Les jetons d'accès déjà émis tombent aussi, sans attendre leur
    expiration. La marque n'a pas à survivre au plus long d'entre eux.
    """
    key = USER_SESSIONS_KEY.format(user_id=user_id)
    jtis = redis_client.smembers(key)
    if jtis:
        redis_client.delete(*(REFRESH_KEY.format(jti=j) for j in jtis))
    redis_client.delete(key)
    redis_client.set(
        ACCESS_REVOKED_KEY.format(user_id=user_id),
        int(time.time()),
        ex=JWT_EXPIRATION_MINUTES * 60 + 60,
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


# --- Rate-limiting du PIN, par IP -------------------------------------------
# Par IP et non par user_id : authenticate_with_pin() retrouve l'utilisateur
# PAR l'empreinte du PIN (voir auth_service.hash_pin), donc en cas d'échec on
# ne sait pas quel compte visait la tentative. C'est aussi la limite correcte
# à poser : elle protège contre le brute-force en ligne depuis une même
# source, ce qui est le risque réel pour un PIN court sur une console
# partagée.

def is_pin_locked(ip: str) -> int | None:
    """Retourne le TTL restant en secondes si verrouillé, sinon None."""
    return lock_ttl("pin_ip", ip)


def register_pin_failure(ip: str) -> None:
    register_failure("pin_ip", ip, PIN_MAX_ATTEMPTS, PIN_LOCK_WINDOW_SECONDS)


def clear_pin_failures(ip: str) -> None:
    clear_failures("pin_ip", ip)
