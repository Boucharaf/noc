"""Normalizes a raw supervision-tool event into the shapes the backend expects."""


def to_ingest_payload(event: dict) -> dict:
    """One open fact_incident row, as every collector's fetch_events() reports it.

    The first block of keys is produced by every collector and is required —
    a KeyError here means a collector emitted a malformed event, which should
    surface loudly rather than be swallowed. Everything after that is
    collector-specific and optional:

      * acknowledged_at                  — Zabbix only
      * itop_ticket_id                   — iTop only
      * workflow_status                  — iTop only (the ticket's own status)
      * origin_source_tool /
        origin_external_id              — iTop only. See extract/itop.py's
                                            module docstring (the relay/dedup
                                            problem): the ETL/backend needs
                                            these to tell a ticket relayed
                                            from another tool apart from a
                                            genuinely new one. Dropping them
                                            here — the previous version of
                                            this function did — silently
                                            defeats that dedup and every
                                            relayed incident gets double
                                            counted.
      * sla_ttr_deadline / sla_breached  — iTop only
    """
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
        "acknowledged_at": event.get("acknowledged_at"),
        "itop_ticket_id": event.get("itop_ticket_id"),
        "workflow_status": event.get("workflow_status"),
        "origin_source_tool": event.get("origin_source_tool"),
        "origin_external_id": event.get("origin_external_id"),
        "sla_ttr_deadline": event.get("sla_ttr_deadline"),
        "sla_breached": event.get("sla_breached"),
    }


def to_resolution_payload(event: dict) -> dict:
    """One resolved/closed incident, as itop.fetch_resolved_events() reports it.

    Deliberately a different shape from to_ingest_payload(): this is not a
    new fact_incident row, it's the closing update to one that already
    exists — matched by external_id, or by
    (origin_source_tool, origin_external_id) when the ticket was a relay
    (see extract/itop.py). No "status" key is hardcoded here: the caller/
    backend decides resolved vs closed on the row it matches, rather than
    this function inventing a value for a shape it doesn't own.

    NOTE: nothing calls this yet — pipelines/tasks.py's collect_supervision
    only drives fetch_events(). Wiring fetch_resolved_events() in needs a
    matching backend endpoint to apply the update; confirm that exists
    before adding the call.
    """
    return {
        "external_id": event["external_id"],
        "source_tool": event["source_tool"],
        "node_code": event["node_code"],
        "itop_ticket_id": event.get("itop_ticket_id"),
        "resolved_at": event.get("resolved_at"),
        "downtime_minutes": event.get("downtime_minutes"),
        "cause_category": event.get("cause_category"),
        "origin_source_tool": event.get("origin_source_tool"),
        "origin_external_id": event.get("origin_external_id"),
    }