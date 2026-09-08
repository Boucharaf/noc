"""Cache Redis des agrégats KPI.

Avale volontairement les erreurs Redis : un KPI est recalculable, une
panne de cache ne doit jamais faire tomber le dashboard. C'est
exactement l'inverse du choix fait dans core/session_store.py, où avaler
une erreur reviendrait à considérer une session révoquée comme valide.
"""
import json
import logging
from typing import Any

from app.core.config import CACHE_TTL
from app.db.redis_client import redis_client

logger = logging.getLogger(__name__)


def get_cached(key: str) -> Any | None:
    try:
        raw = redis_client.get(key)
    except Exception as exc:
        logger.warning("Lecture Redis échouée pour %s : %s", key, exc)
        return None
    return json.loads(raw) if raw else None


def set_cached(key: str, value: Any, ttl: int = CACHE_TTL) -> None:
    try:
        redis_client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        logger.warning("Écriture Redis échouée pour %s : %s", key, exc)


def invalidate_prefix(prefix: str) -> None:
    try:
        for key in redis_client.scan_iter(match=f"{prefix}*"):
            redis_client.delete(key)
    except Exception as exc:
        logger.warning("Invalidation Redis échouée pour le préfixe %s : %s", prefix, exc)
