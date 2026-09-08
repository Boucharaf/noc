"""Mur d'alertes."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.alerts import AlertOut, AlertSummaryOut, RecentAlertOut
from app.services import alerts_service

router = APIRouter(
    prefix="/api/alerts",
    tags=["alertes"],
    dependencies=[Depends(read_rate_limit)],
)


@router.get("/open", response_model=list[AlertOut])
def get_open_alerts(
    limit: int = Query(20, ge=1, le=200),
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return alerts_service.get_open_alerts(db, limit, locality_id)


@router.get("/recent", response_model=list[RecentAlertOut])
def get_recent_alerts(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return alerts_service.get_recent_alerts(db, limit)


@router.get("/counts")
def get_counts(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return alerts_service.count_open_by_severity(db)


@router.get("/summary", response_model=AlertSummaryOut)
def get_summary(
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Le bandeau d'état affiché en permanence en haut du dashboard."""
    return alerts_service.get_summary(db, locality_id)
