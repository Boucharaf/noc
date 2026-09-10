"""
Interventions de terrain.

CE QUI A CHANGÉ. L'ancien service joignait `v_node` et `dim_user` en SQL
pour retrouver le nom de l'équipement d'une intervention. Ces tables
n'existent plus : le parc vit dans l'instantané Redis. Le nom de
l'équipement est donc figé sur l'intervention à sa création — comme pour
`ops_alert_state` — et complété à la lecture par l'instantané quand
l'équipement y est encore.

POURQUOI FIGER LE NOM. Une intervention se consulte des mois plus tard, en
revue ou en litige. Si l'équipement a été retiré du parc entre-temps, la
fiche doit rester lisible. C'est la même règle que pour les alertes, et pour
la même raison.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertTimeline, FieldIntervention, User
from app.services import live_service

logger = logging.getLogger(__name__)

# `en_route` et `on_site` distinguent le trajet de la présence : c'est ce
# qui permet de mesurer un délai d'acheminement séparément du temps
# d'intervention, deux chiffres qui n'ont pas les mêmes leviers.
VALID_STATUSES = ("scheduled", "en_route", "on_site", "done", "cancelled")

# Statuts depuis lesquels une transition reste possible. Une intervention
# terminée ou annulée ne redevient pas « en route » : corriger une erreur
# de saisie passe par une nouvelle intervention, pour que le journal reste
# le reflet de ce qui s'est réellement passé.
CLOSED_STATUSES = ("done", "cancelled")


def _serialise(row: FieldIntervention, agent_name: str | None,
               node_state: str | None) -> dict:
    return {
        "id": row.id,
        "alert_key": row.alert_key,
        "node_key": row.node_key,
        "node_name": row.node_name,
        # Renseigné seulement si l'équipement est encore dans l'instantané.
        # None veut dire « retiré du parc », ce que la fiche doit montrer.
        "node_state": node_state,
        "agent_user_id": row.agent_user_id,
        "agent_name": agent_name,
        "status": row.status,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "checkin_latitude": row.checkin_latitude,
        "checkin_longitude": row.checkin_longitude,
        "report_text": row.report_text,
        "photo_urls": row.photo_urls or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _decorate(db: Session, rows: list[FieldIntervention]) -> list[dict]:
    """Complète les lignes avec le nom de l'agent et l'état de l'équipement.

    Les noms d'agents sont chargés en UNE requête, et l'instantané lu UNE
    fois : une intervention par requête produirait autant d'allers-retours
    qu'il y a de lignes à l'écran.
    """
    agent_ids = {row.agent_user_id for row in rows if row.agent_user_id}
    names: dict[int, str] = {}
    if agent_ids:
        names = {
            r.id: r.full_name or r.username
            for r in db.execute(
                select(User.id, User.full_name, User.username).where(
                    User.id.in_(agent_ids)
                )
            )
        }

    states: dict[str, str] = {}
    try:
        states = {n["id"]: n.get("state") for n in await live_service.get_nodes()}
    except live_service.SnapshotUnavailable:
        # La liste des interventions doit rester consultable quand la
        # collecte est arrêtée : c'est même le moment où un agent en a le
        # plus besoin. On se passe simplement de l'état courant.
        logger.info("Instantané indisponible — interventions servies sans l'état du parc")

    return [
        _serialise(row, names.get(row.agent_user_id), states.get(row.node_key))
        for row in rows
    ]


async def list_for_agent(
    db: Session, agent_user_id: int, status: str | None = None
) -> list[dict]:
    query = select(FieldIntervention).where(
        FieldIntervention.agent_user_id == agent_user_id
    )
    if status:
        query = query.where(FieldIntervention.status == status)
    rows = list(
        db.execute(
            query.order_by(FieldIntervention.scheduled_at.desc().nullslast())
        ).scalars()
    )
    return await _decorate(db, rows)


async def list_all(db: Session, status: str | None = None, limit: int = 200) -> list[dict]:
    query = select(FieldIntervention)
    if status:
        query = query.where(FieldIntervention.status == status)
    rows = list(
        db.execute(
            query.order_by(FieldIntervention.scheduled_at.desc().nullslast()).limit(limit)
        ).scalars()
    )
    return await _decorate(db, rows)


async def get_one(db: Session, intervention_id: int) -> dict:
    row = db.get(FieldIntervention, intervention_id)
    if row is None:
        raise HTTPException(404, "Intervention introuvable.")
    return (await _decorate(db, [row]))[0]


async def create(
    db: Session,
    node_key: str,
    agent_user_id: int,
    alert_key: str | None = None,
    scheduled_at: datetime | None = None,
) -> dict:
    node = await live_service.get_node(node_key)
    if node is None:
        raise HTTPException(
            404,
            f"Aucun équipement « {node_key} » dans l'instantané courant. "
            "Vérifier l'identifiant dans l'inventaire.",
        )

    agent = db.get(User, agent_user_id)
    if agent is None or not agent.is_active:
        raise HTTPException(404, "Agent inconnu ou désactivé.")

    row = FieldIntervention(
        node_key=node_key,
        # Figé à la création — voir l'en-tête du module.
        node_name=node.get("name"),
        alert_key=alert_key,
        agent_user_id=agent_user_id,
        scheduled_at=scheduled_at,
        status="scheduled",
    )
    db.add(row)

    if alert_key:
        db.add(
            AlertTimeline(
                alert_key=alert_key,
                user_id=agent_user_id,
                action="field_dispatch",
                note=f"Intervention programmée sur {node.get('name')}",
            )
        )

    db.commit()
    db.refresh(row)
    return (await _decorate(db, [row]))[0]


async def update_status(
    db: Session,
    intervention_id: int,
    status: str,
    latitude: float | None = None,
    longitude: float | None = None,
    report_text: str | None = None,
) -> dict:
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"Statut inconnu : {status}")

    row = db.get(FieldIntervention, intervention_id)
    if row is None:
        raise HTTPException(404, "Intervention introuvable.")
    if row.status in CLOSED_STATUSES:
        raise HTTPException(
            409,
            f"Intervention déjà « {row.status} ». Créer une nouvelle "
            "intervention plutôt que de modifier celle-ci : le journal doit "
            "refléter ce qui s'est réellement passé.",
        )

    now = datetime.now(timezone.utc)
    row.status = status

    # Le pointage géographique n'est enregistré qu'à l'arrivée sur site :
    # une position relevée au moment de clore le rapport, depuis le bureau,
    # n'attesterait rien.
    if status == "on_site":
        row.started_at = row.started_at or now
        if latitude is not None and longitude is not None:
            row.checkin_latitude = latitude
            row.checkin_longitude = longitude
    elif status in CLOSED_STATUSES:
        row.completed_at = now

    if report_text:
        row.report_text = report_text

    if row.alert_key and status == "done":
        db.add(
            AlertTimeline(
                alert_key=row.alert_key,
                user_id=row.agent_user_id,
                action="field_done",
                note=report_text or "Intervention terminée",
            )
        )

    db.commit()
    db.refresh(row)
    return (await _decorate(db, [row]))[0]
