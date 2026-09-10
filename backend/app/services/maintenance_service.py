"""
Fenêtres de maintenance planifiée.

CE QU'UNE FENÊTRE FAIT, ET NE FAIT PAS. Elle ne masque pas l'alerte : elle
la MARQUE. Un exploitant doit voir qu'un site est en coupure programmée —
sinon il croit à un trou de supervision et envoie quelqu'un sur place pour
rien. En revanche, une alerte marquée est exclue des indicateurs, parce
qu'une coupure voulue n'est pas une panne et que la compter fausserait à la
fois le volume d'incidents et le respect du SLA.

PORTÉE : un équipement OU un site. Le second cas est celui qui sert en
pratique — quand un groupe électrogène est coupé pour entretien, tous les
équipements du site tombent, et personne n'a le temps de déclarer trente
fenêtres à la main. La contrainte de schéma interdit une fenêtre sans
portée : elle s'appliquerait à tout le parc et éteindrait la supervision.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import MaintenanceWindow, User
from app.services import live_service

logger = logging.getLogger(__name__)


def _serialise(window: MaintenanceWindow, author: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": window.id,
        "node_key": window.node_key,
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
    site: str | None = None,
    suppress_alerts: bool = True,
) -> dict:
    if ends_at <= starts_at:
        raise HTTPException(400, "La fin de la fenêtre doit suivre son début.")
    if not node_key and not site:
        raise HTTPException(
            400,
            "Une fenêtre doit viser un équipement ou un site. Sans portée, "
            "elle couvrirait tout le parc et éteindrait la supervision.",
        )

    # L'équipement est vérifié contre l'instantané : déclarer une maintenance
    # sur un identifiant qui n'existe pas produirait une fenêtre qui ne
    # s'appliquerait jamais, sans que personne ne s'en aperçoive avant la
    # coupure.
    if node_key:
        node = await live_service.get_node(node_key)
        if node is None:
            raise HTTPException(
                404,
                f"Aucun équipement « {node_key} » dans l'instantané courant. "
                "Vérifier l'identifiant, ou viser le site plutôt que "
                "l'équipement.",
            )

    window = MaintenanceWindow(
        node_key=node_key,
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
        "Fenêtre de maintenance créée : %s du %s au %s",
        node_key or f"site {site}",
        starts_at.isoformat(),
        ends_at.isoformat(),
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
    """Fenêtre couvrant un équipement, s'il y en a une.

    Fonction partagée par alerts_service et node_service : la règle « une
    fenêtre couvre par équipement OU par site » ne doit exister qu'à un seul
    endroit, sinon les deux écrans finiront par ne plus s'accorder sur ce
    qui est en maintenance.
    """
    for window in windows:
        if window.node_key and window.node_key == node_key:
            return window
        if window.site and site and window.site == site:
            return window
    return None
