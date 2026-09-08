"""
Couverture de supervision.

Le préfixe reste `/api/assets` pour ne pas casser
frontend/src/api/assets.js, alors que la table `dim_asset` n'existe plus :
la donnée vient maintenant de fact_supervision_coverage_daily, calculée
par l'ETL.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.coverage import CoverageSummaryOut, CoverageTrendPoint
from app.services import coverage_service

router = APIRouter(
    prefix="/api/assets",
    tags=["couverture"],
    dependencies=[Depends(read_rate_limit)],
)


@router.get("/coverage", response_model=CoverageSummaryOut)
def get_coverage(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return coverage_service.get_coverage(db)


@router.get("/coverage/trend", response_model=list[CoverageTrendPoint])
def get_coverage_trend(
    days: int = Query(30, ge=1, le=400),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return coverage_service.get_coverage_trend(db, days)
