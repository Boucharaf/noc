"""
Zabbix collector — JSON-RPC.

Auth: either a static API token (ZABBIX_API_TOKEN, Zabbix >= 5.4) or
`user.login` with ZABBIX_USER/ZABBIX_PASSWORD (token valid ~30 min, so we
log in on every poll rather than caching it).

This module reports Zabbix's *current state*, never a delta since the last
poll — every function here follows that contract, and the backend
deduplicates on (source_tool, external_id). See fetch_events()'s original
docstring reasoning for why "current state" beats time_from windows: it has
no look-back hole, no lost-on-ingest-failure hole, and re-reporting an open
item under a stable id is exactly what lets the backend collapse repeats.

Four independent signals are collected, because "the problems Zabbix has
open" is not the same as "is the NOC healthy":

  * fetch_events()               -> fact_incident rows (trigger problems)
  * fetch_host_availability()    -> is each node reachable right now
  * fetch_maintenance_windows()  -> which nodes/localities are under a
                                     declared maintenance window right now
  * fetch_operational_metrics()  -> CPU / RAM / bandwidth / latency snapshot

A host going unreachable does not always raise a trigger problem (missing
or misconfigured trigger, agent never checked in, etc.), so
fetch_host_availability() is not a subset of fetch_events() — both are
needed for an accurate "equipements DOWN" count.

Two API details drive the shape of the events path, both verified against
Zabbix 7.0 and neither obvious from the method name:

  * `problem.get` rejects `selectHosts`. It names the trigger in `objectid`
    instead, so the hosts have to be fetched separately with `trigger.get`.
  * `suppressed` marks a problem silenced by a maintenance window. Those are
    dropped from fetch_events(): somebody deliberately declared that outage
    uninteresting, and surfacing it anyway would put planned work into the
    availability figures. (The maintenance window itself is still worth
    reporting — that's what fetch_maintenance_windows() is for.)
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

# Zabbix trigger severities 0-5 -> dashboard severities
SEVERITY_MAP = {0: "low", 1: "low", 2: "medium", 3: "medium", 4: "high", 5: "critical"}

# Zabbix host.get "available" style fields: 0=unknown, 1=available, 2=unavailable
AVAILABILITY_MAP = {0: "unknown", 1: "up", 2: "down"}

# item key prefixes used to recognize an operational metric on a host.
# Zabbix templates vary a lot between vendors/OS — this is a best-effort
# default set. Override/extend via config.ZABBIX_ITEM_KEY_PATTERNS (same
# shape: {metric_name: [key_prefix, ...]}) once you know what your actual
# templates expose; do NOT trust this list blindly for production KPIs.
DEFAULT_ITEM_KEY_PATTERNS = {
    "cpu_pct": ["system.cpu.util"],
    "ram_pct": ["vm.memory.util", "vm.memory.size[pused]"],
    "bandwidth_in_bps": ["net.if.in"],
    "bandwidth_out_bps": ["net.if.out"],
    "latency_ms": ["icmpping", "icmppingsec"],
}


def _rpc(method: str, params: dict, auth: str | None) -> dict:
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    if auth:
        body["auth"] = auth
    r = requests.post(config.ZABBIX_API_URL, json=body, timeout=config.HTTP_TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Zabbix API error: {data['error']}")
    return data["result"]


def _login() -> str:
    if config.ZABBIX_API_TOKEN:
        return config.ZABBIX_API_TOKEN
    return _rpc(
        "user.login",
        {"username": config.ZABBIX_USER, "password": config.ZABBIX_PASSWORD},
        auth=None,
    )


def _hosts_by_trigger(problems: list[dict], token: str) -> dict[str, dict]:
    """{triggerid: first host} for the triggers behind `problems`."""
    trigger_ids = sorted({p["objectid"] for p in problems if p.get("objectid")})
    if not trigger_ids:
        return {}
    triggers = _rpc(
        "trigger.get",
        {
            "triggerids": trigger_ids,
            "output": ["triggerid"],
            "selectHosts": ["host", "name"],
        },
        auth=token,
    )
    return {t["triggerid"]: (t.get("hosts") or [{}])[0] for t in triggers}


def _cause_from_tags(problem: dict) -> tuple[str | None, str | None]:
    """Best-effort (cause_category, cause_label) from problem tags.

    Zabbix tags are free-form key/value pairs set by whoever built the
    trigger, so this only works if your templates actually tag problems
    with something like {"tag": "category", "value": "reseau"}. Returns
    (None, None) when nothing usable is present rather than guessing.
    """
    tags = problem.get("tags") or []
    category = next((t["value"] for t in tags if t.get("tag") == "category"), None)
    label = next((t["value"] for t in tags if t.get("tag") == "cause"), None)
    return category, label


def fetch_events(nodes: list[dict]) -> list[dict]:
    """Unresolved trigger problems, mapped onto dim_node codes.

    Feeds fact_incident directly. Now also carries acknowledged_at (from
    the problem's acknowledge history) and a best-effort cause_category /
    cause_label pulled from tags, instead of leaving those columns null.
    """
    token = _login()
    problems = _rpc(
        "problem.get",
        {
            "output": "extend",
            "source": 0,  # trigger problems
            "object": 0,  # raised on a trigger
            "selectTags": "extend",
            "selectAcknowledges": ["clock", "action"],
            "sortfield": ["eventid"],
            "sortorder": "ASC",
        },
        auth=token,
    )

    hosts = _hosts_by_trigger(problems, token)

    results = []
    for problem in problems:
        # Suppressed = the host is in a maintenance window, so the problem is
        # silenced on purpose and is not an incident for the dashboard.
        if int(problem.get("suppressed", 0)):
            continue
        host_entry = hosts.get(problem.get("objectid")) or {}
        host = host_entry.get("host", "")
        node_code = match_node(nodes, host, host_entry.get("name", ""))
        if node_code is None:
            skip_unmatched("zabbix", host)
            continue

        detected = datetime.fromtimestamp(int(problem["clock"]), tz=timezone.utc)

        acknowledged_at = None
        acks = problem.get("acknowledges") or []
        if acks:
            first_ack = min(acks, key=lambda a: int(a["clock"]))
            acknowledged_at = datetime.fromtimestamp(
                int(first_ack["clock"]), tz=timezone.utc
            ).isoformat()

        cause_category, cause_label = _cause_from_tags(problem)

        results.append(
            {
                "node_code": node_code,
                "source_tool": "zabbix",
                "external_id": f"zabbix-event-{problem['eventid']}",
                "severity": SEVERITY_MAP.get(int(problem.get("severity", 0)), "medium"),
                "detected_at": detected.isoformat(),
                "acknowledged_at": acknowledged_at,
                "description": problem.get("name") or "Alerte Zabbix",
                "cause_category": cause_category,
                "cause_label": cause_label,
            }
        )
    return results


def fetch_host_availability(nodes: list[dict]) -> list[dict]:
    """Current reachability of every monitored host, independent of triggers.

    A host can go unreachable (agent down, SNMP timeout, ICMP failing)
    without any trigger firing — missing trigger, trigger not yet
    evaluated, template gap. This is the source for an "equipements DOWN /
    interfaces DOWN" KPI that fetch_events() cannot guarantee on its own.

    Zabbix reports per-interface-type availability (`available`,
    `snmp_available`, `jmx_available`, `ipmi_available`) rather than one
    flat "host status" flag; we take the worst of whichever interface
    types are configured on that host and surface it as one row per node.
    """
    token = _login()
    hosts = _rpc(
        "host.get",
        {
            "output": [
                "host",
                "name",
                "status",
                "available",
                "snmp_available",
                "jmx_available",
                "ipmi_available",
                "error",
            ],
        },
        auth=token,
    )

    results = []
    for h in hosts:
        # status: 0 = monitored, 1 = unmonitored — skip hosts Zabbix isn't
        # actively watching, they carry no meaningful availability signal.
        if int(h.get("status", 0)) != 0:
            continue
        node_code = match_node(nodes, h.get("host", ""), h.get("name", ""))
        if node_code is None:
            skip_unmatched("zabbix", h.get("host", ""))
            continue

        availability_codes = [
            int(h.get(field, 0))
            for field in ("available", "snmp_available", "jmx_available", "ipmi_available")
        ]
        # worst case wins: any configured interface reporting "down" (2)
        # makes the node down; otherwise "up" if at least one is confirmed
        # up (1); otherwise "unknown".
        if 2 in availability_codes:
            status = "down"
        elif 1 in availability_codes:
            status = "up"
        else:
            status = "unknown"

        results.append(
            {
                "node_code": node_code,
                "source_tool": "zabbix",
                "status": status,
                "error": h.get("error") or None,
                "checked_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
    return results


def fetch_maintenance_windows(nodes: list[dict]) -> list[dict]:
    """Maintenance windows Zabbix currently considers active, per node.

    fetch_events() only tells you a problem was suppressed *if one
    happened to fire* during the window. A quiet node under maintenance
    produces no such signal. This queries maintenance.get directly so the
    "sites en maintenance" KPI reflects declared intent, not inferred
    absence of alerts.

    `maintenance.get` doesn't filter to "currently active" server-side in
    a version-portable way, so we compute that ourselves from
    active_since/active_till against wall-clock time.
    """
    token = _login()
    now = int(datetime.now(tz=timezone.utc).timestamp())
    windows = _rpc(
        "maintenance.get",
        {
            "output": ["maintenanceid", "name", "active_since", "active_till"],
            "selectHosts": ["host", "name"],
        },
        auth=token,
    )

    results = []
    for w in windows:
        if not (int(w["active_since"]) <= now <= int(w["active_till"])):
            continue
        for h in w.get("hosts") or []:
            node_code = match_node(nodes, h.get("host", ""), h.get("name", ""))
            if node_code is None:
                skip_unmatched("zabbix", h.get("host", ""))
                continue
            results.append(
                {
                    "node_code": node_code,
                    "source_tool": "zabbix",
                    "maintenance_name": w.get("name") or "Maintenance",
                    "active_since": datetime.fromtimestamp(
                        int(w["active_since"]), tz=timezone.utc
                    ).isoformat(),
                    "active_till": datetime.fromtimestamp(
                        int(w["active_till"]), tz=timezone.utc
                    ).isoformat(),
                }
            )
    return results


def fetch_operational_metrics(nodes: list[dict]) -> list[dict]:
    """Latest CPU / RAM / bandwidth / latency reading per node.

    Backs the useKpiOperational placeholder on the frontend. Zabbix has no
    single "give me CPU/RAM/bandwidth" call — these live on regular items,
    identified by key. Matching is done by key *prefix* against
    config.ZABBIX_ITEM_KEY_PATTERNS (falls back to DEFAULT_ITEM_KEY_PATTERNS
    if that setting doesn't exist yet), because item keys carry interface
    indexes and parameters (e.g. `net.if.in[eth0]`) that vary per host.

    This is inherently template-dependent: if your hosts don't use the
    default Zabbix templates, the default patterns will under-match and
    you'll need to set config.ZABBIX_ITEM_KEY_PATTERNS to your real keys
    before trusting this for a dashboard KPI.
    """
    token = _login()
    patterns = getattr(config, "ZABBIX_ITEM_KEY_PATTERNS", DEFAULT_ITEM_KEY_PATTERNS)
    all_prefixes = sorted({p for prefixes in patterns.values() for p in prefixes})

    items = _rpc(
        "item.get",
        {
            "output": ["itemid", "hostid", "key_", "lastvalue", "lastclock", "units"],
            "selectHosts": ["host", "name"],
            "search": {"key_": all_prefixes},
            "searchByAny": True,
        },
        auth=token,
    )

    def metric_name_for_key(key: str) -> str | None:
        for name, prefixes in patterns.items():
            if any(key.startswith(prefix) for prefix in prefixes):
                return name
        return None

    results = []
    for item in items:
        if item.get("lastvalue") in (None, ""):
            continue
        metric_name = metric_name_for_key(item.get("key_", ""))
        if metric_name is None:
            continue
        host_entry = (item.get("hosts") or [{}])[0]
        node_code = match_node(nodes, host_entry.get("host", ""), host_entry.get("name", ""))
        if node_code is None:
            skip_unmatched("zabbix", host_entry.get("host", ""))
            continue

        collected_at = (
            datetime.fromtimestamp(int(item["lastclock"]), tz=timezone.utc).isoformat()
            if item.get("lastclock")
            else None
        )
        results.append(
            {
                "node_code": node_code,
                "source_tool": "zabbix",
                "metric": metric_name,
                "value": item["lastvalue"],
                "unit": item.get("units") or None,
                "collected_at": collected_at,
            }
        )
    return results