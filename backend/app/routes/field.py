"""
Interventions terrain.

Les routes de consultation ne renvoient que les tournées de l'agent
connecté : aucun `user_id` en paramètre, il est déduit du jeton. Le Chef
NOC et le Directeur voient l'ensemble, pour pouvoir superviser.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.operations import User
from app.schemas.field import (
    FieldInterventionCreate,
    FieldInterventionOut,
    FieldInterventionReport,
    FieldInterventionStatusUpdate,
)
from app.services import field_service

router = APIRouter(prefix="/api/field-interventions", tags=["terrain"])

_SUPERVISORS = ("chef_noc", "directeur")


@router.get("", response_model=list[FieldInterventionOut])
def list_interventions(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role in _SUPERVISORS:
        return field_service.list_all(db, status_filter)
    return field_service.list_for_agent(db, user.id, status_filter)


@router.post("", response_model=FieldInterventionOut, status_code=status.HTTP_201_CREATED)
def create_intervention(
    payload: FieldInterventionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("agent_terrain", "chef_noc", "directeur")),
):
    return field_service.create(
        db, user, payload.node_id, payload.incident_id, payload.scheduled_at
    )


@router.patch("/{intervention_id}/status", response_model=FieldInterventionOut)
def update_status(
    intervention_id: int,
    payload: FieldInterventionStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return field_service.update_status(db, intervention_id, user, payload.status)


@router.post("/{intervention_id}/report", response_model=FieldInterventionOut)
def submit_report(
    intervention_id: int,
    payload: FieldInterventionReport,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return field_service.submit_report(
        db,
        intervention_id,
        user,
        report_text=payload.report_text,
        checkin_latitude=payload.checkin_latitude,
        checkin_longitude=payload.checkin_longitude,
        photo_urls=payload.photo_urls,
    )
