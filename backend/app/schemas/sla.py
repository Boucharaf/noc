"""Schémas SLA."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import Period


class SLAIndicatorOut(BaseModel):
    metric: str
    value: float
    target: float
    unit: str
    status: str  # met | not_met


class SLASeverityOut(BaseModel):
    severity: str
    total_incidents: int
    resolved: int
    ttr_target_minutes: int
    tta_target_minutes: int
    avg_mttr_minutes: float | None = None
    avg_mtta_minutes: float | None = None
    ttr_compliance_pct: float | None = None
    tta_compliance_pct: float | None = None
    breached: int


class SLAResponse(BaseModel):
    period: Period
    indicators: list[SLAIndicatorOut]
    by_severity: list[SLASeverityOut]
    global_compliance_pct: float | None = None
    total_breached: int


class SLATargetOut(BaseModel):
    id: int
    severity: str
    ttr_target_minutes: int
    tta_target_minutes: int
    availability_target_pct: float


class SLATargetUpdate(BaseModel):
    ttr_target_minutes: int | None = None
    tta_target_minutes: int | None = None
    availability_target_pct: float | None = None
