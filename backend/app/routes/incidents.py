from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.rate_limit import ingest_rate_limit, read_rate_limit
from app.core.security import get_current_user, require_role, verify_api_key
from app.db.session import get_db
from app.models.user import User
from app.schemas.incidents import (
    AcknowledgePayload,
    IncidentBulkIngestPayload,
    IncidentBulkIngestResponse,
    IncidentIngestPayload,
    IncidentIngestResponse,
    IncidentListResponse,
    ManualIncidentPayload,
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

# Rôles habilités à intervenir sur un incident. "agent_terrain" peut acquitter
# (il est souvent le premier au contact) mais pas résoudre : la clôture
# formelle d'un incident reste une décision technique.
_ACKNOWLEDGE_ROLES = ("agent_terrain", "technicien", "chef_noc", "directeur")
_RESOLVE_ROLES = ("technicien", "chef_noc", "directeur")
_MANUAL_INCIDENT_ROLES = ("agent_terrain", "technicien", "chef_noc", "directeur")

# NOTE: ces slugs doivent correspondre exactement aux valeurs stockées dans
# dim_user.role. Si votre migration a choisi d'autres noms, ne changez que
# les tuples ci-dessus — le reste du fichier n'a pas à bouger.


def _dispatch_new_incident(
    background_tasks: BackgroundTasks, incident, node
) -> None:
    """Broadcast temps réel + notifications (SMS/email/push) pour un incident
    tout juste créé — factorisé car /ingest ET /manual doivent tous les deux
    le déclencher de la même façon."""
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
        # Différé après l'envoi de la réponse : l'appelant (outil de
        # supervision ou agent terrain) ne doit jamais attendre Twilio/SMTP,
        # ni voir sa requête échouer parce qu'un notifieur est indisponible.
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


def _to_response(incident) -> IncidentIngestResponse:
    return IncidentIngestResponse(
        incident_id=incident.id,
        node_id=incident.node_id,
        itop_ticket_id=incident.itop_ticket_id,
        shift=incident.shift,
        created_at=incident.created_at,
    )


@router.post("/ingest", response_model=IncidentIngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_incident(
    payload: IncidentIngestPayload,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    incident, node, created = incident_service.ingest_incident(db, payload)

    if not created:
        # Re-reported still-open alert (batch pollers resend active problems):
        # idempotent no-op, no broadcast/notification, 200 instead of 201.
        response.status_code = status.HTTP_200_OK
        return _to_response(incident)

    cache_service.invalidate_prefix("kpi:")
    _dispatch_new_incident(background_tasks, incident, node)
    return _to_response(incident)


@router.post(
    "/manual",
    response_model=IncidentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_incident(
    payload: ManualIncidentPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_MANUAL_INCIDENT_ROLES)),
):
    """Signalement manuel d'un incident depuis le dashboard — pour un problème
    constaté sur le terrain (câble coupé, groupe électrogène en panne…) que
    les outils de supervision n'ont pas détecté. Authentifié par JWT (pas la
    clé API des collecteurs ETL) : c'est un humain, pas un poller, qui déclare.
    """
    ingest_payload = IncidentIngestPayload(
        node_code=payload.node_code,
        source_tool="manual",
        severity=payload.severity,
        status="open",
        detected_at=datetime.now(timezone.utc),
        description=f"[{current_user.username}] {payload.description}",
        external_id=None,
        itop_ticket_id=None,
        cause_category=payload.cause_category,
        cause_label=payload.cause_label,
    )
    incident, node, created = incident_service.ingest_incident(db, ingest_payload)

    if not created:
        return _to_response(incident)

    cache_service.invalidate_prefix("kpi:")
    _dispatch_new_incident(background_tasks, incident, node)
    return _to_response(incident)


@router.get(
    "",
    response_model=IncidentListResponse,
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)
def list_incidents(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = Query(None),
    locality_id: int | None = Query(None),
    node_code: str | None = Query(None),
    source_tool: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Historique complet, filtrable et paginé — à la différence de
    /api/alerts/open (top-N d'incidents ouverts pour la vue temps réel), cet
    endpoint alimente une table d'incidents consultable sur toute la période
    (résolus compris), par nœud, localité, sévérité, outil source ou ticket.
    """
    return incident_service.list_incidents(
        db,
        status=status_filter,
        severity=severity,
        locality_id=locality_id,
        node_code=node_code,
        source_tool=source_tool,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/ingest/bulk",
    response_model=IncidentBulkIngestResponse,
    status_code=status.HTTP_200_OK,
)
def ingest_incidents_bulk(
    payload: IncidentBulkIngestPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    """Batch counterpart to /ingest, for a poller reconciling its whole active
    set in one call.

    Costs a single unit of the ingest rate limit, which is the point: the ETL
    posts every active alarm on every pass, and at NetXMS's ~1500 that is
    otherwise 150 minutes of quota per five-minute poll.

    The batch is a snapshot, not an append: alerts it no longer carries are
    treated as recovered and their incidents are resolved (see
    incident_service.reconcile_open_incidents). Post partial batches here and
    you will close incidents that are still live.

    It does not broadcast or notify — see incident_service.ingest_incidents_bulk
    for why. Anything that must reach a human on arrival belongs on /ingest.
    """
    result = incident_service.ingest_incidents_bulk(db, payload.incidents)
    if result["created"] or result["resolved"]:
        # Same invalidation /ingest does. Without it the dashboard keeps serving
        # the KPIs cached before the batch — which is how a pass that resolved
        # 190 incidents can still report a 0% resolution rate.
        cache_service.invalidate_prefix("kpi:")
    return result


@router.patch("/{incident_id}/resolve", response_model=IncidentIngestResponse)
def resolve_incident(
    incident_id: int,
    payload: ResolvePayload,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(*_RESOLVE_ROLES)),
):
    incident = incident_service.resolve_incident(db, incident_id, payload.resolved_at, payload.notes)
    cache_service.invalidate_prefix("kpi:")
    return _to_response(incident)


@router.patch("/{incident_id}/acknowledge", response_model=IncidentIngestResponse)
def acknowledge_incident(
    incident_id: int,
    payload: AcknowledgePayload,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(*_ACKNOWLEDGE_ROLES)),
):
    incident = incident_service.acknowledge_incident(db, incident_id, payload.acknowledged_at)
    # No cache to invalidate: acknowledging moves an incident from "open" to
    # "acknowledged" without changing any cached figure — the KPIs count
    # resolved against total, and the alerts endpoints are read straight from
    # the database. Resolving does change them, which is why it invalidates.
    return _to_response(incident)