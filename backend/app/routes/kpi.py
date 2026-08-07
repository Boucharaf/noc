from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.services import cache_service, kpi_service

# All KPI reads require a logged-in user (any role, analyst included) and are
# rate-limited. Declaring both as router-level dependencies rather than
# per-endpoint is deliberate: a route added later inherits them automatically,
# so the failure mode is a new endpoint that is accidentally protected rather
# than one that is accidentally public.
router = APIRouter(
    prefix="/api/kpi",
    tags=["kpi"],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)


@router.get("/summary")
def kpi_summary(month: int = Query(..., ge=1, le=12), year: int = Query(...), db: Session = Depends(get_db)):
    cache_key = f"kpi:summary:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_summary(db, month, year)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/localities")
def kpi_localities(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cache_key = f"kpi:localities:{year}:{month}:{limit}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_localities(db, month, year, limit)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/localities/map")
def kpi_localities_map(month: int = Query(..., ge=1, le=12), year: int = Query(...), db: Session = Depends(get_db)):
    cache_key = f"kpi:localities-map:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_localities_map(db, month, year)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/nodes")
def kpi_nodes(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    locality_id: Optional[int] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cache_key = f"kpi:nodes:{year}:{month}:{locality_id}:{limit}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_nodes(db, month, year, locality_id, limit)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/recurrent")
def kpi_recurrent(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    min_count: int = Query(3, ge=1),
    db: Session = Depends(get_db),
):
    cache_key = f"kpi:recurrent:{year}:{month}:{min_count}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_recurrent_nodes(db, month, year, min_count)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/trend")
def kpi_trend(
    months: int = Query(6, ge=1, le=24),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    if year is None or month is None:
        latest_month, latest_year = kpi_service.get_latest_data_month(db)
        month = month or latest_month
        year = year or latest_year

    cache_key = f"kpi:trend:{year}:{month}:{months}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_trend(db, month, year, months)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/hour-distribution")
def kpi_hour_distribution(
    month: int = Query(..., ge=1, le=12), year: int = Query(...), db: Session = Depends(get_db)
):
    cache_key = f"kpi:hours:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_hour_distribution(db, month, year)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/compare")
def kpi_compare(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    cache_key = f"kpi:compare:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_comparison(db, month, year)
    cache_service.set_cached(cache_key, data)
    return data


@router.get("/causes")
def kpi_causes(month: int = Query(..., ge=1, le=12), year: int = Query(...), db: Session = Depends(get_db)):
    cache_key = f"kpi:causes:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_cause_breakdown(db, month, year)
    cache_service.set_cached(cache_key, data)
    return data


locality_router = APIRouter(
    prefix="/api/locality",
    tags=["kpi"],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)


@locality_router.get("/{locality_id}/nodes")
def locality_nodes(
    locality_id: int,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    cache_key = f"kpi:locality-nodes:{locality_id}:{year}:{month}"
    cached = cache_service.get_cached(cache_key)
    if cached is not None:
        return cached
    data = kpi_service.get_locality_nodes(db, locality_id, month, year)
    if data is None:
        raise HTTPException(status_code=404, detail="Locality not found")
    cache_service.set_cached(cache_key, data)
    return data
