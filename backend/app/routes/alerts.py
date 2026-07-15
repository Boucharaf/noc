from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.services import alerts_service

router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)


@router.get("/open")
def open_alerts(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return alerts_service.get_open_alerts(db, limit)


@router.get("/recent")
def recent_notifications(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return alerts_service.get_recent_notifications(db, limit)
