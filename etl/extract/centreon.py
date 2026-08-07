"""
Centreon collector — REST API v2 monitoring resources (cahier des charges §6.3).

Centreon's primary integration is the broker webhook pushing straight to
POST /api/incidents/ingest (already supported by the backend); this poller is
the batch complement (§2.2 "Batch 5 min") and a safety net if webhooks are
not configured.

Auth: either a static token (CENTREON_API_KEY → X-AUTH-TOKEN header) or a
/login call with CENTREON_USER/CENTREON_PASSWORD.
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

# §6.3 filter: status IN (2, 3) — Critical + Unknown
STATUS_SEVERITY = {"CRITICAL": "critical", "UNKNOWN": "high", "DOWN": "critical"}


def _base_url() -> str:
    return config.CENTREON_API_URL.rstrip("/")


def _auth_token() -> str:
    if config.CENTREON_API_KEY:
        return config.CENTREON_API_KEY
    r = requests.post(
        f"{_base_url()}/login",
        json={
            "security": {
                "credentials": {
                    "login": config.CENTREON_USER,
                    "password": config.CENTREON_PASSWORD,
                }
            }
        },
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()["security"]["token"]


def fetch_events(nodes: list[dict], since: datetime) -> list[dict]:
    token = _auth_token()
    r = requests.get(
        f"{_base_url()}/monitoring/resources",
        headers={"X-AUTH-TOKEN": token},
        params={
            "states": '["unhandled_problems"]',
            "statuses": '["CRITICAL","UNKNOWN","DOWN"]',
            "limit": 100,
        },
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    resources = r.json().get("result", [])

    results = []
    for res in resources:
        status_name = (res.get("status") or {}).get("name", "").upper()
        severity = STATUS_SEVERITY.get(status_name)
        if severity is None:
            continue
        # A host resource carries the configured host name in `name` — which is
        # where the node code goes (see the image README) — and a free-text
        # label in `alias`; either may be what the CMDB knows the node by, so
        # both are offered rather than letting a non-empty alias hide the name.
        # For a service the parent host is what identifies the node, so it goes
        # first; that service's own name/alias simply won't match anything.
        parent = (res.get("parent") or {}).get("name") or ""
        host = parent or res.get("name") or res.get("alias") or ""
        node_code = match_node(
            nodes,
            parent,
            res.get("name", ""),
            res.get("alias", ""),
            res.get("fqdn", ""),
        )
        if node_code is None:
            skip_unmatched("centreon", host)
            continue
        changed = res.get("last_status_change")
        detected = (
            datetime.fromisoformat(changed)
            if changed
            else datetime.now(timezone.utc)
        )
        results.append(
            {
                "node_code": node_code,
                "source_tool": "centreon",
                "external_id": f"centreon-{res.get('type', 'resource')}-{res.get('id')}-{status_name.lower()}",
                "severity": severity,
                "detected_at": detected.isoformat(),
                "description": res.get("information") or f"{status_name} — {host} (Centreon)",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
