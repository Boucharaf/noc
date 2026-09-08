"""
Publie l'état de la dernière collecte de chaque outil dans Redis, exposé
ensuite par le backend via GET /api/interop/status.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import redis

_redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
_STATUS_KEY_PREFIX = "noc:etl:status:"


def publish_status(tool: str, ok: bool, **counts):
    payload = {
        "tool": tool,
        "ok": ok,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        **counts,
    }
    _redis_client.set(f"{_STATUS_KEY_PREFIX}{tool}", json.dumps(payload))


def get_all_status() -> dict[str, dict]:
    keys = _redis_client.keys(f"{_STATUS_KEY_PREFIX}*")
    result = {}
    for key in keys:
        tool = key.decode().removeprefix(_STATUS_KEY_PREFIX)
        raw = _redis_client.get(key)
        if raw:
            result[tool] = json.loads(raw)
    return result
