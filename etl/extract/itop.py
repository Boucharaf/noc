"""
iTop collector — REST/JSON API: `core/get` on class Incident, HTTP Basic auth.

Strictly read-only, and that is a standing constraint rather than an
unfinished feature: iTop is the service desk of record, so the dashboard
reports what it already holds and never creates, updates or closes a ticket.
Anything that writes back belongs on the iTop side of the boundary, where the
ITSM workflow, its approvals and its audit trail live.

Every poll fetches every still-active Incident (operational_status not in
resolved/closed), the same "poll current state, skip what is finished"
approach every collector here takes: a ticket that stays open keeps reporting
with the same external_id, and the backend dedupes on
(source_tool, external_id).

=== The relay/dedup problem (read this before wiring both collectors) ===

iTop here is a hub, not an independent source: NetXMS, Zabbix, Centreon and
Nagios all forward events into it as Incidents. The original version of this
module treated every active Incident as a brand-new fact_incident row with
source_tool="itop" — but a ticket relayed 1:1 from, say, Zabbix is the *same
real-world incident* the Zabbix collector already reports under
source_tool="zabbix". Running both collectors unmodified double-counts every
relayed incident: doubled "Incidents" KPI, doubled/garbage MTTR, and this is
exactly the equipment-duplication risk that was raised early on for
multi-tool coverage of the same devices.

fetch_events() now best-effort detects the originating tool and an
external id from the ticket's free text (see _detect_origin) and returns
them as origin_source_tool / origin_external_id on each row. **The ETL merge
step must treat a row with a non-null origin_source_tool as an update to the
matching (origin_source_tool, origin_external_id) row from that tool's own
collector — set itop_ticket_id / acknowledged_at / resolved_at on it — not as
a new insert.** Only rows where origin_source_tool is None (no monitoring
tool signature found in the ticket — raised by phone, portal, or a tool this
module doesn't recognize yet) should become a fresh fact_incident row under
source_tool="itop". This detection is regex-based against free text and will
miss cases where a ticket doesn't mention its origin tool by name — treat it
as a starting point to refine against real samples from each of the four
tools, not as guaranteed-correct.

Resolved/closed tickets are excluded from fetch_events() rather than "just"
closed ones: normalize.to_ingest_payload always ingests as status="open", so
a resolved-in-iTop ticket would otherwise be reported as a brand-new open
incident on the dashboard. Their resolution is instead reported separately
by fetch_resolved_events(), which the ETL uses to close out (or update) the
matching fact_incident row rather than insert a new one.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

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

# Best-effort origin-tool detection from free text. Only Zabbix's relay
# format is confirmed against a real sample ("Hote: ..."); the Centreon /
# Nagios / NetXMS patterns are placeholders for the common ways each tool
# names itself in an alert subject and MUST be checked against real tickets
# from each source before being trusted for dedup.
_ORIGIN_TOOL_PATTERNS = {
    "zabbix": re.compile(r"zabbix", re.IGNORECASE),
    "centreon": re.compile(r"centreon", re.IGNORECASE),
    "nagios": re.compile(r"nagios", re.IGNORECASE),
    "netxms": re.compile(r"netxms", re.IGNORECASE),
}

# Best-effort external event/service id per tool, only applied once the
# tool itself has been recognized. None when no id is found in free text —
# the ETL then falls back to matching on (node_code, detected_at proximity)
# instead of an exact id.
_ORIGIN_ID_PATTERNS = {
    "zabbix": re.compile(r"event[\s:#]*([0-9]+)", re.IGNORECASE),
    "centreon": re.compile(r"service[\s:#]*([0-9]+)", re.IGNORECASE),
    "nagios": re.compile(r"alert[\s:#]*([0-9]+)", re.IGNORECASE),
    "netxms": re.compile(r"alarm[\s:#]*([0-9]+)", re.IGNORECASE),
}


def _clean_host_hint(raw: str) -> tuple[str, str | None]:
    """(name, ip-or-None) from a raw regex-extracted host hint."""
    cleaned = raw.strip().strip("'\"").strip()
    m = _HOST_IP_SUFFIX_RE.match(cleaned)
    if m:
        return m.group(1).strip(), m.group(2)
    return cleaned, None


def _detect_origin(fields: dict) -> tuple[str | None, str | None]:
    """(origin_source_tool, origin_external_id) guessed from free text.

    See the module docstring's "relay/dedup problem" section — this exists
    so the ETL can update the originating collector's row instead of
    inserting a duplicate fact_incident for the same real-world event.
    """
    text = f"{fields.get('title', '')} {fields.get('description', '')}"
    for tool, pattern in _ORIGIN_TOOL_PATTERNS.items():
        if pattern.search(text):
            id_pattern = _ORIGIN_ID_PATTERNS.get(tool)
            m = id_pattern.search(text) if id_pattern else None
            return tool, (m.group(1) if m else None)
    return None, None


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


def _parse_itop_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


# Standard iTop ITSM SLA attcodes (TTO = time to own, TTR = time to
# resolve). Custom iTop instances sometimes rename or drop these — verify
# against your instance's actual Incident datamodel before relying on them;
# if a field name is wrong, iTop's core/get simply omits it rather than
# erroring, so a silent None here likely means a naming mismatch, not "no
# SLA configured".
_SLA_FIELDS = [
    "tto_escalation_deadline",
    "ttr_escalation_deadline",
]


def fetch_events(nodes: list[dict]) -> list[dict]:
    """Active Incidents, mapped onto dim_node codes.

    Now also carries: operational_status (workflow_status), best-effort
    origin_source_tool/origin_external_id for dedup against the tool that
    originally raised the event (see module docstring), and the SLA
    escalation fields for the SLA dashboard.
    """
    data = _query(
        key="SELECT Incident WHERE operational_status NOT IN ('resolved', 'closed')",
        output_fields="ref,title,description,priority,operational_status,"
        "start_date,functionalcis_list," + ",".join(_SLA_FIELDS),
    )

    results = []
    for obj in (data.get("objects") or {}).values():
        fields = obj.get("fields", {})
        node_code = _match_node(nodes, fields)
        if node_code is None:
            skip_unmatched("itop", fields.get("ref") or obj.get("key", ""))
            continue

        detected = _parse_itop_datetime(fields.get("start_date")) or datetime.now(
            timezone.utc
        )
        origin_source_tool, origin_external_id = _detect_origin(fields)
        ttr_deadline = _parse_itop_datetime(fields.get("ttr_escalation_deadline"))

        results.append(
            {
                "node_code": node_code,
                "source_tool": "itop",
                "external_id": f"itop-incident-{obj.get('key')}",
                "itop_ticket_id": fields.get("ref"),
                "severity": PRIORITY_SEVERITY.get(
                    str(fields.get("priority")), "medium"
                ),
                "detected_at": detected.isoformat(),
                "description": fields.get("title") or "Ticket iTop",
                "cause_category": None,
                "cause_label": None,
                "workflow_status": fields.get("operational_status"),
                "origin_source_tool": origin_source_tool,
                "origin_external_id": origin_external_id,
                "sla_ttr_deadline": ttr_deadline.isoformat() if ttr_deadline else None,
                "sla_breached": bool(ttr_deadline and ttr_deadline < datetime.now(timezone.utc)),
            }
        )
    return results


def fetch_resolved_events(nodes: list[dict], since_hours: int | None = None) -> list[dict]:
    """Incidents resolved/closed within the lookback window.

    fetch_events() deliberately drops resolved tickets so they don't get
    re-ingested as new opens; this is where their resolution actually gets
    reported, so the ETL can close out the matching fact_incident row
    (found via external_id, or via origin_source_tool/origin_external_id
    when this ticket was a relay — see module docstring) instead of losing
    the resolution entirely.

    downtime_minutes is computed from start_date -> resolution_date.
    mttr_minutes is intentionally left for the ETL to fill in from the
    originating collector's acknowledged_at (e.g. Zabbix's), since iTop's
    own fields here don't distinguish "acknowledged" from "resolved".
    """
    since_hours = since_hours or getattr(config, "ITOP_RESOLVED_LOOKBACK_HOURS", 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    data = _query(
        key=(
            "SELECT Incident WHERE operational_status IN ('resolved', 'closed') "
            f"AND resolution_date >= '{cutoff_str}'"
        ),
        output_fields="ref,title,description,resolution_date,resolution_code,"
        "start_date,functionalcis_list",
    )

    results = []
    for obj in (data.get("objects") or {}).values():
        fields = obj.get("fields", {})
        node_code = _match_node(nodes, fields)
        if node_code is None:
            skip_unmatched("itop", fields.get("ref") or obj.get("key", ""))
            continue

        resolved_at = _parse_itop_datetime(fields.get("resolution_date"))
        started_at = _parse_itop_datetime(fields.get("start_date"))
        downtime_minutes = (
            int((resolved_at - started_at).total_seconds() // 60)
            if resolved_at and started_at
            else None
        )
        origin_source_tool, origin_external_id = _detect_origin(fields)

        results.append(
            {
                "node_code": node_code,
                "source_tool": "itop",
                "external_id": f"itop-incident-{obj.get('key')}",
                "itop_ticket_id": fields.get("ref"),
                "resolved_at": resolved_at.isoformat() if resolved_at else None,
                "downtime_minutes": downtime_minutes,
                "cause_category": fields.get("resolution_code") or None,
                "origin_source_tool": origin_source_tool,
                "origin_external_id": origin_external_id,
            }
        )
    return results