"""Schémas des agrégats KPI."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import Period


class KPIValues(BaseModel):
    total_incidents: int
    resolved: int
    open: int
    critical: int
    resolution_rate_pct: float
    avg_mttr_minutes: float
    avg_mtta_minutes: float
    network_availability_pct: float
    critical_localities: int
    recurrent_nodes: int
    off_hours_detected: int


class KPIDelta(BaseModel):
    incidents_delta: int
    availability_delta: float


class KPISummaryResponse(BaseModel):
    period: Period
    kpi: KPIValues
    vs_previous_month: KPIDelta


class LocalityKPIOut(BaseModel):
    locality_id: int | None = None
    locality: str
    region: str
    total_incidents: int
    resolved: int
    critical: int
    avg_mttr: float | None = None
    availability_pct: float | None = None


class LocalityMapOut(LocalityKPIOut):
    latitude: float
    longitude: float
    nb_nodes: int


class NodeKPIOut(BaseModel):
    node_id: int | None = None
    code: str
    name: str
    locality: str
    source_tool: str | None = None
    total_incidents: int
    resolved: int
    avg_mttr: float | None = None


class RecurrentNodeOut(BaseModel):
    node_id: int | None = None
    code: str
    name: str
    locality: str
    total_incidents: int
    main_cause: str | None = None


class TrendPointOut(BaseModel):
    month: int
    year: int
    label: str
    total_incidents: int
    resolved: int
    avg_mttr: float | None = None
    availability_pct: float | None = None


class HourDistributionOut(BaseModel):
    hour: int
    total_incidents: int


class CauseOut(BaseModel):
    category: str
    label: str
    total_incidents: int
    share_pct: float
    avg_mttr: float | None = None


class MinistryKPIOut(BaseModel):
    ministry_id: int
    ministry: str
    nb_nodes: int
    total_incidents: int
    resolved: int
    critical: int
    avg_mttr: float | None = None


class NodeDetailOut(BaseModel):
    node_id: int
    code: str
    name: str
    node_type: str
    source_tool: str
    source_tools: list[str] = []
    is_active: bool
    total_incidents: int
    resolved: int
    open: int
    avg_mttr: float | None = None
    availability_pct: float | None = None


class LocalityNodesResponse(BaseModel):
    locality_id: int
    locality: str
    region: str
    period: Period
    nodes: list[NodeDetailOut]
