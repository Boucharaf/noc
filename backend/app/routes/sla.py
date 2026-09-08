"""Engagements de service."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.operations import User
from app.schemas.sla import SLAResponse, SLATargetOut, SLATargetUpdate
from app.services import sla_service

router = APIRouter(prefix="/api/sla", tags=["sla"], dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=SLAResponse)
def get_sla(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    now = datetime.now(UTC)
    return sla_service.get_sla(db, month or now.month, year or now.year)


@router.get("/targets", response_model=list[SLATargetOut])
def list_targets(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return sla_service.list_targets(db)


@router.patch("/targets/{severity}", response_model=SLATargetOut)
def update_target(
    severity: str,
    payload: SLATargetUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("directeur", "chef_noc")),
):
    return sla_service.update_target(
        db,
        severity,
        ttr_target_minutes=payload.ttr_target_minutes,
        tta_target_minutes=payload.tta_target_minutes,
        availability_target_pct=payload.availability_target_pct,
    )
