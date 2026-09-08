"""
Schémas de l'inventaire des équipements.

`state` reprend le vocabulaire dérivé par services/node_service.py — il
n'existe dans aucune table : l'ETL ne publie pas d'état up/down.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

NODE_STATE_PATTERN = "^(down|degraded|silent|maintenance|up|inactive)$"
NODE_SORT_PATTERN = (
    "^(state|name|locality|open_incidents|incidents_30d|availability|last_incident)$"
)


class NodeSourceRef(BaseModel):
    source_tool: str
    external_ref: str


class NodeOut(BaseModel):
    node_id: int
    code: str
    name: str
    ip_address: str | None = None
    node_type: str | None = None
    is_active: bool = True
    state: str

    locality_id: int | None = None
    locality: str | None = None
    region_id: int | None = None
    region: str | None = None
    ministry_id: int | None = None
    ministry: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    source_tools: list[str] = []
    nb_source_tools: int = 0
    source_tool: str | None = None

    last_metric_at: datetime | None = None
    availability_pct: float | None = None
    latency_ms: float | None = None
    packet_loss_pct: float | None = None
    cpu_pct: float | None = None
    ram_pct: float | None = None
    bandwidth_in_mbps: float | None = None
    bandwidth_out_mbps: float | None = None

    open_incidents: int = 0
    critical_incidents: int = 0
    incidents_30d: int = 0
    last_incident_at: datetime | None = None
    down_since: datetime | None = None
    maintenance_until: datetime | None = None


class NodeListResponse(BaseModel):
    items: list[NodeOut]
    total: int
    page: int
    page_size: int
    pages: int


class NodeDetailOut(NodeOut):
    source_refs: list[NodeSourceRef] = []
    metric_types: list[str] = []
    incidents_90d: int = 0
    avg_mttr_minutes: float | None = None
    downtime_30d_minutes: float | None = None


class NodeIncidentOut(BaseModel):
    id: int
    severity: str
    status: str
    description: str | None = None
    cause_category: str | None = None
    cause_label: str | None = None
    source_tool: str
    detected_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    mttr_minutes: float | None = None
    is_maintenance: bool = False
    age_minutes: int | None = None


class NodeStateCounts(BaseModel):
    down: int = 0
    degraded: int = 0
    silent: int = 0
    maintenance: int = 0
    up: int = 0
    inactive: int = 0
    total: int = 0
