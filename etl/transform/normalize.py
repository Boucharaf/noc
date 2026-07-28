"""Normalizes a raw supervision-tool event into the /api/incidents/ingest payload shape."""


def to_ingest_payload(event: dict) -> dict:
    return {
        "external_id": event["external_id"],
        "source_tool": event["source_tool"],
        "node_code": event["node_code"],
        "severity": event["severity"],
        "status": "open",
        "detected_at": event["detected_at"],
        "description": event.get("description"),
        "cause_category": event.get("cause_category"),
        "cause_label": event.get("cause_label"),
    }
