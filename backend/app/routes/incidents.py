from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.rate_limit import ingest_rate_limit
from app.core.security import require_role, verify_api_key
from app.db.session import get_db
from app.models.user import User
from app.schemas.incidents import (
    AcknowledgePayload,
    IncidentIngestPayload,
    IncidentIngestResponse,
    ResolvePayload,
)
from app.services import (
    alert_broadcaster,
    cache_service,
    incident_service,
    notification_service,
    push_service,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("/ingest", response_model=IncidentIngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_incident(
    payload: IncidentIngestPayload,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    incident, created = incident_service.ingest_incident(db, payload)

    if not created:
        # Re-reported still-open alert (batch pollers resend active problems):
        # idempotent no-op, no broadcast/notification, 200 instead of 201.
        response.status_code = status.HTTP_200_OK
        return IncidentIngestResponse(
            incident_id=incident.id,
            node_id=incident.node_id,
            itop_ticket_id=incident.itop_ticket_id,
            shift=incident.shift,
            created_at=incident.created_at,
        )

    cache_service.invalidate_prefix("kpi:")

    node = incident_service.get_node_by_code(db, payload.node_code)
    alert_broadcaster.publish_alert(
        {
            "type": "incident",
            "incident_id": incident.id,
            "node_code": node.code,
            "node_name": node.name,
            "severity": incident.severity,
            "status": incident.status,
            "detected_at": incident.detected_at,
            "description": incident.description,
        }
    )
    if incident.severity == "critical":
        # Spec §7 step 6 — SMS + permanence email; run after the response is sent.
        background_tasks.add_task(
            notification_service.notify_critical_incident,
            incident.id,
            node.code,
            node.name,
            incident.severity,
            str(incident.detected_at),
            incident.description,
            incident.itop_ticket_id,
        )
        background_tasks.add_task(
            push_service.notify_critical_incident_push,
            incident.id,
            node.code,
            node.name,
            incident.severity,
            incident.description,
        )

    return IncidentIngestResponse(
        incident_id=incident.id,
        node_id=incident.node_id,
        itop_ticket_id=incident.itop_ticket_id,
        shift=incident.shift,
        created_at=incident.created_at,
    )


@router.patch("/{incident_id}/resolve", response_model=IncidentIngestResponse)
def resolve_incident(
    incident_id: int,
    payload: ResolvePayload,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("admin", "noc_agent")),
):
    incident = incident_service.resolve_incident(db, incident_id, payload.resolved_at, payload.notes)
    cache_service.invalidate_prefix("kpi:")
    return IncidentIngestResponse(
        incident_id=incident.id,
        node_id=incident.node_id,
        itop_ticket_id=incident.itop_ticket_id,
        shift=incident.shift,
        created_at=incident.created_at,
    )


@router.patch("/{incident_id}/acknowledge", response_model=IncidentIngestResponse)
def acknowledge_incident(
    incident_id: int,
    payload: AcknowledgePayload,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role("admin", "noc_agent")),
):
    incident = incident_service.acknowledge_incident(db, incident_id, payload.acknowledged_at)
    cache_service.invalidate_prefix("kpi:alerts")
    return IncidentIngestResponse(
        incident_id=incident.id,
        node_id=incident.node_id,
        itop_ticket_id=incident.itop_ticket_id,
        shift=incident.shift,
        created_at=incident.created_at,
    )
