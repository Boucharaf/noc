"""
NetXMS collector — REST API v1 (cahier des charges §6, "NetXMS API").

Targets the NetXMS web API daemon v1 REST API: POST {url}/v1/login with
{"username", "password"} returns a bearer token (short-lived, not cached —
we log in on every poll, matching the zabbix/centreon collectors), which
authenticates GET {url}/v1/alarms — a flat list of
{id, severity, state, source, message, lastChangeTime}. `source` is the
numeric id of the object (usually a Node) the alarm was raised on; GET
{url}/v1/objects is used to resolve it to a name for node matching, on a
best-effort basis (it may not include every Node depending on server config —
an alarm whose source isn't in that list falls back to matching on the raw
numeric id, which will normally miss and get logged/skipped like any other
unmatched host).

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


def fetch_events(nodes: list[dict], since: datetime) -> list[dict]:
    token = _login()

    objects = _as_list(_get("/v1/objects", token), "objects")
    object_names = {obj.get("id"): obj.get("name", "") for obj in objects}

    alarms = _as_list(_get("/v1/alarms", token), "alarms")

    results = []
    for alarm in alarms:
        if int(alarm.get("state", 0)) == TERMINATED_STATE:
            continue
        severity_raw = int(alarm.get("severity", alarm.get("currentSeverity", 1)))
        if severity_raw == 0:  # NORMAL — not an incident
            continue
        source_id = alarm.get("source", alarm.get("sourceObjectId"))
        host = str(object_names.get(source_id) or source_id or "")
        node_code = match_node(nodes, host)
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
