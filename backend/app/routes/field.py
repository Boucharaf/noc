from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.field import (
    FieldInterventionCreate,
    FieldInterventionOut,
    FieldInterventionReport,
    FieldInterventionStatusUpdate,
)
from app.services import field_service

router = APIRouter(
    prefix="/api/field-interventions",
    tags=["field"],
    dependencies=[Depends(get_current_user)],
)

# Une tournée est assignée à un agent précis (agent_user_id) : ces routes ne
# donnent accès qu'aux interventions du compte connecté. Le Chef NOC/
# Directeur planifient et suivent l'ensemble des tournées depuis une vue
# d'équipe séparée — pas encore construite, voir la note dans
# app/services/field_service.py.
_AGENT_ONLY = Depends(require_role("agent_terrain"))


@router.get("", response_model=list[FieldInterventionOut])
def list_my_interventions(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = _AGENT_ONLY,
):
    return field_service.list_my_interventions(db, current_user.id, status)


@router.post("", response_model=FieldInterventionOut, status_code=201)
def create_intervention(
    payload: FieldInterventionCreate,
    db: Session = Depends(get_db),
    current_user: User = _AGENT_ONLY,
):
    return field_service.create_intervention(db, current_user.id, payload)


@router.patch("/{intervention_id}/status", response_model=FieldInterventionOut)
def update_status(
    intervention_id: int,
    payload: FieldInterventionStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = _AGENT_ONLY,
):
    return field_service.update_status(db, intervention_id, current_user.id, payload.status)


@router.post("/{intervention_id}/report", response_model=FieldInterventionOut)
def submit_report(
    intervention_id: int,
    payload: FieldInterventionReport,
    db: Session = Depends(get_db),
    current_user: User = _AGENT_ONLY,
):
    return field_service.submit_report(db, intervention_id, current_user.id, payload)
