"""
Nagios collector — `statusjson.cgi?query=hostlist` (cahier des charges §6.2).

Auth: Basic (NAGIOS_USER/NAGIOS_PASSWORD) and/or an X-Auth-Token header
(NAGIOS_API_KEY). This polls current host *status* rather than an event log,
so a host that stays DOWN is reported on every poll with the same stable
external_id — the backend deduplicates open incidents on
(source_tool, external_id).

Asks for `details=true`, which turns each hostlist entry from a bare status
code into the host's full status record. Two fields there matter: the outage
is dated from Nagios' own `last_state_change` rather than from the moment we
happened to poll — a host already DOWN when collection starts would otherwise
have all the downtime before the first poll erased from its KPIs — and
`plugin_output` carries the check's actual message. Servers too old to support
`details` still return the bare code, which is read as before (with the poll
time standing in for the transition, since nothing better is on offer).

Nagios publishes no address for a host here, so unlike the other collectors
matching is by name only: name the hosts after their node code.
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
    auth = (config.NAGIOS_USER, config.NAGIOS_PASSWORD) if config.NAGIOS_USER else None
    r = requests.get(
        url,
        params={"query": "hostlist", "details": "true"},
        headers=headers,
        auth=auth,
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    hostlist = r.json().get("data", {}).get("hostlist", {})

    now = datetime.now(timezone.utc)
    results = []
    for host, entry in hostlist.items():
        # With details=true each entry is the host's status record; without it
        # (older Nagios) it is the bare status code.
        detail = entry if isinstance(entry, dict) else {}
        # statusjson.cgi bitmask host states: 1=PENDING, 2=UP, 4=DOWN, 8=UNREACHABLE
        state = int(detail.get("status", entry) if detail else entry)
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
        # Milliseconds since the epoch, and 0 when Nagios has never seen the
        # host change state — in which case the poll time is all we have.
        changed = detail.get("last_state_change") or 0
        detected = (
            datetime.fromtimestamp(changed / 1000, tz=timezone.utc) if changed else now
        )
        results.append(
            {
                "node_code": node_code,
                "source_tool": "nagios",
                # Stable while the outage lasts → deduplicated by the backend.
                "external_id": f"nagios-{host}-down",
                "severity": severity,
                "detected_at": detected.isoformat(),
                "description": detail.get("plugin_output")
                or f"{label} — {host} (Nagios)",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
