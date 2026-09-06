from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MetricIngestPayload(BaseModel):
    node_code: str
    source_tool: str = Field(..., pattern="^(zabbix|nagios|centreon|netxms|nsp|itop)$")
    metric_type: str = Field(
        ...,
        pattern="^(cpu_pct|ram_pct|bandwidth_in_bps|bandwidth_out_bps|"
        "latency_ms|packet_loss_pct|availability)$",
    )
    value: float
    unit: Optional[str] = None
    collected_at: datetime


class MetricBulkIngestPayload(BaseModel):
    # Un pass complet couvre potentiellement tout le parc (~1500+ nœuds) sur
    # plusieurs métriques chacun — même ordre de grandeur que le bulk incidents.
    metrics: list[MetricIngestPayload] = Field(..., max_length=20000)


class MetricBulkIngestResponse(BaseModel):
    received: int
    created: int
    duplicates: int
    unknown_node: int


class NetworkKpiOut(BaseModel):
    """KPI réseau agrégés sur une période : disponibilité, perte de paquets,
    latence moyenne, utilisation de bande passante — calculés depuis
    fact_metric, absents tant que cette table n'existait pas."""

    availability_pct: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    avg_bandwidth_utilization_pct: Optional[float] = None
    nodes_down: int
    nodes_reporting: int


class NodeDownOut(BaseModel):
    node_id: int
    node_code: str
    node_name: str
    locality_id: int
    locality: str
    source_tool: str
    since: Optional[datetime] = None
