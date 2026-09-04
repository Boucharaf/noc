"""
Nagios collector — `statusjson.cgi` (hostlist, servicelist, hostdowntimelist).

Auth: Basic (NAGIOS_USER/NAGIOS_PASSWORD) and/or an X-Auth-Token header
(NAGIOS_API_KEY). This polls current status rather than an event log, so a
host/service that stays down is reported on every poll with the same stable
external_id — the backend deduplicates open incidents on
(source_tool, external_id).

Three signals, same reasoning as the Zabbix/Centreon collectors:

  * fetch_events()               -> fact_incident rows from host status
  * fetch_service_availability() -> individual service checks (interfaces,
                                     disks, processes...) going CRITICAL
                                     without the parent host itself going
                                     DOWN — this is the "interfaces DOWN"
                                     KPI that host-level status alone misses
  * fetch_maintenance_windows()  -> hosts currently under a scheduled
                                     downtime

Nagios publishes no address here, so unlike the other collectors matching is
by name only: name the hosts (and, for services, their parent host) after
their node code.

hostlist/details=true is confirmed against a real instance. servicelist and
hostdowntimelist below follow Nagios Core's documented statusjson.cgi shapes
but haven't been checked against a real response the way hostlist has —
verify the field names (particularly the servicelist nesting and the
downtime bitmask) against your server before trusting either for a
production KPI.
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import build_node_index, match_node, skip_unmatched

logger = logging.getLogger(__name__)

_CGI_PATH = "/cgi-bin/statusjson.cgi"

# statusjson.cgi service state bitmask: 1=PENDING, 2=OK, 4=WARNING,
# 8=UNKNOWN, 16=CRITICAL.
_SERVICE_SEVERITY = {16: "critical", 8: "high", 4: "medium"}


def _get(query: str, **params) -> dict:
    headers = {}
    if config.NAGIOS_API_KEY:
        headers["X-Auth-Token"] = config.NAGIOS_API_KEY
    auth = (config.NAGIOS_USER, config.NAGIOS_PASSWORD) if config.NAGIOS_USER else None
    r = requests.get(
        f"{config.NAGIOS_API_URL.rstrip('/')}{_CGI_PATH}",
        params={"query": query, **params},
        headers=headers,
        auth=auth,
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json().get("data", {})


def fetch_events(nodes: list[dict]) -> list[dict]:
    hostlist = _get("hostlist", details="true").get("hostlist", {})

    now = datetime.now(timezone.utc)
    index = build_node_index(nodes)
    results = []
    for host, entry in hostlist.items():
        # With details=true each entry is the host's status record; without
        # it (older Nagios) it is the bare status code.
        detail = entry if isinstance(entry, dict) else {}
        raw_status = detail.get("status") if detail else entry
        if raw_status is None:
            # Only reachable if `entry` is a dict missing "status" —
            # previously this fell back to int(entry) here and crashed the
            # whole poll on one malformed host record instead of skipping it.
            logger.warning("[nagios] host %r has no status field, skipping", host)
            continue
        # statusjson.cgi bitmask host states: 1=PENDING, 2=UP, 4=DOWN, 8=UNREACHABLE
        state = int(raw_status)
        if state == 4:
            severity, label = "critical", "Hôte DOWN"
        elif state == 8:
            severity, label = "high", "Hôte UNREACHABLE"
        else:
            continue  # UP / PENDING
        node_code = match_node(nodes, host, index=index)
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


def fetch_service_availability(nodes: list[dict]) -> list[dict]:
    """Service-level checks (interfaces, disks, processes...) in trouble.

    A parent host can be UP while one of its services — a specific
    interface, a disk, a process — is CRITICAL or UNKNOWN. fetch_events()
    never sees this: it only looks at host status. This closes that gap for
    an "interfaces DOWN" KPI, using the same stable-external_id dedup
    pattern as every other signal here.
    """
    servicelist = _get("servicelist", details="true").get("servicelist", {})

    index = build_node_index(nodes)
    results = []
    for host, services in (servicelist or {}).items():
        node_code = match_node(nodes, host, index=index)
        if node_code is None:
            skip_unmatched("nagios", host)
            continue
        for service_name, entry in (services or {}).items():
            detail = entry if isinstance(entry, dict) else {}
            raw_status = detail.get("status") if detail else entry
            if raw_status is None:
                continue
            severity = _SERVICE_SEVERITY.get(int(raw_status))
            if severity is None:
                continue  # OK / PENDING
            changed = detail.get("last_state_change") or 0
            detected = (
                datetime.fromtimestamp(changed / 1000, tz=timezone.utc)
                if changed
                else datetime.now(timezone.utc)
            )
            results.append(
                {
                    "node_code": node_code,
                    "source_tool": "nagios",
                    "external_id": f"nagios-{host}-{service_name}",
                    "severity": severity,
                    "detected_at": detected.isoformat(),
                    "description": detail.get("plugin_output")
                    or f"{service_name} — {host} (Nagios)",
                    "cause_category": None,
                    "cause_label": None,
                }
            )
    return results


def fetch_maintenance_windows(nodes: list[dict]) -> list[dict]:
    """Hosts currently inside an active scheduled downtime."""
    downtimes = _get("hostdowntimelist").get("hostdowntimelist", {})

    now_ts = datetime.now(timezone.utc).timestamp()
    index = build_node_index(nodes)
    results = []
    for _id, dt in (downtimes or {}).items():
        if not isinstance(dt, dict):
            continue
        start = dt.get("start_time") or 0
        end = dt.get("end_time") or 0
        if not (start / 1000 <= now_ts <= end / 1000):
            continue  # scheduled but not active right now, or malformed
        host = dt.get("host_name", "")
        node_code = match_node(nodes, host, index=index)
        if node_code is None:
            skip_unmatched("nagios", host)
            continue
        results.append(
            {
                "node_code": node_code,
                "source_tool": "nagios",
                "maintenance_name": dt.get("comment") or "Downtime Nagios",
                "active_since": datetime.fromtimestamp(
                    start / 1000, tz=timezone.utc
                ).isoformat(),
                "active_till": datetime.fromtimestamp(
                    end / 1000, tz=timezone.utc
                ).isoformat(),
            }
        )
    return results