"""
Incidents : consultation et actions humaines.

CHANGEMENT MAJEUR par rapport à l'ancien backend : il n'y a plus
d'ingestion HTTP. L'ancien `/api/incidents/ingest` supposait que l'ETL
poussait chaque incident vers le backend ; le nouvel ETL écrit
directement dans `fact_incident` (etl/load/load_facts.py). Conserver un
endpoint d'ingestion créerait deux chemins d'écriture concurrents sur la
même table, avec deux conventions d'`external_id` différentes et donc des
doublons.

Le backend est donc LECTEUR de fact_incident, avec deux exceptions
assumées et sans risque de collision avec l'ETL :

* les incidents manuels, écrits avec `source_tool='manual'` — une valeur
  qu'aucun connecteur ETL ne produit, donc la contrainte
  UNIQUE (source_tool, external_id) les isole complètement ;
* l'acquittement et la résolution depuis le dashboard, qui posent
  `acknowledged_at` / `resolved_at` / `status`. L'UPSERT de l'ETL les
  préserve : il applique COALESCE sur ces colonnes plutôt que de les
  écraser (voir etl/load/load_facts.py::load_incidents). C'est la raison
  pour laquelle ces deux actions sont sûres, et pourquoi l'assignation,
  elle, vit dans une table à part (ops_incident_assignment).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.operations import IncidentAssignment, IncidentTimeline, User
from app.models.warehouse import Incident, Node
from app.services import cache_service, kpi_service
from app.services.alert_broadcaster import publish_alert

logger = logging.getLogger(__name__)

MANUAL_SOURCE_TOOL = "manual"

_SELECT_COLUMNS = """
    i.id, i.source_tool, i.external_id, i.node_id, i.node_code, i.node_name,
    i.locality_id, i.locality, i.region, i.ministry,
    i.severity, i.status, i.description,
    i.cause_category, i.cause_label,
    i.detected_at, i.acknowledged_at, i.resolved_at,
    i.mtta_minutes, i.mttr_minutes, i.downtime_minutes,
    i.itop_ticket_ref, i.is_maintenance,
    a.assigned_to_user_id, u.full_name AS assigned_to_full_name,
    COALESCE(a.escalation_level, 0) AS escalation_level,
    COALESCE(a.impact_scope, 1)     AS impact_scope,
    a.incident_type,
    COALESCE(a.reopened_count, 0)   AS reopened_count,
    EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60 AS age_minutes
"""

_FROM = """
    FROM v_incident i
    LEFT JOIN ops_incident_assignment a ON a.incident_id = i.id
    LEFT JOIN dim_user u ON u.id = a.assigned_to_user_id
"""


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "source_tool": row["source_tool"],
        "external_id": row["external_id"],
        "node_id": row["node_id"],
        "node_code": row["node_code"] or "—",
        "node_name": row["node_name"] or "—",
        "locality_id": row["locality_id"],
        "locality": row["locality"] or "—",
        "region": row["region"],
        "ministry": row["ministry"],
        "severity": row["severity"],
        "status": row["status"],
        "description": row["description"],
        "cause_category": row["cause_category"],
        "cause_label": row["cause_label"],
        "detected_at": row["detected_at"],
        "acknowledged_at": row["acknowledged_at"],
        "resolved_at": row["resolved_at"],
        "mtta_minutes": row["mtta_minutes"],
        "mttr_minutes": row["mttr_minutes"],
        "downtime_minutes": row["downtime_minutes"],
        "itop_ticket_ref": row["itop_ticket_ref"],
        "is_maintenance": bool(row["is_maintenance"]),
        "assigned_to_user_id": row["assigned_to_user_id"],
        "assigned_to_full_name": row["assigned_to_full_name"],
        "escalation_level": int(row["escalation_level"]),
        "impact_scope": int(row["impact_scope"]),
        "incident_type": row["incident_type"],
        "reopened_count": int(row["reopened_count"]),
        "age_minutes": int(row["age_minutes"]) if row["age_minutes"] is not None else None,
    }


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def list_incidents(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    locality_id: int | None = None,
    node_code: str | None = None,
    source_tool: str | None = None,
    cause_category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    page = max(1, page)
    page_size = max(1, min(200, page_size))

    where = ["TRUE"]
    params: dict = {}

    if status:
        where.append("i.status = :status")
        params["status"] = status
    if severity:
        where.append("i.severity = :severity")
        params["severity"] = severity
    if locality_id is not None:
        where.append("i.locality_id = :locality_id")
        params["locality_id"] = locality_id
    if node_code:
        # dim_node n'a pas de colonne `code` : v_node expose le nom comme
        # code, donc le filtre porte sur le nom. Recherche partielle,
        # insensible à la casse — un opérateur tape rarement le nom exact.
        where.append("i.node_code ILIKE :node_code")
        params["node_code"] = f"%{node_code}%"
    if source_tool:
        where.append("i.source_tool = :source_tool")
        params["source_tool"] = source_tool
    if cause_category:
        where.append("i.cause_category = :cause_category")
        params["cause_category"] = cause_category
    if date_from:
        where.append("i.detected_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("i.detected_at < :date_to")
        params["date_to"] = date_to

    clause = " AND ".join(where)

    total = db.execute(
        text(f"SELECT count(*) {_FROM} WHERE {clause}"), params
    ).scalar() or 0

    rows = db.execute(
        text(
            f"""
            SELECT {_SELECT_COLUMNS} {_FROM}
            WHERE {clause}
            ORDER BY i.detected_at DESC NULLS LAST, i.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "pages": (int(total) + page_size - 1) // page_size,
    }


def get_workload(db: Session) -> list[dict]:
    """Charge par intervenant — la question du Chef NOC avant d'assigner.

    La ligne `assigned_to_user_id = NULL` est délibérément conservée : les
    incidents que personne ne traite sont l'information la plus utile de
    ce tableau, et les écarter pour « ne garder que les agents » ferait
    disparaître exactement ce qu'on cherche.
    """
    rows = db.execute(
        text(
            """
            SELECT
                a.assigned_to_user_id                                        AS user_id,
                u.full_name,
                u.username,
                u.role,
                count(*)                                                     AS open_incidents,
                count(*) FILTER (WHERE i.severity = 'critical')              AS critical,
                count(*) FILTER (WHERE i.severity = 'high')                  AS high,
                count(*) FILTER (WHERE i.status = 'open')                    AS unacknowledged,
                avg(EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60)        AS avg_age_minutes,
                max(EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60)        AS oldest_age_minutes
            FROM v_incident i
            LEFT JOIN ops_incident_assignment a ON a.incident_id = i.id
            LEFT JOIN dim_user u ON u.id = a.assigned_to_user_id
            WHERE i.status IN ('open','acknowledged') AND NOT i.is_maintenance
            GROUP BY a.assigned_to_user_id, u.full_name, u.username, u.role
            ORDER BY (a.assigned_to_user_id IS NULL) DESC, count(*) DESC
            """
        )
    ).mappings().all()

    return [
        {
            "user_id": r["user_id"],
            "full_name": r["full_name"] or ("Non assigné" if r["user_id"] is None else "—"),
            "username": r["username"],
            "role": r["role"],
            "open_incidents": int(r["open_incidents"]),
            "critical": int(r["critical"]),
            "high": int(r["high"]),
            "unacknowledged": int(r["unacknowledged"]),
            "avg_age_minutes": round(float(r["avg_age_minutes"]), 1)
            if r["avg_age_minutes"] is not None
            else None,
            "oldest_age_minutes": round(float(r["oldest_age_minutes"]), 1)
            if r["oldest_age_minutes"] is not None
            else None,
        }
        for r in rows
    ]


def get_incident(db: Session, incident_id: int) -> dict:
    row = db.execute(
        text(f"SELECT {_SELECT_COLUMNS} {_FROM} WHERE i.id = :id"), {"id": incident_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")

    incident = _row_to_dict(row)
    incident["timeline"] = get_timeline(db, incident_id)
    return incident


def get_timeline(db: Session, incident_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT t.id, t.user_id, u.full_name AS user_full_name,
                   t.action, t.note, t.created_at
            FROM ops_incident_timeline t
            LEFT JOIN dim_user u ON u.id = t.user_id
            WHERE t.incident_id = :id
            ORDER BY t.created_at ASC, t.id ASC
            """
        ),
        {"id": incident_id},
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _log(db: Session, incident_id: int, user: User | None, action: str, note: str | None = None):
    db.add(
        IncidentTimeline(
            incident_id=incident_id,
            user_id=user.id if user else None,
            action=action,
            note=note,
        )
    )


def acknowledge(db: Session, incident_id: int, user: User) -> dict:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")

    if incident.acknowledged_at is None:
        now = datetime.now(UTC)
        incident.acknowledged_at = now
        if incident.detected_at:
            incident.mtta_minutes = round(
                (now - incident.detected_at).total_seconds() / 60, 1
            )
        # Le statut n'est écrasé que s'il est encore ouvert : un incident
        # que l'outil source a déjà clos entre-temps ne doit pas être
        # rouvert par un acquittement tardif du dashboard.
        if incident.status in (None, "open", "new"):
            incident.status = "acknowledged"

    _log(db, incident_id, user, "acknowledged")
    db.commit()
    kpi_service.invalidate_cache()
    return get_incident(db, incident_id)


def resolve(db: Session, incident_id: int, user: User, notes: str) -> dict:
    if not (notes or "").strip():
        # Même règle que côté frontend (api/alerts.js) : une résolution
        # sans note est une perte d'information pour le post-mortem.
        raise HTTPException(
            status_code=422, detail="Une note de résolution est obligatoire."
        )

    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")

    now = datetime.now(UTC)
    if incident.resolved_at is None:
        incident.resolved_at = now
        if incident.detected_at:
            minutes = round((now - incident.detected_at).total_seconds() / 60, 1)
            incident.mttr_minutes = minutes
            if incident.downtime_minutes is None:
                incident.downtime_minutes = minutes
    incident.status = "resolved"

    _log(db, incident_id, user, "resolved", notes.strip())
    db.commit()
    kpi_service.invalidate_cache()
    return get_incident(db, incident_id)


def assign(db: Session, incident_id: int, user: User, assignee_id: int, note: str | None) -> dict:
    if db.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")
    if db.get(User, assignee_id) is None:
        raise HTTPException(status_code=404, detail="Destinataire introuvable.")

    assignment = db.get(IncidentAssignment, incident_id) or IncidentAssignment(
        incident_id=incident_id
    )
    assignment.assigned_to_user_id = assignee_id
    assignment.updated_at = datetime.now(UTC)
    db.merge(assignment)

    _log(db, incident_id, user, "assigned", note)
    db.commit()
    return get_incident(db, incident_id)


def escalate(db: Session, incident_id: int, user: User, escalate_to_id: int, reason: str) -> dict:
    if db.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")

    assignment = db.get(IncidentAssignment, incident_id) or IncidentAssignment(
        incident_id=incident_id
    )
    assignment.escalation_level = (assignment.escalation_level or 0) + 1
    assignment.escalated_at = datetime.now(UTC)
    assignment.escalated_to_user_id = escalate_to_id
    assignment.updated_at = datetime.now(UTC)
    db.merge(assignment)

    _log(db, incident_id, user, "escalated", reason)
    db.commit()
    return get_incident(db, incident_id)


def comment(db: Session, incident_id: int, user: User, note: str) -> list[dict]:
    if db.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident introuvable.")
    _log(db, incident_id, user, "commented", note)
    db.commit()
    return get_timeline(db, incident_id)


# ---------------------------------------------------------------------------
# Signalement manuel
# ---------------------------------------------------------------------------
def create_manual(
    db: Session,
    user: User,
    *,
    node_code: str,
    severity: str,
    description: str,
    cause_category: str | None = None,
) -> dict:
    """Panne constatée sur le terrain que les outils n'ont pas détectée.

    L'`external_id` est construit comme `manual-<user_id>-<timestamp>` :
    il doit rester unique au sein de source_tool='manual' à cause de la
    contrainte UNIQUE (source_tool, external_id) de fact_incident, et
    l'horodatage à la microseconde suffit ici (un même utilisateur ne
    crée pas deux signalements dans la même microseconde).
    """
    node = (
        db.query(Node)
        .filter(Node.name.ilike(node_code))
        .first()
    )
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun équipement ne correspond à « {node_code} ».",
        )

    now = datetime.now(UTC)
    incident = Incident(
        source_tool=MANUAL_SOURCE_TOOL,
        external_id=f"manual-{user.id}-{now.strftime('%Y%m%d%H%M%S%f')}",
        node_id=node.id,
        status="open",
        severity=severity,           # déjà dans le vocabulaire normalisé
        cause_category=cause_category or "non_identifie",
        detected_at=now,
        description=description,
    )
    db.add(incident)
    db.flush()

    _log(db, incident.id, user, "created", "Signalement manuel")
    db.commit()
    kpi_service.invalidate_cache()

    # Même canal que les incidents découverts par le veilleur : un
    # signalement terrain doit remonter sur le mur d'alertes en direct.
    publish_alert(
        {
            "type": "incident",
            "id": incident.id,
            "node_code": node.name,
            "node_name": node.name,
            "severity": severity,
            "status": "open",
            "description": description,
            "source_tool": MANUAL_SOURCE_TOOL,
            "detected_at": now.isoformat(),
        }
    )
    cache_service.invalidate_prefix("noc:alerts:")
    return get_incident(db, incident.id)
