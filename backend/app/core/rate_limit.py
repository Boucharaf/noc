"""
Limitation de débit par IP et utilisateur, fenêtre fixe d'une minute, dans Redis.

Échoue en mode ouvert : si Redis est indisponible, la requête passe. La
disponibilité du dashboard prime sur l'application stricte du quota.
"""
import logging
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

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


def request_scope(request: Request) -> str:
    return "read" if request.method in {"GET", "HEAD"} else "write"


def enforce_rate_limit(scope: str, limit: int, identity_type: str, identity: str) -> None:
    if not RATE_LIMIT_ENABLED:
        return
    window = int(time.time() // 60)
    key = f"ratelimit:{scope}:{identity_type}:{identity}:{window}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60)
    except RedisError as exc:
        logger.warning("Contrôle de débit indisponible (%s), requête acceptée : %s", key, exc)
        return
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Limite de débit dépassée ({limit} requêtes/min)",
            headers={"Retry-After": "60"},
        )


async def rate_limit_middleware(request: Request, call_next):
    if (
        not request.url.path.startswith("/api/")
        or request.method == "OPTIONS"
        or not RATE_LIMIT_ENABLED
    ):
        return await call_next(request)

    scope = request_scope(request)
    limit = RATE_LIMIT_READ_PER_MIN if scope == "read" else RATE_LIMIT_WRITE_PER_MIN
    try:
        await run_in_threadpool(enforce_rate_limit, scope, limit, "ip", client_ip(request))
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    return await call_next(request)
