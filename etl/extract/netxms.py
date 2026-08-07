"""
NetXMS collector — REST API v1 (cahier des charges §6, "NetXMS API").

Targets the NetXMS web API daemon v1 REST API: POST {url}/v1/login with
{"username", "password"} returns a bearer token (short-lived, not cached —
we log in on every poll, matching the zabbix/centreon collectors), which
authenticates GET {url}/v1/alarms — a flat list of
{id, severity, state, source, message, lastChangeTime}. `source` is the
numeric id of the object (usually a Node) the alarm was raised on, resolved to
a name (and IP) for node matching: GET {url}/v1/objects supplies the tree in
one call, but on the servers we target it returns only the root containers, so
any id missing from it is fetched individually with GET {url}/v1/objects/{id}.
An id that resolves to neither falls back to matching on the raw numeric id,
which will normally miss and get logged/skipped like any other unmatched host.

Active alarms are polled, so an alarm that stays active keeps its (stable)
alarm id — the backend deduplicates open incidents on
(source_tool, external_id).
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

# NetXMS severities 0–4: NORMAL, WARNING, MINOR, MAJOR, CRITICAL
SEVERITY_MAP = {0: "low", 1: "medium", 2: "medium", 3: "high", 4: "critical"}

# NetXMS alarm states: 0=outstanding, 1=acknowledged, 2=terminated/resolved
TERMINATED_STATE = 2


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


def _resolve_source(source_id, token: str, cache: dict) -> tuple[str, str]:
    """(name, ip) for an alarm's source object, "" for either when unknown.

    Only called for ids the /v1/objects listing didn't cover; the cache keeps
    it to one request per distinct source per poll, however many alarms share it.
    """
    if source_id in cache:
        return cache[source_id]
    resolved = ("", "")
    try:
        obj = _get(f"/v1/objects/{source_id}", token)
        if isinstance(obj, dict):
            resolved = (obj.get("name", ""), _object_ip(obj))
    except requests.RequestException as exc:
        logger.warning("[netxms] could not resolve object %s: %s", source_id, exc)
    cache[source_id] = resolved
    return resolved


def fetch_events(nodes: list[dict]) -> list[dict]:
    token = _login()

    objects = _as_list(_get("/v1/objects", token), "objects")
    listed = {obj.get("id"): (obj.get("name", ""), _object_ip(obj)) for obj in objects}

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
        name, ip = listed.get(source_id) or _resolve_source(
            source_id, token, resolved_cache
        )
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
        results.append(
            {
                "node_code": node_code,
                "source_tool": "netxms",
                "external_id": f"netxms-alarm-{alarm.get('id')}",
                "severity": SEVERITY_MAP.get(severity_raw, "medium"),
                "detected_at": detected.isoformat(),
                "description": alarm.get("message") or "Alarme NetXMS",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
