import logging
from datetime import UTC

from app.db.redis_client import redis_client

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

REFRESH_KEY = "refresh:{jti}"
USER_SESSIONS_KEY = "refresh_user:{user_id}"

PIN_ATTEMPTS_KEY = "pin_attempts:ip:{ip}"
PIN_LOCK_KEY = "pin_locked:ip:{ip}"
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
    toutes les sessions du compte par précaution, pas juste celle rejouée)."""
    key = USER_SESSIONS_KEY.format(user_id=user_id)
    jtis = redis_client.smembers(key)
    if jtis:
        redis_client.delete(*(REFRESH_KEY.format(jti=j) for j in jtis))
    redis_client.delete(key)


# --- Rate-limiting du PIN, par IP -------------------------------------------
# Par IP et non par user_id : authenticate_with_pin() retrouve l'utilisateur
# PAR le hash du PIN (voir auth_service.hash_pin), donc en cas d'échec on ne
# sait pas quel compte visait la tentative. C'est aussi la limite correcte à
# poser : elle protège contre le brute-force en ligne depuis une même
# source, ce qui est le risque réel pour un PIN court sur une console
# partagée.

def is_pin_locked(ip: str) -> int | None:
    """Retourne le TTL restant en secondes si verrouillé, sinon None."""
    ttl = redis_client.ttl(PIN_LOCK_KEY.format(ip=ip))
    return ttl if ttl and ttl > 0 else None


def register_pin_failure(ip: str) -> None:
    key = PIN_ATTEMPTS_KEY.format(ip=ip)
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, PIN_LOCK_WINDOW_SECONDS)
    if attempts >= PIN_MAX_ATTEMPTS:
        redis_client.set(PIN_LOCK_KEY.format(ip=ip), "1", ex=PIN_LOCK_WINDOW_SECONDS)
        redis_client.delete(key)


def clear_pin_failures(ip: str) -> None:
    redis_client.delete(PIN_ATTEMPTS_KEY.format(ip=ip))
