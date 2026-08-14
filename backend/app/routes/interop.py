from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.services import interop_service

router = APIRouter(
    prefix="/api/interop",
    tags=["interop"],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)


@router.get("/status")
def interop_status(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(...),
    db: Session = Depends(get_db),
):
    """Live state of each supervision-tool integration.

    Deliberately not cached. The whole value of this endpoint is that it says
    what is true now — serving it from a five-minute cache would reintroduce
    exactly the lag that makes a status display untrustworthy.
    """
    return interop_service.get_interop_status(db, month, year)
