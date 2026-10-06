"""
Routes de terrain — la tournée d'un agent, depuis son téléphone.

DEUX PARTICULARITÉS qui expliquent que ce module reste séparé :

  * ces routes sont les seules accessibles au rôle `agent_terrain`, qui n'a
    aucun droit d'exploitation ailleurs — il constate et rend compte, il ne
    décide pas. Il ne voit et ne fait avancer que SES interventions ;
  * elles sont appelées depuis un téléphone, souvent en réseau dégradé.
    Elles doivent donc rester servies même quand la collecte est arrêtée :
    c'est précisément le moment où un agent est sur le terrain.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import FieldIntervention, User
from app.services import field_service

router = APIRouter(prefix="/api/field", tags=["terrain"])

DISPATCHERS = ("directeur", "chef_noc", "technicien")

_STATUS_PATTERN = r"^(scheduled|en_route|on_site|done|cancelled)$"


class InterventionCreate(BaseModel):
    # Clé de l'équipement dans le parc fusionné (`<outil>:<référence>`), et
    # non un entier : il n'y a plus de table d'équipements dans le NOC.
    node_key: str = Field(..., min_length=1, max_length=300)
    alert_key: str | None = Field(None, max_length=300)
    agent_user_id: int
    scheduled_at: datetime | None = None


class StatusUpdate(BaseModel):
    status: str = Field(..., pattern=_STATUS_PATTERN)
    # Position relevée au pointage, pour attester la présence sur site.
    # N'est enregistrée qu'à l'arrivée (`on_site`) : relevée au moment de
    # clore le rapport, depuis le bureau, elle n'attesterait rien.
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    report_text: str | None = Field(None, max_length=4000)


def _ensure_visible(db: Session, intervention_id: int, user: User) -> None:
    """Un agent de terrain n'accède qu'aux interventions qui lui sont confiées.

    404 et non 403 : répondre « interdit » confirmerait l'existence d'une
    intervention qui n'est pas la sienne.
    """
    if user.role in DISPATCHERS:
        return
    row = db.get(FieldIntervention, intervention_id)
    if row is None or row.agent_user_id != user.id:
        raise HTTPException(404, "Intervention introuvable.")


@router.get("/interventions")
async def list_interventions(
    status: str | None = Query(None, pattern=_STATUS_PATTERN),
    mine: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Interventions.

    `mine` par défaut à vrai : un agent qui ouvre l'application veut SA
    tournée, pas celle de toute l'équipe. Les rôles d'encadrement peuvent
    demander la vue complète.
    """
    if mine or user.role == "agent_terrain":
        return await field_service.list_for_agent(db, user.id, status)
    return await field_service.list_all(db, status)


@router.get("/interventions/{intervention_id}")
async def get_intervention(
    intervention_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_visible(db, intervention_id, user)
    return await field_service.get_one(db, intervention_id)


@router.post("/interventions", status_code=201)
async def create_intervention(
    payload: InterventionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*DISPATCHERS)),
):
    return await field_service.create(
        db,
        node_key=payload.node_key,
        agent_user_id=payload.agent_user_id,
        alert_key=payload.alert_key,
        scheduled_at=payload.scheduled_at,
    )


@router.patch("/interventions/{intervention_id}")
async def update_intervention(
    intervention_id: int,
    payload: StatusUpdate = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_visible(db, intervention_id, user)
    return await field_service.update_status(
        db,
        intervention_id,
        payload.status,
        latitude=payload.latitude,
        longitude=payload.longitude,
        report_text=payload.report_text,
    )
