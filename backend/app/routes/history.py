"""
Historique de disponibilité — lecture du journal (collector/history.py).

Lecture seule, base du NOC uniquement : aucun appel vers les outils. Si le
journal n'existe pas encore (schéma non rejoué) ou si la base ne répond pas,
les routes répondent `{"available": false, "reason": …}` et les écrans
l'affichent, au lieu d'une erreur qui ferait échouer toute la page.
"""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import User
from app.services import availability_service

router = APIRouter(prefix="/api/history", tags=["historique"])

_Place = Query(None, max_length=200)


def _unavailable(exc: availability_service.HistoryUnavailable) -> dict:
    return {
        "available": False,
        "reason": (
            "Historique indisponible : journal absent (rejouer backend/sql/schema.sql) "
            "ou base du NOC injoignable."
        ),
    }


@router.get("/status")
def history_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return availability_service.status(db)
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)


@router.get("/ranking")
def history_ranking(
    kind: str = Query("node", pattern="^(node|link)$"),
    days: int = Query(30, ge=1, le=730),
    limit: int = Query(20, ge=1, le=200),
    region: str | None = _Place,
    province: str | None = _Place,
    site: str | None = _Place,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Équipements ou liens les moins disponibles sur la période."""
    try:
        return availability_service.ranking(db, kind, days, limit, region, province, site)
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)


@router.get("/nodes/{node_id:path}")
def history_node(
    node_id: str = Path(min_length=1, max_length=300),
    days: int = Query(30, ge=1, le=730),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disponibilité, pannes, liens et alertes d'un équipement sur la période."""
    try:
        return availability_service.node_history(db, node_id, days)
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)
