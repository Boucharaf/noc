"""
Centreon collector — REST API v2 monitoring resources.

Centreon's primary integration is the broker webhook pushing straight to
POST /api/incidents/ingest (already supported by the backend); this poller is
the batch complement, and a safety net if webhooks are not configured.

Auth: either a static token (CENTREON_API_KEY → X-AUTH-TOKEN header) or a
/login call with CENTREON_USER/CENTREON_PASSWORD.

Three signals, same reasoning as the Zabbix collector — "problems Centreon
currently has open" isn't the whole NOC picture:

  * fetch_events()              -> fact_incident rows (unhandled problems)
  * fetch_host_availability()   -> current status of every monitored host,
                                    not just the ones currently unhandled
  * fetch_maintenance_windows() -> hosts Centreon currently flags
                                    `is_in_downtime`

All three page through /monitoring/resources via `limit`/`page`. The
previous version of fetch_events() requested `limit: 100` and never paged —
on an instance with more than 100 hosts unhandled at once, everything past
the first page was silently dropped, with no warning distinguishing that
from "there just weren't more incidents". Every call site here now pages to
exhaustion.

`is_in_downtime` and the pagination `meta.total` shape are what this was
built against for Centreon's v2 monitoring API — Centreon has reshuffled
both before across versions, so confirm both against your instance (a raw
GET on /monitoring/resources is the fastest check) before trusting
fetch_maintenance_windows() for a KPI. fetch_maintenance_windows() also
cannot report active_since/active_till from this endpoint — it only exposes
the boolean flag, not the downtime's own start/end times; querying
/monitoring/hosts/{id}/downtimes per flagged host would be needed for that,
deliberately left out here to avoid turning one poll into N+1 requests.
"""

import logging
from datetime import datetime, timezone

import requests

import config
from extract.common import build_node_index, match_node, skip_unmatched

logger = logging.getLogger(__name__)

# Status filter: status IN (2, 3) — Critical + Unknown
STATUS_SEVERITY = {"CRITICAL": "critical", "UNKNOWN": "high", "DOWN": "critical"}

_PAGE_LIMIT = 100


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


def _paginated_resources(token: str, params: dict) -> list[dict]:
    """GET /monitoring/resources, following pagination to exhaustion."""
    resources: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            f"{_base_url()}/monitoring/resources",
            headers={"X-AUTH-TOKEN": token},
            params={**params, "limit": _PAGE_LIMIT, "page": page},
            timeout=config.HTTP_TIMEOUT_S,
        )
        r.raise_for_status()
        payload = r.json()
        batch = payload.get("result", [])
        resources.extend(batch)
        total = (payload.get("meta") or {}).get("total", len(resources))
        if len(batch) < _PAGE_LIMIT or len(resources) >= total:
            return resources
        page += 1


def fetch_events(nodes: list[dict]) -> list[dict]:
    token = _auth_token()
    resources = _paginated_resources(
        token,
        {
            "states": '["unhandled_problems"]',
            "statuses": '["CRITICAL","UNKNOWN","DOWN"]',
        },
    )

    index = build_node_index(nodes)
    results = []
    for res in resources:
        status_name = (res.get("status") or {}).get("name", "").upper()
        severity = STATUS_SEVERITY.get(status_name)
        if severity is None:
            continue
        # A host resource carries the configured host name in `name` — which
        # is where the node code goes (see the image README) — and a
        # free-text label in `alias`; either may be what the CMDB knows the
        # node by, so both are offered rather than letting a non-empty alias
        # hide the name. For a service the parent host is what identifies
        # the node, so it goes first; that service's own name/alias simply
        # won't match anything.
        parent = (res.get("parent") or {}).get("name") or ""
        host = parent or res.get("name") or res.get("alias") or ""
        node_code = match_node(
            nodes,
            parent,
            res.get("name", ""),
            res.get("alias", ""),
            res.get("fqdn", ""),
            index=index,
        )
        if node_code is None:
            skip_unmatched("centreon", host)
            continue
        changed = res.get("last_status_change")
        detected = (
            datetime.fromisoformat(changed) if changed else datetime.now(timezone.utc)
        )
        results.append(
            {
                "node_code": node_code,
                "source_tool": "centreon",
                "external_id": f"centreon-{res.get('type', 'resource')}-{res.get('id')}-{status_name.lower()}",
                "severity": severity,
                "detected_at": detected.isoformat(),
                "description": res.get("information")
                or f"{status_name} — {host} (Centreon)",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results


def fetch_host_availability(nodes: list[dict]) -> list[dict]:
    """Current status of every monitored host, not just the unhandled ones.

    Same gap as Zabbix's fetch_host_availability(): a host can be down while
    already acknowledged/handled (invisible to fetch_events()'s
    `unhandled_problems` filter) or simply not surfaced as a problem
    fetch_events() would catch. This queries all host-type resources
    regardless of state.
    """
    token = _auth_token()
    resources = _paginated_resources(token, {"types": '["host"]'})

    index = build_node_index(nodes)
    results = []
    for res in resources:
        status_name = (res.get("status") or {}).get("name", "").upper()
        if status_name in ("UP", "OK"):
            status = "up"
        elif status_name in ("DOWN", "CRITICAL"):
            status = "down"
        elif status_name in ("UNREACHABLE", "UNKNOWN"):
            status = "unknown"
        else:
            continue  # PENDING or unrecognized — no meaningful signal yet
        host = res.get("name") or res.get("alias") or res.get("fqdn") or ""
        node_code = match_node(
            nodes, host, res.get("alias", ""), res.get("fqdn", ""), index=index
        )
        if node_code is None:
            skip_unmatched("centreon", host)
            continue
        results.append(
            {
                "node_code": node_code,
                "source_tool": "centreon",
                "status": status,
                "error": res.get("information") or None,
                "checked_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
    return results


def fetch_maintenance_windows(nodes: list[dict]) -> list[dict]:
    """Hosts Centreon currently reports as `is_in_downtime`.

    fetch_events() only shows a suppressed problem if it still counts as an
    `unhandled_problem`; a host quietly parked in a downtime with no active
    problem produces nothing there. This scans all host resources for the
    downtime flag directly — see the module docstring for why
    active_since/active_till aren't available from this endpoint.
    """
    token = _auth_token()
    resources = _paginated_resources(token, {"types": '["host"]'})

    index = build_node_index(nodes)
    results = []
    for res in resources:
        if not res.get("is_in_downtime"):
            continue
        host = res.get("name") or res.get("alias") or res.get("fqdn") or ""
        node_code = match_node(
            nodes, host, res.get("alias", ""), res.get("fqdn", ""), index=index
        )
        if node_code is None:
            skip_unmatched("centreon", host)
            continue
        results.append(
            {
                "node_code": node_code,
                "source_tool": "centreon",
                "maintenance_name": "Downtime Centreon",
                "active_since": None,
                "active_till": None,
            }
        )
    return results