"""Interventions terrain (ops_field_intervention)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.operations import FieldIntervention, IncidentTimeline, User
from app.models.warehouse import Node

VALID_STATUSES = ("scheduled", "en_route", "on_site", "done", "cancelled")


def _serialize_rows(db: Session, where: str, params: dict) -> list[dict]:
    rows = db.execute(
        text(
            f"""
            SELECT f.id, f.incident_id, f.node_id,
                   COALESCE(n.name, '—') AS node_name,
                   COALESCE(n.locality, '—') AS locality,
                   f.agent_user_id, u.full_name AS agent_full_name,
                   f.status, f.scheduled_at, f.started_at, f.completed_at,
                   f.checkin_latitude, f.checkin_longitude,
                   f.report_text, f.photo_urls, f.created_at
            FROM ops_field_intervention f
            LEFT JOIN v_node n  ON n.node_id = f.node_id
            LEFT JOIN dim_user u ON u.id = f.agent_user_id
            WHERE {where}
            ORDER BY COALESCE(f.scheduled_at, f.created_at) DESC
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def list_for_agent(db: Session, agent_user_id: int, status: str | None = None) -> list[dict]:
    where = "f.agent_user_id = :agent_id"
    params = {"agent_id": agent_user_id}
    if status:
        where += " AND f.status = :status"
        params["status"] = status
    return _serialize_rows(db, where, params)


def list_all(db: Session, status: str | None = None) -> list[dict]:
    where = "TRUE"
    params: dict = {}
    if status:
        where = "f.status = :status"
        params["status"] = status
    return _serialize_rows(db, where, params)


def get_one(db: Session, intervention_id: int) -> dict:
    rows = _serialize_rows(db, "f.id = :id", {"id": intervention_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Intervention introuvable.")
    return rows[0]


def create(db: Session, agent: User, node_id: int, incident_id: int | None, scheduled_at) -> dict:
    if db.get(Node, node_id) is None:
        raise HTTPException(status_code=404, detail="Équipement introuvable.")

    intervention = FieldIntervention(
        node_id=node_id,
        incident_id=incident_id,
        agent_user_id=agent.id,
        scheduled_at=scheduled_at,
        status="scheduled",
    )
    db.add(intervention)

    if incident_id:
        db.add(
            IncidentTimeline(
                incident_id=incident_id,
                user_id=agent.id,
                action="commented",
                note="Intervention terrain planifiée",
            )
        )
    db.commit()
    db.refresh(intervention)
    return get_one(db, intervention.id)


def update_status(db: Session, intervention_id: int, agent: User, status: str) -> dict:
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Statut d'intervention inconnu.")

    intervention = db.get(FieldIntervention, intervention_id)
    if intervention is None:
        raise HTTPException(status_code=404, detail="Intervention introuvable.")
    # Un agent ne pilote que ses propres tournées : sans ce contrôle,
    # l'identifiant seul suffirait à modifier celle d'un collègue.
    if intervention.agent_user_id != agent.id and agent.role not in ("chef_noc", "directeur"):
        raise HTTPException(status_code=403, detail="Cette intervention ne vous est pas assignée.")

    now = datetime.now(UTC)
    intervention.status = status
    if status == "en_route" and intervention.started_at is None:
        intervention.started_at = now
    if status in ("done", "cancelled"):
        intervention.completed_at = now

    db.commit()
    return get_one(db, intervention_id)


def submit_report(
    db: Session,
    intervention_id: int,
    agent: User,
    *,
    report_text: str,
    checkin_latitude: float | None,
    checkin_longitude: float | None,
    photo_urls: list[str],
) -> dict:
    intervention = db.get(FieldIntervention, intervention_id)
    if intervention is None:
        raise HTTPException(status_code=404, detail="Intervention introuvable.")
    if intervention.agent_user_id != agent.id and agent.role not in ("chef_noc", "directeur"):
        raise HTTPException(status_code=403, detail="Cette intervention ne vous est pas assignée.")

    now = datetime.now(UTC)
    intervention.report_text = report_text
    intervention.checkin_latitude = checkin_latitude
    intervention.checkin_longitude = checkin_longitude
    intervention.photo_urls = photo_urls or []
    intervention.status = "done"
    intervention.completed_at = now

    # Le compte rendu terrain remonte dans la chronologie de l'incident :
    # c'est souvent la seule explication de la cause réelle d'une panne.
    if intervention.incident_id:
        db.add(
            IncidentTimeline(
                incident_id=intervention.incident_id,
                user_id=agent.id,
                action="commented",
                note=f"Compte rendu terrain : {report_text}",
            )
        )

    db.commit()
    return get_one(db, intervention_id)
