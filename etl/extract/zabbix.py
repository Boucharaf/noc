"""
Zabbix collector — JSON-RPC `problem.get`.

Auth: either a static API token (ZABBIX_API_TOKEN, Zabbix ≥ 5.4) or
`user.login` with ZABBIX_USER/ZABBIX_PASSWORD (token valid ~30 min, so we
log in on every poll rather than caching it).

Reports the problems Zabbix currently holds unresolved, not the events raised
since the last poll — the same "report current state, let the backend
deduplicate" contract every collector here follows. Read `event.get` with
`time_from` as the tempting alternative and understand why it is wrong: it
offers each event in exactly one poll window, so a trigger that fired before
collection first ran stays invisible for as long as it remains open, any
outage longer than the look-back leaves a permanent hole, and an ingest that
fails loses that incident for good. Current state has none of those failure
modes. A problem that stays open re-reports every pass under its event id,
which is stable for the life of the problem, and the backend collapses the
repeats on (source_tool, external_id).

Two API details drive the shape of this module, both verified against Zabbix
7.0 and neither obvious from the method name:

  * `problem.get` rejects `selectHosts`. It names the trigger in `objectid`
    instead, so the hosts have to be fetched separately with `trigger.get`.
  * `suppressed` marks a problem silenced by a maintenance window. Those are
    dropped: somebody deliberately declared that outage uninteresting, and
    surfacing it anyway would put planned work into the availability figures.
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

# Zabbix trigger severities 0–5 → dashboard severities
SEVERITY_MAP = {0: "low", 1: "low", 2: "medium", 3: "medium", 4: "high", 5: "critical"}


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


def fetch_events(nodes: list[dict]) -> list[dict]:
    """Unresolved trigger problems, mapped onto dim_node codes."""
    token = _login()
    problems = _rpc(
        "problem.get",
        {
            "output": "extend",
            "source": 0,  # trigger problems
            "object": 0,  # raised on a trigger
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
        results.append(
            {
                "node_code": node_code,
                "source_tool": "zabbix",
                "external_id": f"zabbix-event-{problem['eventid']}",
                "severity": SEVERITY_MAP.get(int(problem.get("severity", 0)), "medium"),
                "detected_at": detected.isoformat(),
                "description": problem.get("name") or "Alerte Zabbix",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
