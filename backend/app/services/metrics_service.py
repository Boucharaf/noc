"""Ingestion bulk + lectures KPI pour fact_metric.

Suit le même patron que incident_service.ingest_incidents_bulk : une
résolution de node_code -> node_id par lot, une insertion en masse, un seul
commit. La déduplication ne se fait pas en Python (contrairement aux
incidents) : l'index unique idx_metric_dedup côté base
(node_id, metric_type, source_tool, collected_at) s'en charge via
ON CONFLICT DO NOTHING — plus simple ici parce qu'une métrique n'a pas
d'état "ouvert/résolu" à faire évoluer, juste une lecture qui existe ou pas.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.dimension import Node
from app.models.metric import Metric
from app.schemas.metrics import MetricIngestPayload

logger = logging.getLogger(__name__)

# Une lecture "availability" plus vieille que ça n'est plus considérée comme
# représentative de l'état actuel d'un nœud — au-delà, mieux vaut afficher
# "inconnu" que le dernier statut connu il y a des heures.
_STALE_AFTER = timedelta(minutes=30)


def ingest_metrics_bulk(db: Session, payloads: list[MetricIngestPayload]) -> dict[str, int]:
    if not payloads:
        return {"received": 0, "created": 0, "duplicates": 0, "unknown_node": 0}

    node_ids = {
        code: nid
        for code, nid in db.query(Node.code, Node.id).filter(
            Node.code.in_({p.node_code for p in payloads})
        )
    }

    rows = []
    unknown_node = 0
    for p in payloads:
        node_id = node_ids.get(p.node_code)
        if node_id is None:
            unknown_node += 1
            continue
        rows.append(
            {
                "node_id": node_id,
                "source_tool": p.source_tool,
                "metric_type": p.metric_type,
                "value": p.value,
                "unit": p.unit,
                "collected_at": p.collected_at.astimezone(timezone.utc).replace(tzinfo=None)
                if p.collected_at.tzinfo
                else p.collected_at,
            }
        )

    created = 0
    if rows:
        stmt = pg_insert(Metric).values(rows).on_conflict_do_nothing(
            index_elements=["node_id", "metric_type", "source_tool", "collected_at"]
        )
        result = db.execute(stmt)
        db.commit()
        created = result.rowcount or 0

    return {
        "received": len(payloads),
        "created": created,
        "duplicates": len(rows) - created,
        "unknown_node": unknown_node,
    }


def get_network_kpi(db: Session, since: datetime | None = None) -> dict:
    """Disponibilité, perte de paquets, latence moyenne, utilisation de bande
    passante — agrégés sur `since` (défaut : dernière heure), et compte des
    équipements actuellement DOWN (dernière lecture "availability" = 0, pas
    plus vieille que _STALE_AFTER).
    """
    since = since or (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)

    def _avg(metric_type: str) -> float | None:
        value = db.execute(
            select(func.avg(Metric.value)).where(
                Metric.metric_type == metric_type, Metric.collected_at >= since
            )
        ).scalar()
        return float(value) if value is not None else None

    availability_pct = _avg("availability")
    if availability_pct is not None:
        availability_pct = round(availability_pct * 100, 1)

    avg_bandwidth_in = _avg("bandwidth_in_bps")
    avg_bandwidth_out = _avg("bandwidth_out_bps")
    avg_bandwidth = None
    if avg_bandwidth_in is not None or avg_bandwidth_out is not None:
        avg_bandwidth = max(v for v in (avg_bandwidth_in, avg_bandwidth_out) if v is not None)

    cutoff = (datetime.now(timezone.utc) - _STALE_AFTER).replace(tzinfo=None)
    latest_availability = text(
        """
        SELECT DISTINCT ON (node_id) node_id, value
        FROM fact_metric
        WHERE metric_type = 'availability' AND collected_at >= :cutoff
        ORDER BY node_id, collected_at DESC
        """
    )
    latest_rows = db.execute(latest_availability, {"cutoff": cutoff}).all()
    nodes_down = sum(1 for _, value in latest_rows if value == 0)

    return {
        "availability_pct": availability_pct,
        "packet_loss_pct": _avg("packet_loss_pct"),
        "avg_latency_ms": _avg("latency_ms"),
        "avg_bandwidth_utilization_pct": avg_bandwidth,
        "nodes_down": nodes_down,
        "nodes_reporting": len(latest_rows),
    }


def list_nodes_down(db: Session) -> list[dict]:
    """Nœuds dont la dernière lecture 'availability' connue (pas plus vieille
    que _STALE_AFTER) vaut 0 — la liste derrière le compteur de
    get_network_kpi()."""
    cutoff = (datetime.now(timezone.utc) - _STALE_AFTER).replace(tzinfo=None)
    rows = db.execute(
        text(
            """
            SELECT node_id, source_tool, collected_at, code, name, locality_id, locality_name
            FROM (
                SELECT DISTINCT ON (m.node_id)
                    m.node_id, m.source_tool, m.collected_at, m.value,
                    n.code, n.name, n.locality_id, l.name AS locality_name
                FROM fact_metric m
                JOIN dim_node n ON n.id = m.node_id
                JOIN dim_locality l ON l.id = n.locality_id
                WHERE m.metric_type = 'availability' AND m.collected_at >= :cutoff
                ORDER BY m.node_id, m.collected_at DESC
            ) latest
            WHERE value = 0
            """
        ),
        {"cutoff": cutoff},
    ).all()
    return [
        {
            "node_id": r.node_id,
            "node_code": r.code,
            "node_name": r.name,
            "locality_id": r.locality_id,
            "locality": r.locality_name,
            "source_tool": r.source_tool,
            "since": r.collected_at,
        }
        for r in rows
    ]
