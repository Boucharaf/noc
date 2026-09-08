"""
Incidents : consultation et actions humaines.

Il n'y a plus de route d'ingestion (`POST /api/incidents/ingest` et sa
variante bulk ont disparu) : le nouvel ETL écrit directement dans
fact_incident. Voir services/incident_service pour le détail.
"""
import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit, write_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.operations import User
from app.schemas.incidents import (
    SEVERITY_PATTERN,
    STATUS_PATTERN,
    AssignPayload,
    CommentPayload,
    EscalatePayload,
    IncidentDetail,
    IncidentListResponse,
    IncidentTimelineEntry,
    IncidentWorkloadOut,
    ManualIncidentPayload,
    ResolvePayload,
)
from app.services import incident_service

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

# Miroir de frontend/src/api/permissions.js. Le contrôle qui compte est
# celui-ci : le RBAC côté client n'est que du confort d'interface.
_VIEW_HISTORY = ("directeur", "chef_noc", "technicien")
_ACKNOWLEDGE = ("chef_noc", "technicien", "agent_terrain")
_RESOLVE = ("chef_noc", "technicien")
_MANUAL = ("directeur", "chef_noc", "technicien", "agent_terrain")
_ASSIGN = ("chef_noc",)
_ESCALATE = ("chef_noc", "technicien")


@router.get("", response_model=IncidentListResponse, dependencies=[Depends(read_rate_limit)])
def list_incidents(
    status_filter: str | None = Query(None, alias="status", pattern=STATUS_PATTERN),
    severity: str | None = Query(None, pattern=SEVERITY_PATTERN),
    locality_id: int | None = None,
    node_code: str | None = None,
    source_tool: str | None = None,
    cause_category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_VIEW_HISTORY)),
):
    return incident_service.list_incidents(
        db,
        status=status_filter,
        severity=severity,
        locality_id=locality_id,
        node_code=node_code,
        source_tool=source_tool,
        cause_category=cause_category,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


# Déclarées AVANT /{incident_id} : Starlette teste les routes dans l'ordre
# de déclaration, et « workload » comme « export.csv » seraient sinon
# capturés par le paramètre entier, qui répondrait 422.
@router.get("/workload", response_model=list[IncidentWorkloadOut])
def get_workload(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("directeur", "chef_noc", "technicien")),
):
    """Répartition des incidents ouverts par intervenant."""
    return incident_service.get_workload(db)


@router.get("/export.csv")
def export_incidents(
    status_filter: str | None = Query(None, alias="status", pattern=STATUS_PATTERN),
    severity: str | None = Query(None, pattern=SEVERITY_PATTERN),
    locality_id: int | None = None,
    node_code: str | None = None,
    source_tool: str | None = None,
    cause_category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_VIEW_HISTORY)),
):
    """Export CSV du résultat courant du filtre.

    Un exploitant produit ses propres tableaux d'analyse ; sans export il
    recopie les lignes à la main depuis l'écran. Le séparateur est le
    point-virgule et le fichier porte un BOM UTF-8, parce que la
    destination réelle est Excel en configuration francophone : une
    virgule y casse les colonnes, et sans BOM les accents deviennent
    illisibles.
    """
    rows = incident_service.list_incidents(
        db,
        status=status_filter,
        severity=severity,
        locality_id=locality_id,
        node_code=node_code,
        source_tool=source_tool,
        cause_category=cause_category,
        date_from=date_from,
        date_to=date_to,
        page=1,
        page_size=min(limit, 50000),
    )["items"]

    columns = [
        ("id", "ID"),
        ("detected_at", "Détecté le"),
        ("severity", "Gravité"),
        ("status", "Statut"),
        ("node_name", "Équipement"),
        ("locality", "Site"),
        ("region", "Région"),
        ("ministry", "Ministère"),
        ("source_tool", "Outil"),
        ("cause_label", "Cause"),
        ("description", "Description"),
        ("acknowledged_at", "Acquitté le"),
        ("resolved_at", "Résolu le"),
        ("mtta_minutes", "MTTA (min)"),
        ("mttr_minutes", "MTTR (min)"),
        ("downtime_minutes", "Indispo. (min)"),
        ("assigned_to_full_name", "Assigné à"),
        ("itop_ticket_ref", "Ticket iTop"),
    ]

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([label for _, label in columns])
    for item in rows:
        writer.writerow(
            ["" if item.get(key) is None else str(item.get(key)) for key, _ in columns]
        )

    now = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="incidents-{now}.csv"'},
    )


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return incident_service.get_incident(db, incident_id)


@router.get("/{incident_id}/timeline", response_model=list[IncidentTimelineEntry])
def get_timeline(
    incident_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return incident_service.get_timeline(db, incident_id)


@router.post(
    "/manual",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_rate_limit)],
)
def create_manual_incident(
    payload: ManualIncidentPayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_MANUAL)),
):
    """Panne constatée sur le terrain que les outils n'ont pas détectée."""
    return incident_service.create_manual(
        db,
        user,
        node_code=payload.node_code,
        severity=payload.severity,
        description=payload.description,
        cause_category=payload.cause_category,
    )


@router.patch("/{incident_id}/acknowledge", response_model=IncidentDetail)
def acknowledge(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ACKNOWLEDGE)),
):
    return incident_service.acknowledge(db, incident_id, user)


@router.patch("/{incident_id}/resolve", response_model=IncidentDetail)
def resolve(
    incident_id: int,
    payload: ResolvePayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_RESOLVE)),
):
    return incident_service.resolve(db, incident_id, user, payload.notes)


@router.post("/{incident_id}/assign", response_model=IncidentDetail)
def assign(
    incident_id: int,
    payload: AssignPayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ASSIGN)),
):
    return incident_service.assign(
        db, incident_id, user, payload.assigned_to_user_id, payload.note
    )


@router.post("/{incident_id}/escalate", response_model=IncidentDetail)
def escalate(
    incident_id: int,
    payload: EscalatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ESCALATE)),
):
    return incident_service.escalate(
        db, incident_id, user, payload.escalated_to_user_id, payload.reason
    )


@router.post("/{incident_id}/comment", response_model=list[IncidentTimelineEntry])
def comment(
    incident_id: int,
    payload: CommentPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return incident_service.comment(db, incident_id, user, payload.note)
