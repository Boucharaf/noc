"""
Limitation de débit par IP, fenêtre fixe d'une minute, stockée dans Redis.

Échoue en mode ouvert : si Redis est indisponible, la requête passe. La
disponibilité du dashboard prime sur l'application stricte du quota.
"""
import logging
import time

from fastapi import HTTPException, Request

from app.core.config import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_READ_PER_MIN,
    RATE_LIMIT_WRITE_PER_MIN,
)
from app.db.redis_client import redis_sync as redis_client

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    # Derrière le reverse proxy nginx, l'IP réelle est dans X-Real-IP. On
    # peut s'y fier parce que nginx l'ÉCRASE avec $remote_addr et que le
    # backend n'est joignable que par lui (aucun port publié dans
    # docker-compose.yml) : publier le port du backend rendrait cet en-tête
    # falsifiable, et chaque verrouillage contournable.
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "unknown"
    )


def rate_limit(scope: str, limit: int):
    def dependency(request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        window = int(time.time() // 60)
        key = f"ratelimit:{scope}:{client_ip(request)}:{window}"
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, 60)
        except Exception as exc:
            logger.warning("Contrôle de débit indisponible (%s), requête acceptée : %s", key, exc)
            return
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Limite de débit dépassée ({limit} requêtes/min)",
                headers={"Retry-After": "60"},
            )

    return dependency


read_rate_limit = rate_limit("read", RATE_LIMIT_READ_PER_MIN)
write_rate_limit = rate_limit("write", RATE_LIMIT_WRITE_PER_MIN)
