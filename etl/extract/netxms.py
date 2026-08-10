"""
NetXMS collector — REST API v1.

Targets the NetXMS web API daemon v1 REST API: POST {url}/v1/login with
{"username", "password"} returns a bearer token (short-lived, not cached —
we log in on every poll, matching the zabbix/centreon collectors), which
authenticates GET {url}/v1/alarms — a flat list of
{id, severity, state, source, message, lastChangeTime}. `source` is the
numeric id of the object (usually a Node) the alarm was raised on, and has to
be resolved to a name and address before it can be matched to a node.

Resolution deliberately uses two endpoints. GET {url}/v1/objects returns the
object tree in one request, but what it actually contains depends on the
server's configuration: on the instances this was built against it yields only
the handful of root containers and no Nodes at all, so relying on it alone
means no alarm ever resolves and every one is skipped as unmatched — a silent
failure that reads like an empty CMDB. Ids it does not cover are therefore
fetched one at a time from GET {url}/v1/objects/{id} and cached in Redis
across polls (see the object identity cache below — without it a pass costs
one request per distinct alarm source, every five minutes, forever). An id
neither endpoint resolves falls back to matching on the raw number, which
normally misses and is logged and skipped like any other unknown host.

Not every alarm comes from a host: on the ANPTIC instance about one in eight
distinct sources is a BusinessService rather than a Node. Those are skipped
silently — see HOST_CLASSES.

Active alarms are polled, so an alarm that stays active keeps its (stable)
alarm id — the backend deduplicates open incidents on
(source_tool, external_id).

dim_node rows for the real inventory are created by provision_netxms_nodes.py;
without them every alarm is reported as an unmatched host.
"""

import json
import logging
from datetime import datetime, timezone

import redis
import requests

import config
from extract.common import match_node, skip_unmatched
from transform.causes import classify

logger = logging.getLogger(__name__)

# NetXMS severities 0–4: NORMAL, WARNING, MINOR, MAJOR, CRITICAL
SEVERITY_MAP = {0: "low", 1: "medium", 2: "medium", 3: "high", 4: "critical"}

# NetXMS alarm states: 0=outstanding, 1=acknowledged, 2=terminated/resolved
TERMINATED_STATE = 2

# Object classes that stand for a piece of equipment, i.e. that a dim_node can
# plausibly exist for. Anything else raising an alarm (BusinessService,
# Container, ...) is not a host and is skipped without a warning.
HOST_CLASSES = {"Node", "Cluster", "MobileDevice", "AccessPoint", "Sensor", "Chassis"}

# ── object identity cache ───────────────────────────────────────────────────
# Resolving alarm sources is by far the most expensive part of a poll: because
# /v1/objects lists only the root containers (see the module docstring), each
# distinct source costs its own GET /v1/objects/{id}. On the ANPTIC instance
# that is ~1180 requests per pass, and with a five-minute interval ~340k
# requests a day spent re-reading names and IP addresses that essentially never
# change.
#
# Redis rather than a process-local dict: the worker runs with concurrency 2,
# so a local cache is duplicated per process and thrown away on every restart
# and redeploy — precisely when a cold pass is most expensive.
#
# Only successful resolutions are stored. Caching a failure would let one
# transient error hide a host for the whole TTL, and failures are rare enough
# that retrying next pass costs nothing.
_OBJECT_KEY = "noc:netxms:object:{}"

_redis = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=2,
)


def _cached_object(source_id) -> tuple[str, str, str] | None:
    try:
        raw = _redis.get(_OBJECT_KEY.format(source_id))
    except redis.RedisError as exc:
        # Degrade to the uncached path rather than failing the poll: a Redis
        # outage should cost latency, not incidents.
        logger.warning("[netxms] object cache unavailable: %s", exc)
        return None
    if not raw:
        return None
    try:
        name, ip, klass = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return name, ip, klass


def _cache_object(source_id, resolved: tuple[str, str, str]) -> None:
    try:
        _redis.set(
            _OBJECT_KEY.format(source_id),
            json.dumps(resolved),
            ex=config.NETXMS_OBJECT_CACHE_TTL_S,
        )
    except redis.RedisError:
        pass


