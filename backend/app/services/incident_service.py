from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.constants import SYNC_MV_REFRESH
from app.models.dimension import Cause, Node
from app.models.incident import Incident
from app.schemas.incidents import IncidentIngestPayload
from app.services import itop_service


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """fact_incident columns are TIMESTAMP WITHOUT TIME ZONE; normalize any
    tz-aware input (e.g. webhook payloads ending in "Z") to naive UTC so
    arithmetic against other naive columns doesn't raise."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def get_node_by_code(db: Session, node_code: str) -> Node:
    node = db.query(Node).filter(Node.code == node_code).first()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Unknown node_code '{node_code}'")
    return node


def get_or_create_cause(
    db: Session, category: str | None, label: str | None
) -> Cause | None:
    if not category or not label:
        return None
    cause = (
        db.query(Cause).filter(Cause.category == category, Cause.label == label).first()
    )
    if cause is None:
        cause = Cause(category=category, label=label)
        db.add(cause)
        db.flush()
    return cause


def refresh_kpi_view(db: Session) -> None:
    # The spec's nightly 02:00 refresh runs in the ETL beat container
    # (etl.refresh_kpi_view); this synchronous refresh-on-write keeps small demo
    # datasets interactive and is disabled in production via SYNC_MV_REFRESH=false.
    if not SYNC_MV_REFRESH:
        return
    db.execute(text("REFRESH MATERIALIZED VIEW mv_kpi_node_monthly"))
    db.commit()


def find_open_duplicate(
    db: Session, external_id: str | None, source_tool: str
) -> Incident | None:
    """An unresolved incident already ingested for this exact alert.

    Real collectors re-report a still-active problem on every poll (Nagios
    host status, NetXMS alarms…) with a stable external_id — matching it here
    makes ingestion idempotent. A resolved/closed incident does NOT match: the
    same alert firing again after recovery is a genuinely new incident.
    """
    if not external_id:
        return None
    return (
        db.query(Incident)
        .filter(
            Incident.external_id == external_id,
            Incident.source_tool == source_tool,
            Incident.status.in_(("open", "acknowledged")),
        )
        .first()
    )


def ingest_incident(db: Session, payload: IncidentIngestPayload) -> tuple[Incident, bool]:
    """Returns (incident, created) — created is False when the payload matched
    an already-open incident and no new row was written."""
    node = get_node_by_code(db, payload.node_code)

    duplicate = find_open_duplicate(db, payload.external_id, payload.source_tool)
    if duplicate is not None:
        return duplicate, False

    cause = get_or_create_cause(db, payload.cause_category, payload.cause_label)

    incident = Incident(
        node_id=node.id,
        cause_id=cause.id if cause else None,
        external_id=payload.external_id,
        source_tool=payload.source_tool,
        severity=payload.severity,
        status=payload.status,
        detected_at=_to_naive_utc(payload.detected_at),
        description=payload.description,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    if payload.itop_auto_ticket:
        incident.itop_ticket_id = itop_service.create_ticket(
            incident.id, payload.node_code, payload.description, payload.severity
        )
        db.commit()
        db.refresh(incident)

    refresh_kpi_view(db)
    return incident, True


def resolve_incident(
    db: Session, incident_id: int, resolved_at: datetime | None, notes: str | None
) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident.resolved_at = _to_naive_utc(resolved_at) or datetime.now(
        timezone.utc
    ).replace(tzinfo=None)
    incident.status = "resolved"
    if incident.acknowledged_at is None:
        incident.acknowledged_at = incident.resolved_at
    incident.downtime_minutes = max(
        int((incident.resolved_at - incident.detected_at).total_seconds() // 60), 0
    )
    if notes:
        incident.description = (
            f"{incident.description or ''}\n[Résolution] {notes}".strip()
        )

    db.commit()
    db.refresh(incident)
    refresh_kpi_view(db)
    return incident


def acknowledge_incident(
    db: Session, incident_id: int, acknowledged_at: datetime | None
) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident.acknowledged_at = _to_naive_utc(acknowledged_at) or datetime.now(
        timezone.utc
    ).replace(tzinfo=None)
    if incident.status == "open":
        incident.status = "acknowledged"

    db.commit()
    db.refresh(incident)
    return incident
