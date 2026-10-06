"""
Fenêtres de maintenance planifiée.

CE QU'UNE FENÊTRE FAIT, ET NE FAIT PAS. Elle ne masque pas l'alerte : elle
la MARQUE. Un exploitant doit voir qu'un site est en coupure programmée —
sinon il croit à un trou de supervision et envoie quelqu'un sur place pour
rien. En revanche, une alerte marquée est exclue des indicateurs, parce
qu'une coupure voulue n'est pas une panne et que la compter fausserait à la
fois le volume d'incidents et le respect du SLA.

PORTÉE : un site est toujours requis. La fenêtre peut viser tous ses
équipements ou une sélection de plusieurs équipements de ce site. Un
équipement ne peut pas être sélectionné sans site.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaintenanceWindow, User
from app.services import live_service

logger = logging.getLogger(__name__)


def _serialise(window: MaintenanceWindow, author: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": window.id,
        "node_key": window.node_key,
        "node_keys": window.node_keys or [],
        "site": window.site,
        "reason": window.reason,
        "starts_at": window.starts_at.isoformat(),
        "ends_at": window.ends_at.isoformat(),
        "suppress_alerts": window.suppress_alerts,
        "created_by": author,
        "created_at": window.created_at.isoformat() if window.created_at else None,
        # Calculé ici plutôt qu'au frontend : trois clients qui déduisent
        # chacun « est-elle active ? » de deux dates finiraient par diverger
        # sur les fuseaux.
        "active": window.starts_at <= now <= window.ends_at,
        "upcoming": window.starts_at > now,
    }


def _author_names(db: Session, windows: list[MaintenanceWindow]) -> dict[int, str]:
    ids = {w.created_by for w in windows if w.created_by}
    if not ids:
        return {}
    rows = db.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(ids))
    )
    return {row.id: row.full_name or row.username for row in rows}


def list_windows(
    db: Session, scope: str = "all", limit: int = 200
) -> list[dict]:
    """Fenêtres, filtrées par leur position dans le temps.

    `scope` vaut `active`, `upcoming`, `past` ou `all`. Le filtrage est fait
    en SQL et non en Python : sur un parc qui accumule des années de
    fenêtres, tout charger pour n'en garder que trois serait absurde.
    """
    now = datetime.now(timezone.utc)
    query = select(MaintenanceWindow)

    if scope == "active":
        query = query.where(
            MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at >= now
        )
    elif scope == "upcoming":
        query = query.where(MaintenanceWindow.starts_at > now)
    elif scope == "past":
        query = query.where(MaintenanceWindow.ends_at < now)

    windows = list(
        db.execute(
            query.order_by(MaintenanceWindow.starts_at.desc()).limit(limit)
        ).scalars()
    )
    authors = _author_names(db, windows)
    return [_serialise(w, authors.get(w.created_by)) for w in windows]


async def create_window(
    db: Session,
    user_id: int,
    reason: str,
    starts_at: datetime,
    ends_at: datetime,
    node_key: str | None = None,
    node_keys: list[str] | None = None,
    site: str | None = None,
    suppress_alerts: bool = True,
) -> dict:
    if ends_at <= starts_at:
        raise HTTPException(400, "La fin de la fenêtre doit suivre son début.")
    if not site:
        raise HTTPException(
            400, "Sélectionnez un site avant de planifier la maintenance."
        )

    selected_node_keys = list(dict.fromkeys(node_keys or []))
    if node_key:
        selected_node_keys.append(node_key)
        selected_node_keys = list(dict.fromkeys(selected_node_keys))

    if selected_node_keys:
        # Un équipement est validé dans le snapshot et doit appartenir au
        # site choisi. Une sélection vide avec un site signifie site entier.
        snapshot_nodes = await live_service.get_nodes()
        nodes_by_id = {node.get("id"): node for node in snapshot_nodes}
        for selected_key in selected_node_keys:
            node = nodes_by_id.get(selected_key)
            if node is None:
                raise HTTPException(
                    404,
                    f"Aucun équipement « {selected_key} » dans l'instantané courant.",
                )
            if node.get("site") != site:
                raise HTTPException(
                    400,
                    f"L'équipement « {node.get('name') or selected_key} » "
                    f"n'appartient pas au site « {site} ».",
                )
    elif not any(node.get("site") == site for node in await live_service.get_nodes()):
        raise HTTPException(404, f"Le site « {site} » est absent de l'inventaire courant.")

    if node_key and len(selected_node_keys) == 1:
        # Keep the legacy single-target column populated for existing readers.
        stored_node_key = node_key
        stored_node_keys = None
    elif selected_node_keys:
        stored_node_key = None
        stored_node_keys = selected_node_keys
    else:
        stored_node_key = None
        stored_node_keys = None

    window = MaintenanceWindow(
        node_key=stored_node_key,
        node_keys=stored_node_keys,
        site=site,
        reason=reason,
        starts_at=starts_at,
        ends_at=ends_at,
        suppress_alerts=suppress_alerts,
        created_by=user_id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)

    logger.info(
        "Fenêtre de maintenance créée : %s",
        f"{len(selected_node_keys)} équipement(s) du site {site}"
        if selected_node_keys
        else f"site {site}",
    )
    return _serialise(window)


def delete_window(db: Session, window_id: int) -> None:
    window = db.get(MaintenanceWindow, window_id)
    if window is None:
        raise HTTPException(404, "Fenêtre de maintenance introuvable.")
    db.delete(window)
    db.commit()


def active_at(db: Session, at: datetime | None = None) -> list[MaintenanceWindow]:
    """Fenêtres actives à un instant donné, pour les autres services."""
    moment = at or datetime.now(timezone.utc)
    return list(
        db.execute(
            select(MaintenanceWindow).where(
                MaintenanceWindow.starts_at <= moment,
                MaintenanceWindow.ends_at >= moment,
            )
        ).scalars()
    )


def covers(
    windows: list[MaintenanceWindow], node_key: str | None, site: str | None
) -> MaintenanceWindow | None:
    """Fenêtre couvrant un équipement, s'il y en a une."""
    for window in windows:
        if window.node_keys:
            if node_key and node_key in window.node_keys:
                return window
            continue
        if window.node_key:
            if window.node_key == node_key:
                return window
            continue
        if window.site and site and window.site == site:
            return window
    return None