def _login() -> str:
    r = requests.post(
        f"{config.NETXMS_API_URL.rstrip('/')}/v1/login",
        json={"username": config.NETXMS_USER, "password": config.NETXMS_PASSWORD},
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()["token"]


def _get(path: str, token: str) -> dict | list:
    r = requests.get(
        f"{config.NETXMS_API_URL.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def _as_list(payload: dict | list, key: str) -> list:
    return payload.get(key, []) if isinstance(payload, dict) else payload


def _object_ip(obj: dict) -> str:
    """A Node's primary address — `ipAddress` is {family, address, prefixLength}."""
    addr = obj.get("ipAddress")
    if isinstance(addr, dict):
        return addr.get("address", "")
    return addr or ""


def _resolve_source(source_id, token: str, cache: dict) -> tuple[str, str, str]:
    """(name, ip, class) for an alarm's source object, "" for any part unknown.

    Only called for ids the /v1/objects listing didn't cover. Three layers, in
    order: the per-poll dict (many alarms share one source), the Redis cache
    (see above — this is what removes the ~1180 requests a pass), and finally
    the server.
    """
    if source_id in cache:
        return cache[source_id]

    resolved = _cached_object(source_id)
    if resolved is None:
        resolved = ("", "", "")
        try:
            obj = _get(f"/v1/objects/{source_id}", token)
            if isinstance(obj, dict):
                resolved = (obj.get("name", ""), _object_ip(obj), obj.get("class", ""))
                if resolved[0]:
                    _cache_object(source_id, resolved)
        except requests.RequestException as exc:
            logger.warning("[netxms] could not resolve object %s: %s", source_id, exc)

    cache[source_id] = resolved
    return resolved


def fetch_events(nodes: list[dict]) -> list[dict]:
    token = _login()

    objects = _as_list(_get("/v1/objects", token), "objects")
    listed = {
        obj.get("id"): (obj.get("name", ""), _object_ip(obj), obj.get("class", ""))
        for obj in objects
    }

    alarms = _as_list(_get("/v1/alarms", token), "alarms")

    resolved_cache: dict = {}
    results = []
    for alarm in alarms:
        if int(alarm.get("state", 0)) == TERMINATED_STATE:
            continue
        severity_raw = int(alarm.get("severity", alarm.get("currentSeverity", 1)))
        if severity_raw == 0:  # NORMAL — not an incident
            continue
        source_id = alarm.get("source") or alarm.get("sourceObjectId")
        name, ip, klass = listed.get(source_id) or _resolve_source(
            source_id, token, resolved_cache
        )
        # Alarms are also raised on objects that are not hosts at all — a
        # BusinessService going to "failed" is the usual one. They can never
        # match a dim_node, so they are dropped quietly: warning about them
        # would tell the operator to provision something unprovisionable,
        # every poll, for as long as the service stays down.
        if klass and klass not in HOST_CLASSES:
            continue
        host = name or str(source_id or "")
        node_code = match_node(nodes, host, ip)
        if node_code is None:
            skip_unmatched("netxms", host)
            continue
        detected_raw = alarm.get("lastChangeTime") or alarm.get("creationTime")
        if isinstance(detected_raw, str):
            detected = datetime.fromisoformat(detected_raw.replace("Z", "+00:00"))
        elif detected_raw is not None:
            detected = datetime.fromtimestamp(int(detected_raw), tz=timezone.utc)
        else:
            detected = datetime.now(timezone.utc)
        message = alarm.get("message") or "Alarme NetXMS"
        category, label = classify(message)
        results.append(
            {
                "node_code": node_code,
                "source_tool": "netxms",
                "external_id": f"netxms-alarm-{alarm.get('id')}",
                "severity": SEVERITY_MAP.get(severity_raw, "medium"),
                "detected_at": detected.isoformat(),
                "description": message,
                "cause_category": category,
                "cause_label": label,
            }
        )
    return results
