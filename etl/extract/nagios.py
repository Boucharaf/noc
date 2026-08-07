"""
Nagios collector — `statusjson.cgi?query=hostlist` (cahier des charges §6.2).

Auth: Basic (NAGIOS_USER/NAGIOS_PASSWORD) and/or an X-Auth-Token header
(NAGIOS_API_KEY). This polls current host *status* rather than an event log,
so a host that stays DOWN is reported on every poll with the same stable
external_id — the backend deduplicates open incidents on
(source_tool, external_id).
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

def fetch_events(nodes: list[dict]) -> list[dict]:
    url = f"{config.NAGIOS_API_URL.rstrip('/')}/cgi-bin/statusjson.cgi"
    headers = {}
    if config.NAGIOS_API_KEY:
        headers["X-Auth-Token"] = config.NAGIOS_API_KEY
    auth = (
        (config.NAGIOS_USER, config.NAGIOS_PASSWORD) if config.NAGIOS_USER else None
    )
    r = requests.get(
        url,
        params={"query": "hostlist"},
        headers=headers,
        auth=auth,
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    hostlist = r.json().get("data", {}).get("hostlist", {})

    now = datetime.now(timezone.utc)
    results = []
    for host, state in hostlist.items():
        # statusjson.cgi bitmask host states: 1=PENDING, 2=UP, 4=DOWN, 8=UNREACHABLE
        state = int(state)
        if state == 4:
            severity, label = "critical", "Hôte DOWN"
        elif state == 8:
            severity, label = "high", "Hôte UNREACHABLE"
        else:
            continue  # UP / PENDING
        node_code = match_node(nodes, host)
        if node_code is None:
            skip_unmatched("nagios", host)
            continue
        results.append(
            {
                "node_code": node_code,
                "source_tool": "nagios",
                # Stable while the outage lasts → deduplicated by the backend.
                "external_id": f"nagios-{host}-down",
                "severity": severity,
                "detected_at": now.isoformat(),
                "description": f"{label} — {host} (Nagios)",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
