"""Agrégats KPI du dashboard."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.kpi import (
    CauseOut,
    HourDistributionOut,
    KPISummaryResponse,
    LocalityKPIOut,
    LocalityMapOut,
    LocalityNodesResponse,
    MinistryKPIOut,
    NodeKPIOut,
    RecurrentNodeOut,
    TrendPointOut,
)
from app.services import kpi_service

router = APIRouter(
    prefix="/api/kpi",
    tags=["kpi"],
    dependencies=[Depends(read_rate_limit)],
)

# Router séparé : le frontend appelle /api/locality/{id}/nodes, hors du
# préfixe /api/kpi (voir frontend/src/api/kpi.js::getLocalityNodes).
locality_router = APIRouter(
    prefix="/api/locality",
    tags=["kpi"],
    dependencies=[Depends(read_rate_limit)],
)


def _now() -> tuple[int, int]:
    now = datetime.now(UTC)
    return now.month, now.year


def _period(month: int | None, year: int | None) -> tuple[int, int]:
    default_month, default_year = _now()
    return month or default_month, year or default_year


@router.get("/summary", response_model=KPISummaryResponse)
def get_summary(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_summary(db, m, y)


@router.get("/localities", response_model=list[LocalityKPIOut])
def get_localities(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_localities(db, m, y, limit)


@router.get("/localities/map", response_model=list[LocalityMapOut])
def get_localities_map(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_localities_map(db, m, y)


@router.get("/nodes", response_model=list[NodeKPIOut])
def get_nodes(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    locality_id: int | None = None,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_nodes(db, m, y, locality_id, limit)


@router.get("/recurrent", response_model=list[RecurrentNodeOut])
def get_recurrent(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    min_count: int = Query(3, ge=2, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_recurrent(db, m, y, min_count)


@router.get("/trend", response_model=list[TrendPointOut])
def get_trend(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    months: int = Query(6, ge=2, le=24),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_trend(db, m, y, months)


@router.get("/hour-distribution", response_model=list[HourDistributionOut])
def get_hour_distribution(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_hour_distribution(db, m, y)


@router.get("/causes", response_model=list[CauseOut])
def get_causes(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_causes(db, m, y)


@router.get("/compare")
def get_compare(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    m, y = _period(month, year)
    return kpi_service.get_compare(db, m, y)


@router.get("/ministries", response_model=list[MinistryKPIOut])
def get_ministries(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Vue par ministère — dimension apportée par le nouvel ETL
    (dim_ministry), absente de l'ancien schéma."""
    m, y = _period(month, year)
    return kpi_service.get_ministries(db, m, y)


@locality_router.get("/{locality_id}/nodes", response_model=LocalityNodesResponse)
def get_locality_nodes(
    locality_id: int,
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from fastapi import HTTPException

    m, y = _period(month, year)
    result = kpi_service.get_locality_nodes(db, locality_id, m, y)
    if not result:
        raise HTTPException(status_code=404, detail="Site introuvable.")
    return result
