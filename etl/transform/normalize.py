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


# Two of the three extra signals collapse onto the same fact_metric shape:
# operational_metrics already reports {metric, value, unit, collected_at},
# while host_availability/service_availability report {status, checked_at} —
# a point-in-time up/down reading is, for storage purposes, just another
# metric (metric_type="availability", value 1.0/0.0). Normalizing both here
# means metrics_service only ever has one ingestion shape to handle.
_AVAILABILITY_VALUE = {"up": 1.0, "down": 0.0}


def to_metric_payload(event: dict) -> dict | None:
    """One fact_metric row from an operational_metrics or a
    host_availability/service_availability event — see extract/*.py's
    fetch_operational_metrics()/fetch_host_availability(). Returns None for
    an "unknown" availability reading: unknown isn't a value on the 0/1
    availability scale, it's the absence of one, and a metric row with no
    real value would just have to be filtered back out downstream.
    """
    if "metric" in event:
        return {
            "node_code": event["node_code"],
            "source_tool": event["source_tool"],
            "metric_type": event["metric"],
            "value": event["value"],
            "unit": event.get("unit"),
            "collected_at": event["collected_at"],
        }

    # host_availability / service_availability shape.
    value = _AVAILABILITY_VALUE.get(event.get("status"))
    if value is None:
        return None
    return {
        "node_code": event["node_code"],
        "source_tool": event["source_tool"],
        "metric_type": "availability",
        "value": value,
        "unit": None,
        "collected_at": event["checked_at"],
    }


def to_maintenance_window_payload(event: dict) -> dict:
    """One dim_maintenance_window row imported from a supervision tool — see
    extract/*.py's fetch_maintenance_windows(). active_since/active_till are
    frequently None (NetXMS never reports them; Centreon only reports the
    boolean flag — see extract/centreon.py's module docstring): the backend
    fills a missing active_since with "now" and a missing active_till with a
    short default duration, since a maintenance row needs both to be useful
    for SLA/alert suppression at all.
    """
    return {
        "node_code": event["node_code"],
        "source_tool": event["source_tool"],
        # Stable across polls for the same window so re-importing it every
        # five minutes upserts instead of creating a new row each time.
        "external_id": f"{event['source_tool']}-{event['node_code']}-maintenance",
        "reason": event.get("maintenance_name") or "Maintenance importée",
        "starts_at": event.get("active_since"),
        "ends_at": event.get("active_till"),
    }


def to_asset_payload(asset: dict) -> dict:
    """One dim_asset row from itop.fetch_all_assets() — the full CMDB
    inventory used for the supervision-coverage referential. Reconciling it
    against dim_node (to set is_monitored/node_id) is the backend's job
    (asset_service.sync_assets_bulk), not this function's — see
    extract/itop.py's fetch_all_assets() docstring for why.
    """
    return {
        "itop_ci_id": asset["itop_ci_id"],
        "name": asset["name"],
        "asset_type": asset.get("asset_type"),
        "org_name": asset.get("org_name"),
        "location_name": asset.get("location_name"),
    }