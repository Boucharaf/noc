"""État des intégrations avec les 6 outils de supervision."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.interop import InteropStatusResponse
from app.services import interop_service

router = APIRouter(prefix="/api/interop", tags=["interopérabilité"])


@router.get("/status", response_model=InteropStatusResponse)
def get_status(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    now = datetime.now(UTC)
    return interop_service.get_interop_status(db, month or now.month, year or now.year)
