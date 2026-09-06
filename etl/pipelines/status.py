"""Publishes the outcome of each collection pass for the dashboard to read.

`collect_supervision` already knows, per tool, whether the last poll reached
the supervision API and what it brought back; until now that only reached the
worker log, where nobody looks until something is obviously wrong. A tool whose
credentials have expired keeps failing every pass in silence.

The result of every pass is written to one Redis key, which the backend serves
from GET /api/interop/status. Redis rather than the database because this is
liveness, not history: it is rewritten every pass, worth nothing once stale,
and must not put a write on the incident tables every five minutes.

The key carries a TTL of several poll intervals. If the worker dies, the key
expires and the dashboard reports the collectors as stale rather than
indefinitely showing the last result as though it were current — the failure
mode that makes a status display worse than none.
"""

import json
import logging
from datetime import datetime, timezone

import redis

import config

logger = logging.getLogger(__name__)

STATUS_KEY = "noc:collector:status"
# Survive a couple of missed passes before the status is declared stale, so a
# single slow or skipped tick does not flap the dashboard.
STATUS_TTL_S = max(config.COLLECT_INTERVAL_S * 3, 60)

_redis = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=2,
)


def publish_collector_status(stats: dict, key_suffix: str | None = None) -> None:
    """Record one pass. `stats` is what collect_supervision (or one of the
    other collection tasks) returns.

    `key_suffix` writes to a separate Redis key (`noc:collector:status:<suffix>`)
    instead of the main one — used by collect_metrics so a metrics-poll
    failure doesn't overwrite/blend with the incidents-poll status that
    GET /api/interop/status was built to report on.
    """
    key = f"{STATUS_KEY}:{key_suffix}" if key_suffix else STATUS_KEY
    payload = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": config.COLLECT_INTERVAL_S,
        "tools": stats,
    }
    try:
        _redis.set(key, json.dumps(payload), ex=STATUS_TTL_S)
    except redis.RedisError as exc:
        # Never let status reporting break collection — the incidents matter
        # more than the display of how they were gathered.
        logger.warning("Collector status publish failed: %s", exc)
