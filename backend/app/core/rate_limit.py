"""
Per-IP fixed-window rate limiting backed by Redis: 100 req/min on read
endpoints, 10 req/min on /ingest.

The ingest limit is the tighter of the two because it is the only unauthenticated-
by-user path — a supervision tool holding the static API key — and because a
looping webhook is the realistic way this service gets flooded. Read traffic
comes from logged-in dashboards, which are bounded by how many people are
looking at them.

Fails open: if Redis is unavailable the request goes through — availability of
the dashboard matters more than strict quota enforcement.
"""
import logging
import time

from fastapi import HTTPException, Request

from app.core.constants import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_INGEST_PER_MIN,
    RATE_LIMIT_READ_PER_MIN,
)
from app.db.redis_client import redis_client

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    # Behind the nginx reverse proxy the real client is in X-Real-IP.
    return (
        request.headers.get("x-real-ip")
        or (request.client.host if request.client else "unknown")
    )


def rate_limit(scope: str, limit: int):
    def dependency(request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        window = int(time.time() // 60)
        key = f"ratelimit:{scope}:{_client_ip(request)}:{window}"
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, 60)
        except Exception as exc:
            logger.warning("Rate limit check failed (%s), allowing request: %s", key, exc)
            return
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests/min)",
                headers={"Retry-After": "60"},
            )

    return dependency


read_rate_limit = rate_limit("read", RATE_LIMIT_READ_PER_MIN)
ingest_rate_limit = rate_limit("ingest", RATE_LIMIT_INGEST_PER_MIN)
