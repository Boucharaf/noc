"""
iTop CMDB/ITSM client — creates Incident tickets via iTop's REST webservice
(operation core/create, class Incident) using ITOP_URL/ITOP_USER/ITOP_PASS.

Like the notification channels in notification_service.py, this must degrade
gracefully: iTop being down or misconfigured must never block ingestion of a
live incident from a supervision webhook.
"""

import json
import logging

import requests

from app.core.constants import ITOP_ORG_ID, ITOP_PASS, ITOP_URL, ITOP_USER

logger = logging.getLogger(__name__)

# iTop's Incident.urgency enum: 1=Critical, 2=High, 3=Medium, 4=Low
_URGENCY_BY_SEVERITY = {
    "critical": "1",
    "high": "2",
    "medium": "3",
    "low": "4",
}


def create_ticket(incident_id: int, node_code: str, description: str | None, severity: str = "medium") -> str | None:
    """Create an Incident ticket in iTop. Returns its reference (e.g. "I-000042"),
    or None if iTop is unreachable/misconfigured/rejects the request."""
    if not ITOP_URL:
        return None

    fields = {
        "title": f"[NOC] Incident #{incident_id} - {node_code}",
        "org_id": ITOP_ORG_ID,
        "description": description or f"Incident detected on node {node_code}",
        "urgency": _URGENCY_BY_SEVERITY.get(severity, "3"),
    }
    payload = {
        "operation": "core/create",
        "class": "Incident",
        "comment": "Created automatically by the NOC dashboard",
        "output_fields": "id,ref",
        "fields": fields,
    }

    try:
        response = requests.post(
            ITOP_URL,
            params={"version": "1.3"},
            data={
                "auth_user": ITOP_USER,
                "auth_pwd": ITOP_PASS,
                "json_data": json.dumps(payload),
            },
            timeout=5,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.error("iTop ticket creation failed for incident #%s: %s", incident_id, exc)
        return None

    if result.get("code") != 0:
        logger.error(
            "iTop rejected ticket creation for incident #%s: %s",
            incident_id,
            result.get("message"),
        )
        return None

    objects = result.get("objects") or {}
    if not objects:
        return None
    ticket = next(iter(objects.values()))
    return ticket.get("fields", {}).get("ref")
