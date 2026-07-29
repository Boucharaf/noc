"""
iTop collector — REST/JSON API (cahier des charges, iTop as read-only ticket
source). Read-only: `core/get` on class Incident, HTTP Basic auth. The
dashboard never creates/updates iTop tickets (see the removed
itop_service.py) — it only ever displays what iTop already has.

Every poll fetches every still-active Incident (operational_status not in
resolved/closed) rather than filtering on `since`, matching the netxms
collector's "poll current state, skip terminated" approach: a ticket that
stays open keeps reporting with the same external_id, and the backend
dedupes on (source_tool, external_id). Resolved/closed tickets are excluded
rather than "just" closed ones: normalize.to_ingest_payload always ingests
as status="open", so a resolved-in-iTop ticket would otherwise be reported
as a brand-new open incident on the dashboard.
"""

import json
import logging
import re
from datetime import datetime, timezone

import requests

import config
from extract.common import match_node, skip_unmatched

logger = logging.getLogger(__name__)

# iTop priority 1-4, most instances configured highest-to-lowest.
PRIORITY_SEVERITY = {"1": "critical", "2": "high", "3": "medium", "4": "low"}

# Real tickets (see endpoints.txt sample) are relayed from Zabbix with an
# empty functionalcis_list — no CI link — so the host has to be recovered
# from free text: a "Hote: <name>" line in the description, and/or a
# "... sur <name>" suffix on the title. Both name the same host; try both.
_HOST_DESCRIPTION_RE = re.compile(r"H[oô]te\s*:\s*([^\n<]+)", re.IGNORECASE)
_HOST_TITLE_RE = re.compile(r"\bsur\s+(\S+)\s*$", re.IGNORECASE)

# Some titles wrap the hostname in quotes ("... sur 'HOST'") or append an IP
# in parens ("Hyperviseur-02 (10.165.22.83)") — strip both so the cleaned
# name matches dim_node.name exactly.
_HOST_IP_SUFFIX_RE = re.compile(r"^(.*?)\s*\((\d{1,3}(?:\.\d{1,3}){3})\)\s*$")


def _clean_host_hint(raw: str) -> tuple[str, str | None]:
    """(name, ip-or-None) from a raw regex-extracted host hint."""
    cleaned = raw.strip().strip("'\"").strip()
    m = _HOST_IP_SUFFIX_RE.match(cleaned)
    if m:
        return m.group(1).strip(), m.group(2)
    return cleaned, None


def _query(**params) -> dict:
    payload = {"operation": "core/get", "class": "Incident", **params}
    r = requests.post(
        config.ITOP_API_URL,
        data={"json_data": json.dumps(payload)},
        auth=(config.ITOP_USER, config.ITOP_PASSWORD),
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"iTop API error: {data.get('message')}")
    return data


def _match_node(nodes: list[dict], fields: dict) -> str | None:
    ci_list = fields.get("functionalcis_list") or []

    ci_ids = {
        str(ci["functionalci_id"])
        for ci in ci_list
        if isinstance(ci, dict) and ci.get("functionalci_id")
    }
    for n in nodes:
        if n.get("itop_ci_id") and n["itop_ci_id"] in ci_ids:
            return n["code"]

    for ci in ci_list:
        if not isinstance(ci, dict):
            continue
        code = match_node(nodes, ci.get("functionalci_id_friendlyname", ""))
        if code:
            return code

    hints = [
        _clean_host_hint(m.group(1))[0]
        for m in (
            _HOST_DESCRIPTION_RE.search(fields.get("description") or ""),
            _HOST_TITLE_RE.search(fields.get("title") or ""),
        )
        if m
    ]
    return match_node(nodes, *hints) if hints else None


def fetch_events(nodes: list[dict], since: datetime) -> list[dict]:
    data = _query(
        key="SELECT Incident WHERE operational_status NOT IN ('resolved', 'closed')",
        output_fields="ref,title,description,priority,start_date,functionalcis_list",
    )

    results = []
    for obj in (data.get("objects") or {}).values():
        fields = obj.get("fields", {})
        node_code = _match_node(nodes, fields)
        if node_code is None:
            skip_unmatched("itop", fields.get("ref") or obj.get("key", ""))
            continue

        start_date = fields.get("start_date")
        if start_date:
            detected = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        else:
            detected = datetime.now(timezone.utc)

        results.append(
            {
                "node_code": node_code,
                "source_tool": "itop",
                "external_id": f"itop-incident-{obj.get('key')}",
                "itop_ticket_id": fields.get("ref"),
                "severity": PRIORITY_SEVERITY.get(str(fields.get("priority")), "medium"),
                "detected_at": detected.isoformat(),
                "description": fields.get("title") or "Ticket iTop",
                "cause_category": None,
                "cause_label": None,
            }
        )
    return results
