"""Cycle de vie d'une intervention terrain (FieldIntervention).

C'est le cœur du métier de l'Agent Terrain — sans ce service, son rôle se
limite à "peut se connecter" (voir le commentaire en tête de
app/models/operations.py). Volontairement séparé d'incident_service : une
intervention peut exister sans incident (tournée de routine, maintenance
préventive), et le déroulé (planifiée → en route → sur site → terminée)
n'a pas d'équivalent dans le cycle de vie d'un incident.
"""

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dimension import Node
from app.models.operations import FieldIntervention
from app.schemas.field import FieldInterventionCreate, FieldInterventionReport

# Ordre du cycle de vie : une transition ne peut qu'avancer (jamais sauter en
# arrière), sauf vers "cancelled" qui est toujours permis tant que
# l'intervention n'est pas déjà terminée.
_STATUS_ORDER = ("scheduled", "en_route", "on_site", "done")


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _serialize(intervention: FieldIntervention) -> dict:
    return {
        "id": intervention.id,
        "incident_id": intervention.incident_id,
        "node_id": intervention.node_id,
        "node_name": intervention.node.name if intervention.node else None,
        "status": intervention.status,
        "scheduled_at": intervention.scheduled_at,
        "started_at": intervention.started_at,
        "completed_at": intervention.completed_at,
        "report_text": intervention.report_text,
    }


def list_my_interventions(
    db: Session, agent_user_id: int, status: str | None = None
) -> list[dict]:
    query = db.query(FieldIntervention).filter(
        FieldIntervention.agent_user_id == agent_user_id
    )
    if status:
        query = query.filter(FieldIntervention.status == status)
    rows = query.order_by(FieldIntervention.scheduled_at.asc().nullslast()).all()
    return [_serialize(r) for r in rows]


def get_intervention(db: Session, intervention_id: int) -> FieldIntervention:
    intervention = db.get(FieldIntervention, intervention_id)
    if intervention is None:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return intervention


def create_intervention(
    db: Session, agent_user_id: int, payload: FieldInterventionCreate
) -> dict:
    node = db.get(Node, payload.node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Nœud {payload.node_id} introuvable")

    intervention = FieldIntervention(
        incident_id=payload.incident_id,
        node_id=payload.node_id,
        agent_user_id=agent_user_id,
        status="scheduled",
        scheduled_at=_to_naive_utc(payload.scheduled_at),
    )
    db.add(intervention)
    db.commit()
    db.refresh(intervention)
    return _serialize(intervention)


def _assert_owner(intervention: FieldIntervention, agent_user_id: int) -> None:
    if intervention.agent_user_id != agent_user_id:
        # Un agent ne voit/ne modifie que ses propres tournées — le
        # Chef NOC/Directeur passent par une vue séparée (pas encore
        # exposée) plutôt que par ces routes réservées à l'agent assigné.
        raise HTTPException(
            status_code=403, detail="Cette intervention n'est pas assignée à cet agent."
        )


def update_status(
    db: Session, intervention_id: int, agent_user_id: int, new_status: str
) -> dict:
    intervention = get_intervention(db, intervention_id)
    _assert_owner(intervention, agent_user_id)

    if new_status == "cancelled":
        if intervention.status == "done":
            raise HTTPException(
                status_code=409, detail="Une intervention terminée ne peut plus être annulée."
            )
        intervention.status = "cancelled"
        db.commit()
        db.refresh(intervention)
        return _serialize(intervention)

    if new_status not in _STATUS_ORDER:
        raise HTTPException(status_code=400, detail=f"Statut invalide '{new_status}'.")

    current_index = (
        _STATUS_ORDER.index(intervention.status)
        if intervention.status in _STATUS_ORDER
        else -1
    )
    new_index = _STATUS_ORDER.index(new_status)
    if new_index <= current_index:
        raise HTTPException(
            status_code=409,
            detail=f"Impossible de repasser de '{intervention.status}' à '{new_status}'.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if new_status == "en_route" and intervention.started_at is None:
        intervention.started_at = now
    if new_status == "done":
        intervention.completed_at = now

    intervention.status = new_status
    db.commit()
    db.refresh(intervention)
    return _serialize(intervention)


def submit_report(
    db: Session, intervention_id: int, agent_user_id: int, payload: FieldInterventionReport
) -> dict:
    """Check-in géolocalisé + compte-rendu — marque l'intervention terminée.

    La géoloc n'est qu'enregistrée, jamais utilisée pour rejeter le
    compte-rendu (pas de vérification de distance au nœud ici) : un Agent
    terrain peut légitimement rédiger son rapport une fois reparti, un GPS
    imprécis en zone rurale ne doit pas bloquer la clôture d'une
    intervention réellement effectuée.
    """
    intervention = get_intervention(db, intervention_id)
    _assert_owner(intervention, agent_user_id)

    if intervention.status == "cancelled":
        raise HTTPException(
            status_code=409, detail="Une intervention annulée ne peut pas recevoir de rapport."
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    intervention.checkin_latitude = payload.checkin_latitude
    intervention.checkin_longitude = payload.checkin_longitude
    intervention.report_text = payload.report_text
    intervention.photo_urls = json.dumps(payload.photo_urls)
    if intervention.started_at is None:
        intervention.started_at = now
    intervention.completed_at = now
    intervention.status = "done"

    db.commit()
    db.refresh(intervention)
    return _serialize(intervention)
