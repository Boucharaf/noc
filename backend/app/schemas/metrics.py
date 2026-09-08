"""
Schémas des métriques.

Il n'y a PLUS de schéma d'ingestion : le nouvel ETL écrit directement
dans la hypertable `metric_value`, le backend ne fait que lire.
`METRIC_TYPE_PATTERN` reprend exactement la liste de
etl/transform/normalize_metrics.py.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

METRIC_TYPE_PATTERN = (
    "^(latency_ms|packet_loss_pct|bandwidth_in_mbps|bandwidth_out_mbps|"
    "cpu_pct|ram_pct|availability_pct)$"
)


class NetworkKpiOut(BaseModel):
    window_hours: int
    availability_pct: float | None = None
    packet_loss_pct: float | None = None
    avg_latency_ms: float | None = None
    avg_cpu_pct: float | None = None
    avg_ram_pct: float | None = None
    avg_bandwidth_in_mbps: float | None = None
    avg_bandwidth_out_mbps: float | None = None
    nodes_reporting: int
    nodes_down: int
    metric_types_available: list[str] = []


class NodeDownOut(BaseModel):
    node_id: int
    node_code: str
    node_name: str
    locality_id: int | None = None
    locality: str
    source_tool: str
    since: datetime | None = None


class MetricPointOut(BaseModel):
    time: datetime
    value: float | None = None
    min: float | None = None
    max: float | None = None


class NetworkSeriesPointOut(MetricPointOut):
    """Point d'une courbe agrégée sur plusieurs équipements.

    `nb_nodes` n'est pas décoratif : une moyenne calculée sur 3 nœuds au
    lieu de 300 ne veut pas dire la même chose, et c'est le seul moyen de
    voir qu'un connecteur a cessé de remonter au milieu de la fenêtre.
    """

    nb_nodes: int = 0


class TopNodeMetricOut(BaseModel):
    node_id: int
    node_code: str
    node_name: str
    locality: str
    locality_id: int | None = None
    metric_type: str
    avg_value: float
    max_value: float
    nb_points: int
