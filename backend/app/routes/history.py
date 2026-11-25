"""
Historique de disponibilité — lecture du journal (collector/history.py).

Lecture seule, base du NOC uniquement : aucun appel vers les outils. Si le
journal n'existe pas encore (schéma non rejoué) ou si la base ne répond pas,
les routes répondent `{"available": false, "reason": …}` et les écrans
l'affichent, au lieu d'une erreur qui ferait échouer toute la page.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import User
from app.services import availability_service, kpi_service, live_service

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


@router.get("/tools")
def history_tools(
    days: int = Query(30, ge=1, le=730),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disponibilité des outils de supervision et leurs interruptions."""
    try:
        return availability_service.tools_health(db, days)
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)


@router.get("/ranking")
async def history_ranking(
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
        core_ids = await live_service.core_node_ids() if kind == "node" else None
        return await run_in_threadpool(
            availability_service.ranking, db, kind, days, limit, region, province, site, core_ids
        )
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)


@router.get("/month")
async def history_month(
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    region: str | None = _Place,
    province: str | None = _Place,
    site: str | None = _Place,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Le tableau de bord d'un mois : disponibilité, pannes et alertes de ce
    mois seulement, d'après le journal et les journaux des outils."""
    lo = datetime(year, month, 1, tzinfo=timezone.utc)
    hi = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    core_ids = await live_service.core_node_ids()

    def read():
        return {
            "available": True,
            "year": year,
            "month": month,
            "availability": availability_service.ranking(
                db, "node", 31, 20, region, province, site, core_ids, start=lo, end=hi
            ),
            "alerts": availability_service.month_alerts(db, lo, hi, region, province, site),
            "days": kpi_service.trend(
                db, site=kpi_service.rollup_key(region, province, site), start_at=lo, end_at=hi
            ),
        }

    try:
        return await run_in_threadpool(read)
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


@router.get("/flapping")
def history_flapping(
    hours: int = Query(1, ge=1, le=24),
    threshold: int = Query(availability_service.FLAPPING_CHANGES, ge=2, le=100),
    region: str | None = _Place,
    province: str | None = _Place,
    site: str | None = _Place,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Équipements qui changent d'état au moins `threshold` fois en `hours` h."""
    try:
        return availability_service.flapping(db, hours, threshold, region, province, site)
    except availability_service.HistoryUnavailable as exc:
        return _unavailable(exc)
