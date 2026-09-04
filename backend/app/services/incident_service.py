from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import Integer, func, select, text, update
from sqlalchemy.orm import Session

from app.core.constants import SYNC_MV_REFRESH
from app.models.dimension import Cause, Node
from app.models.incident import Incident
from app.schemas.incidents import IncidentIngestPayload


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


def ingest_incident(
    db: Session, payload: IncidentIngestPayload
) -> tuple[Incident, Node, bool]:
    """Returns (incident, node, created) — created is False when the payload
    matched an already-open incident and no new row was written.

    The node is returned alongside the incident (rather than making the route
    call get_node_by_code again) so callers building a broadcast/notification
    payload don't pay for the same lookup twice on every single ingestion."""
    node = get_node_by_code(db, payload.node_code)

    duplicate = find_open_duplicate(db, payload.external_id, payload.source_tool)
    if duplicate is not None:
        return duplicate, node, False

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
        itop_ticket_id=payload.itop_ticket_id,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    refresh_kpi_view(db)
    return incident, node, True


def reconcile_open_incidents(
    db: Session, source_tool: str, active_external_ids: set[str]
) -> int:
    """Resolve incidents whose alert has disappeared from the tool's active set.

    Batch collectors report what is wrong *right now*; an alert that clears
    simply stops being listed, and nothing else ever tells us it ended. Without
    this, incidents only accumulate: MTTR and resolution rate stay at zero
    forever, and every availability figure is computed against outages that the
    network recovered from months ago.

    The active set is only trusted when it is non-empty. An empty one is
    indistinguishable from a collector that authenticated but returned nothing,
    and treating that as "the whole network recovered" would resolve every open
    incident for the tool at once — losing the real start times, since the next
    poll re-creates them as new incidents detected now. A genuine all-clear is
    picked up by the next pass that carries at least one alert.

    Incidents with no external_id are left alone: they cannot be matched
    against the active set, so their absence from it means nothing.
    """
    if not active_external_ids:
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = db.execute(
        update(Incident)
        .where(
            Incident.source_tool == source_tool,
            Incident.status.in_(("open", "acknowledged")),
            Incident.external_id.isnot(None),
            Incident.external_id.notin_(active_external_ids),
        )
        .values(
            status="resolved",
            resolved_at=now,
            # Never acknowledged by a human, but leaving it null would make the
            # incident look unhandled forever in the alert views.
            acknowledged_at=func.coalesce(Incident.acknowledged_at, now),
            downtime_minutes=func.greatest(
                func.floor(
                    func.extract("epoch", now - Incident.detected_at) / 60
                ).cast(Integer),
                0,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def ingest_incidents_bulk(
    db: Session, payloads: list[IncidentIngestPayload]
) -> dict[str, int]:
    """Ingest a whole poll's worth of alerts in one transaction.

    Same semantics as ingest_incident — dedupe on (source_tool, external_id)
    against still-open incidents, create a cause when both parts are given —
    but nothing per-item: one lookup per *set* of node codes, external ids and
    causes, one commit, one materialized-view refresh at the end. Ingesting
    NetXMS's ~1500 active alarms through ingest_incident means 1500 commits and
    1500 REFRESH MATERIALIZED VIEW, which is what makes the one-by-one path
    unusable at that size rather than merely slow.

    Deliberately silent: no broadcast, no SMS, no email. This is the path for a
    batch poller reconciling its whole active set, where the interesting event
    is "here is everything that is wrong right now", not 1500 separate pieces of
    news — notifying on each would page the permanence a thousand times for a
    backlog it already knows about. Genuinely new incidents still arrive
    through POST /ingest and still notify.

    Unknown node codes are counted and skipped, not raised: one host missing
    from the CMDB must not throw away the other 1499.
    """
    if not payloads:
        return {
            "received": 0,
            "created": 0,
            "duplicates": 0,
            "unknown_node": 0,
            "resolved": 0,
        }

    node_ids = {
        code: nid
        for code, nid in db.query(Node.code, Node.id).filter(
            Node.code.in_({p.node_code for p in payloads})
        )
    }

    external_ids = {p.external_id for p in payloads if p.external_id}
    open_keys = set()
    if external_ids:
        open_keys = {
            (source_tool, external_id)
            for external_id, source_tool in db.query(
                Incident.external_id, Incident.source_tool
            ).filter(
                Incident.external_id.in_(external_ids),
                Incident.status.in_(("open", "acknowledged")),
            )
        }

    created = duplicates = unknown_node = 0
    for payload in payloads:
        node_id = node_ids.get(payload.node_code)
        if node_id is None:
            unknown_node += 1
            continue
        key = (payload.source_tool, payload.external_id)
        # Checked against open_keys rather than the database so that duplicates
        # *within the batch* collapse too — a poll can legitimately carry the
        # same external_id twice.
        if payload.external_id and key in open_keys:
            duplicates += 1
            continue

        cause = get_or_create_cause(db, payload.cause_category, payload.cause_label)
        db.add(
            Incident(
                node_id=node_id,
                cause_id=cause.id if cause else None,
                external_id=payload.external_id,
                source_tool=payload.source_tool,
                severity=payload.severity,
                status=payload.status,
                detected_at=_to_naive_utc(payload.detected_at),
                description=payload.description,
                itop_ticket_id=payload.itop_ticket_id,
            )
        )
        if payload.external_id:
            open_keys.add(key)
        created += 1

    # Reconcile within the same transaction as the inserts, so the batch is
    # applied as one consistent "this is the state now" snapshot per tool.
    resolved = 0
    for source_tool in {p.source_tool for p in payloads}:
        resolved += reconcile_open_incidents(
            db,
            source_tool,
            {p.external_id for p in payloads if p.source_tool == source_tool and p.external_id},
        )

    db.commit()
    if created or resolved:
        refresh_kpi_view(db)

    return {
        "received": len(payloads),
        "created": created,
        "duplicates": duplicates,
        "unknown_node": unknown_node,
        "resolved": resolved,
    }


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


def list_incidents(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    locality_id: int | None = None,
    node_code: str | None = None,
    source_tool: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Paginated, filterable incident history — the /open and /recent alert
    feeds are deliberately top-N views for the live dashboard; this backs the
    IncidentTable's "search the whole history" use case (by node, locality,
    period, ticket…) that neither of those can answer.
    """
    query = select(Incident).join(Node, Incident.node_id == Node.id)
    count_query = select(func.count(Incident.id)).select_from(Incident).join(
        Node, Incident.node_id == Node.id
    )

    filters = []
    if status:
        filters.append(Incident.status == status)
    if severity:
        filters.append(Incident.severity == severity)
    if locality_id is not None:
        filters.append(Node.locality_id == locality_id)
    if node_code:
        filters.append(Node.code == node_code)
    if source_tool:
        filters.append(Incident.source_tool == source_tool)
    if date_from is not None:
        filters.append(Incident.detected_at >= _to_naive_utc(date_from))
    if date_to is not None:
        filters.append(Incident.detected_at <= _to_naive_utc(date_to))

    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    total = db.execute(count_query).scalar() or 0

    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    rows = (
        db.execute(
            query.order_by(Incident.detected_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    items = [
        {
            "id": r.id,
            "node_id": r.node_id,
            "node_code": r.node.code,
            "node_name": r.node.name,
            "locality_id": r.node.locality_id,
            "severity": r.severity,
            "status": r.status,
            "source_tool": r.source_tool,
            "description": r.description,
            "detected_at": r.detected_at,
            "acknowledged_at": r.acknowledged_at,
            "resolved_at": r.resolved_at,
            "itop_ticket_id": r.itop_ticket_id,
            "external_id": r.external_id,
        }
        for r in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }