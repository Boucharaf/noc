"""
Fenêtres de maintenance planifiée (ops_maintenance_window).

Deux origines possibles :

* manuelle — créée depuis le dashboard, `created_by_user_id` renseigné ;
* importée — poussée par l'ETL via POST /api/internal/maintenance-windows,
  `source_tool` + `external_id` renseignés (mode maintenance Zabbix,
  downtime Centreon, etc.).

Toute fenêtre avec `suppress_alerts` neutralise les incidents qu'elle
recouvre dans la vue `v_incident` (colonne `is_maintenance`), donc dans
tous les KPI et le SLA.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.operations import MaintenanceWindow, User
from app.models.warehouse import Node
from app.services import kpi_service


def _serialize(db: Session, where: str, params: dict) -> list[dict]:
    rows = db.execute(
        text(
            f"""
            SELECT w.id, w.node_id, n.name AS node_name,
                   w.locality_id, l.name AS locality_name,
                   w.reason, w.starts_at, w.ends_at, w.suppress_alerts,
                   w.created_by_user_id, u.full_name AS created_by_full_name,
                   w.source_tool, w.external_id, w.created_at,
                   (now() BETWEEN w.starts_at AND w.ends_at) AS is_active
            FROM ops_maintenance_window w
            LEFT JOIN dim_node     n ON n.id = w.node_id
            LEFT JOIN dim_locality l ON l.id = w.locality_id
            LEFT JOIN dim_user     u ON u.id = w.created_by_user_id
            WHERE {where}
            ORDER BY w.starts_at DESC
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def list_windows(db: Session, only_active: bool = False, limit: int = 100) -> list[dict]:
    where = "TRUE"
    params: dict = {}
    if only_active:
        where = "now() BETWEEN w.starts_at AND w.ends_at"
    windows = _serialize(db, where, params)
    return windows[:limit]


def create_window(
    db: Session,
    user: User,
    *,
    node_id: int | None,
    locality_id: int | None,
    reason: str,
    starts_at: datetime,
    ends_at: datetime,
    suppress_alerts: bool = True,
) -> dict:
    if node_id is None and locality_id is None:
        raise HTTPException(
            status_code=422,
            detail="Préciser au moins un équipement ou un site.",
        )
    if ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="La fin doit être postérieure au début.")
    if node_id is not None and db.get(Node, node_id) is None:
        raise HTTPException(status_code=404, detail="Équipement introuvable.")

    window = MaintenanceWindow(
        node_id=node_id,
        locality_id=locality_id,
        reason=reason,
        starts_at=starts_at,
        ends_at=ends_at,
        suppress_alerts=suppress_alerts,
        created_by_user_id=user.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)

    # Une fenêtre nouvellement créée change rétroactivement les KPI :
    # les incidents qu'elle recouvre en sortent.
    kpi_service.invalidate_cache()
    return _serialize(db, "w.id = :id", {"id": window.id})[0]


def delete_window(db: Session, window_id: int) -> None:
    window = db.get(MaintenanceWindow, window_id)
    if window is None:
        raise HTTPException(status_code=404, detail="Fenêtre introuvable.")
    db.delete(window)
    db.commit()
    kpi_service.invalidate_cache()


def import_windows(db: Session, windows: list[dict]) -> dict:
    """Import en masse depuis l'ETL.

    Rapprochement de l'équipement par son nom : `dim_node` n'a pas de
    colonne `code`, et `dim_node_source_map.external_ref` n'est pas
    forcément l'identifiant que l'outil utilise pour ses maintenances.
    Un nom introuvable n'est pas une erreur bloquante — il est compté et
    renvoyé, pour qu'un import partiel reste exploitable.
    """
    created = updated = unknown = 0

    for item in windows:
        node = db.query(Node).filter(Node.name.ilike(item["node_code"])).first()
        if node is None:
            unknown += 1
            continue

        existing = (
            db.query(MaintenanceWindow)
            .filter(
                MaintenanceWindow.source_tool == item["source_tool"],
                MaintenanceWindow.external_id == item["external_id"],
            )
            .first()
        )
        now = datetime.now(UTC)
        starts_at = item.get("starts_at") or now
        ends_at = item.get("ends_at") or now

        if existing:
            existing.node_id = node.id
            existing.reason = item["reason"]
            existing.starts_at = starts_at
            existing.ends_at = ends_at
            updated += 1
        else:
            db.add(
                MaintenanceWindow(
                    node_id=node.id,
                    reason=item["reason"],
                    starts_at=starts_at,
                    ends_at=ends_at,
                    suppress_alerts=True,
                    source_tool=item["source_tool"],
                    external_id=item["external_id"],
                )
            )
            created += 1

    db.commit()
    kpi_service.invalidate_cache()
    return {
        "received": len(windows),
        "created": created,
        "updated": updated,
        "unknown_node": unknown,
    }
