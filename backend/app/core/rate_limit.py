"""
Limitation de débit par IP, fenêtre fixe d'une minute, stockée dans Redis.

Échoue en mode ouvert : si Redis est indisponible, la requête passe. La
disponibilité du dashboard prime sur l'application stricte du quota.
"""
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_READ_PER_MIN,
    RATE_LIMIT_WRITE_PER_MIN,
    RATE_LIMIT_USER_READ_PER_MIN,
    RATE_LIMIT_USER_WRITE_PER_MIN,
    TRUSTED_PROXY_IPS,
)
from app.db.redis_client import get_redis, redis_sync as redis_client

logger = logging.getLogger(__name__)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-real-ip")
    if peer in TRUSTED_PROXY_IPS and forwarded:
        return forwarded
    return peer or "unknown"


def rate_limit(scope: str, limit: int):
    def dependency(request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        window = int(time.time() // 60)
        key = f"ratelimit:{scope}:{client_ip(request)}:{window}"
        count = _increment_sync(key)
        if count is None:
            return
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Limite de débit dépassée ({limit} requêtes/min)",
                headers={"Retry-After": "60"},
            )

    return dependency


def _increment_sync(key: str) -> int | None:
    try:
        return int(redis_client.eval(_INCREMENT_SCRIPT, 1, key, 60))
    except Exception as exc:
        logger.warning(
            "Contrôle de débit indisponible (%s), requête acceptée : %s", key, exc
        )
        return None


async def _increment_async(key: str) -> int | None:
    try:
        redis_client_async = get_redis()
        return int(await redis_client_async.eval(_INCREMENT_SCRIPT, 1, key, 60))
    except Exception as exc:
        logger.warning(
            "Contrôle de débit indisponible (%s), requête acceptée : %s", key, exc
        )
        return None


async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not RATE_LIMIT_ENABLED or not request.url.path.startswith("/api/"):
        return await call_next(request)

    is_read = request.method in _SAFE_METHODS
    scope = "read" if is_read else "write"
    ip_limit = RATE_LIMIT_READ_PER_MIN if is_read else RATE_LIMIT_WRITE_PER_MIN
    user_limit = (
        RATE_LIMIT_USER_READ_PER_MIN if is_read else RATE_LIMIT_USER_WRITE_PER_MIN
    )
    window = int(time.time() // 60)

    checks = [(f"ratelimit:{scope}:{client_ip(request)}:{window}", ip_limit)]
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        from app.services.auth_service import decode_access_token

        try:
            payload = decode_access_token(authorization[7:].strip())
        except HTTPException:
            payload = None
        if payload and payload.get("sub"):
            checks.append(
                (f"ratelimit:user:{scope}:{payload['sub']}:{window}", user_limit)
            )

    for key, limit in checks:
        count = await _increment_async(key)
        if count is not None and count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Limite de débit dépassée ({limit} requêtes/min)"},
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


read_rate_limit = rate_limit("read", RATE_LIMIT_READ_PER_MIN)
write_rate_limit = rate_limit("write", RATE_LIMIT_WRITE_PER_MIN)
