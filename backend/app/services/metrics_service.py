"""
Métriques réseau, lues depuis l'entrepôt TimescaleDB.

Deux sources, choisies selon la fenêtre demandée :

* `metric_value` — données brutes, une ligne par relevé. Précise mais
  volumineuse ; l'ETL y écrit à chaque cycle pour tout le parc.
* `metric_hourly` — agrégat continu horaire maintenu par TimescaleDB
  (etl/sql/schema_timescale.sql). Beaucoup moins de lignes à balayer.

Au-delà de 48 heures on bascule sur l'agrégat : sur 6 mois, `metric_value`
représenterait des dizaines de millions de lignes, alors que la courbe
affichée n'a de toute façon pas une résolution supérieure à l'heure.
L'agrégat accuse jusqu'à une heure de retard (`end_offset => 1 hour` dans
la politique de rafraîchissement), ce qui est sans importance pour une
tendance longue mais interdirait de l'utiliser pour du temps réel.

Le seuil `availability_pct` sert aussi à déterminer les équipements
« tombés » : l'ETL ne publie pas d'état up/down explicite, seulement des
métriques et des incidents.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import METRIC_TYPES

logger = logging.getLogger(__name__)

# Au-delà de cette fenêtre, lecture sur l'agrégat horaire.
RAW_WINDOW_HOURS = 48


def _bounds(hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    return end - timedelta(hours=max(1, hours)), end


def get_network_kpi(db: Session, hours: int = 24, locality_id: int | None = None) -> dict:
    """Moyennes réseau sur la fenêtre glissante."""
    start, end = _bounds(hours)

    rows = db.execute(
        text(
            """
            SELECT m.metric_type,
                   avg(m.value) AS avg_value,
                   min(m.value) AS min_value,
                   max(m.value) AS max_value,
                   count(DISTINCT m.node_id) AS nb_nodes
            FROM metric_value m
            LEFT JOIN dim_node n ON n.id = m.node_id
            WHERE m.time >= :start AND m.time < :end
              AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
            GROUP BY m.metric_type
            """
        ),
        {"start": start, "end": end, "locality_id": locality_id},
    ).mappings().all()

    by_type = {r["metric_type"]: r for r in rows}

    def _avg(metric_type: str) -> float | None:
        row = by_type.get(metric_type)
        return round(float(row["avg_value"]), 2) if row and row["avg_value"] is not None else None

    nodes_reporting = db.execute(
        text(
            """
            SELECT count(DISTINCT m.node_id)
            FROM metric_value m
            LEFT JOIN dim_node n ON n.id = m.node_id
            WHERE m.time >= :start AND m.time < :end
              AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
            """
        ),
        {"start": start, "end": end, "locality_id": locality_id},
    ).scalar() or 0

    bandwidth_in = _avg("bandwidth_in_mbps")
    bandwidth_out = _avg("bandwidth_out_mbps")

    return {
        "window_hours": hours,
        "availability_pct": _avg("availability_pct"),
        "packet_loss_pct": _avg("packet_loss_pct"),
        "avg_latency_ms": _avg("latency_ms"),
        "avg_cpu_pct": _avg("cpu_pct"),
        "avg_ram_pct": _avg("ram_pct"),
        "avg_bandwidth_in_mbps": bandwidth_in,
        "avg_bandwidth_out_mbps": bandwidth_out,
        "nodes_reporting": int(nodes_reporting),
        "nodes_down": len(get_nodes_down(db, locality_id=locality_id)),
        "metric_types_available": sorted(by_type.keys()),
    }


def get_nodes_down(db: Session, locality_id: int | None = None) -> list[dict]:
    """Équipements considérés hors service.

    L'ETL ne publie pas d'état up/down : un équipement est déclaré tombé
    s'il porte un incident critique encore ouvert, OU si sa dernière
    mesure de disponibilité est nulle. Les deux conditions sont réunies
    ici parce qu'aucune n'est suffisante seule — tous les outils ne
    remontent pas de métrique `availability_pct`, et un équipement peut
    être injoignable sans qu'un incident ait encore été corrélé.
    """
    rows = db.execute(
        text(
            """
            WITH last_availability AS (
                SELECT DISTINCT ON (m.node_id)
                       m.node_id, m.value, m.time
                FROM metric_value m
                WHERE m.metric_type = 'availability_pct'
                  AND m.time > now() - INTERVAL '1 hour'
                ORDER BY m.node_id, m.time DESC
            ),
            critical_open AS (
                SELECT i.node_id, min(i.detected_at) AS since
                FROM v_incident i
                WHERE i.status IN ('open','acknowledged')
                  AND i.severity IN ('critical','high')
                  AND NOT i.is_maintenance
                  AND i.cause_category IN ('equipement_down','lien_down','alimentation')
                GROUP BY i.node_id
            )
            SELECT
                n.node_id,
                n.code       AS node_code,
                n.name       AS node_name,
                n.locality_id,
                COALESCE(n.locality, '—') AS locality,
                COALESCE(n.source_tool, '—') AS source_tool,
                COALESCE(co.since, la.time) AS since
            FROM v_node n
            LEFT JOIN last_availability la ON la.node_id = n.node_id
            LEFT JOIN critical_open     co ON co.node_id = n.node_id
            WHERE n.is_active
              AND (co.node_id IS NOT NULL OR la.value = 0)
              AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
            ORDER BY since ASC NULLS LAST
            """
        ),
        {"locality_id": locality_id},
    ).mappings().all()

    return [dict(r) for r in rows]


def get_node_series(
    db: Session, node_id: int, metric_type: str, hours: int = 24
) -> list[dict]:
    """Série temporelle d'une métrique pour un équipement."""
    if metric_type not in METRIC_TYPES:
        return []

    start, end = _bounds(hours)

    if hours <= RAW_WINDOW_HOURS:
        rows = db.execute(
            text(
                """
                SELECT m.time AS bucket, m.value AS avg_value,
                       m.value AS min_value, m.value AS max_value
                FROM metric_value m
                WHERE m.node_id = :node_id AND m.metric_type = :metric_type
                  AND m.time >= :start AND m.time < :end
                ORDER BY m.time
                """
            ),
            {"node_id": node_id, "metric_type": metric_type, "start": start, "end": end},
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                """
                SELECT h.bucket, h.avg_value, h.min_value, h.max_value
                FROM metric_hourly h
                WHERE h.node_id = :node_id AND h.metric_type = :metric_type
                  AND h.bucket >= :start AND h.bucket < :end
                ORDER BY h.bucket
                """
            ),
            {"node_id": node_id, "metric_type": metric_type, "start": start, "end": end},
        ).mappings().all()

    return [
        {
            "time": r["bucket"],
            "value": round(float(r["avg_value"]), 3) if r["avg_value"] is not None else None,
            "min": round(float(r["min_value"]), 3) if r["min_value"] is not None else None,
            "max": round(float(r["max_value"]), 3) if r["max_value"] is not None else None,
        }
        for r in rows
    ]


def get_node_latest(db: Session, node_id: int) -> dict[str, dict]:
    """Dernière valeur connue de chaque métrique d'un équipement."""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (m.metric_type)
                   m.metric_type, m.value, m.time, m.source_tool
            FROM metric_value m
            WHERE m.node_id = :node_id
              AND m.time > now() - INTERVAL '24 hours'
            ORDER BY m.metric_type, m.time DESC
            """
        ),
        {"node_id": node_id},
    ).mappings().all()

    return {
        r["metric_type"]: {
            "value": round(float(r["value"]), 3),
            "time": r["time"],
            "source_tool": r["source_tool"],
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# Vues réseau agrégées — ce que regarde un exploitant sur le mur d'écrans
# ---------------------------------------------------------------------------
def get_network_series(
    db: Session,
    metric_type: str,
    hours: int = 24,
    locality_id: int | None = None,
    ministry_id: int | None = None,
) -> list[dict]:
    """Courbe d'une métrique agrégée sur TOUT le parc (ou un périmètre).

    `get_node_series` répond « comment va cet équipement » ; celle-ci
    répond « comment va le réseau », qui est la première question posée
    devant un mur d'écrans. Sans elle, le frontend devrait appeler la
    série de chaque nœud puis moyenner côté navigateur — soit des
    centaines de requêtes pour une seule courbe.

    Le bucket suit la fenêtre : 5 minutes sur 24 h (résolution de la
    collecte), 1 heure au-delà, en lisant l'agrégat continu quand la
    fenêtre dépasse RAW_WINDOW_HOURS.
    """
    if metric_type not in METRIC_TYPES:
        return []

    start, end = _bounds(hours)
    geo_filter = """
        AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
        AND (CAST(:ministry_id AS INT) IS NULL OR n.ministry_id = :ministry_id)
    """
    params = {
        "start": start,
        "end": end,
        "metric_type": metric_type,
        "locality_id": locality_id,
        "ministry_id": ministry_id,
    }

    if hours <= RAW_WINDOW_HOURS:
        bucket = "5 minutes" if hours <= 24 else "15 minutes"
        rows = db.execute(
            text(
                f"""
                SELECT time_bucket(INTERVAL '{bucket}', m.time) AS bucket,
                       avg(m.value) AS avg_value,
                       min(m.value) AS min_value,
                       max(m.value) AS max_value,
                       count(DISTINCT m.node_id) AS nb_nodes
                FROM metric_value m
                JOIN dim_node n ON n.id = m.node_id
                WHERE m.metric_type = :metric_type
                  AND m.time >= :start AND m.time < :end
                  {geo_filter}
                GROUP BY bucket
                ORDER BY bucket
                """
            ),
            params,
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                f"""
                SELECT h.bucket,
                       avg(h.avg_value) AS avg_value,
                       min(h.min_value) AS min_value,
                       max(h.max_value) AS max_value,
                       count(DISTINCT h.node_id) AS nb_nodes
                FROM metric_hourly h
                JOIN dim_node n ON n.id = h.node_id
                WHERE h.metric_type = :metric_type
                  AND h.bucket >= :start AND h.bucket < :end
                  {geo_filter}
                GROUP BY h.bucket
                ORDER BY h.bucket
                """
            ),
            params,
        ).mappings().all()

    def _round(value) -> float | None:
        return round(float(value), 3) if value is not None else None

    return [
        {
            "time": r["bucket"],
            "value": _round(r["avg_value"]),
            "min": _round(r["min_value"]),
            "max": _round(r["max_value"]),
            "nb_nodes": int(r["nb_nodes"] or 0),
        }
        for r in rows
    ]


# Sens de lecture de chaque métrique : pour la latence, « pire » veut
# dire « plus haut » ; pour la disponibilité, « plus bas ». Le classement
# doit suivre la sémantique, pas un ORDER BY DESC uniforme.
_WORST_IS_HIGH = {
    "latency_ms",
    "packet_loss_pct",
    "cpu_pct",
    "ram_pct",
    "bandwidth_in_mbps",
    "bandwidth_out_mbps",
}


def get_top_nodes(
    db: Session,
    metric_type: str,
    hours: int = 24,
    limit: int = 10,
    locality_id: int | None = None,
) -> list[dict]:
    """Classement des équipements sur une métrique (top talkers, pires latences…).

    Répond au KPI métier « Top 10 des sites ou équipements les plus
    incidentés », côté performance plutôt que côté incidents.
    """
    if metric_type not in METRIC_TYPES:
        return []

    start, end = _bounds(hours)
    direction = "DESC" if metric_type in _WORST_IS_HIGH else "ASC"

    rows = db.execute(
        text(
            f"""
            SELECT n.node_id, n.code AS node_code, n.name AS node_name,
                   COALESCE(n.locality, '—') AS locality, n.locality_id,
                   avg(m.value) AS avg_value,
                   max(m.value) AS max_value,
                   count(*)     AS nb_points
            FROM metric_value m
            JOIN v_node n ON n.node_id = m.node_id
            WHERE m.metric_type = :metric_type
              AND m.time >= :start AND m.time < :end
              AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
            GROUP BY n.node_id, n.code, n.name, n.locality, n.locality_id
            ORDER BY avg(m.value) {direction}
            LIMIT :limit
            """
        ),
        {
            "metric_type": metric_type,
            "start": start,
            "end": end,
            "locality_id": locality_id,
            "limit": max(1, min(50, limit)),
        },
    ).mappings().all()

    return [
        {
            "node_id": r["node_id"],
            "node_code": r["node_code"],
            "node_name": r["node_name"],
            "locality": r["locality"],
            "locality_id": r["locality_id"],
            "metric_type": metric_type,
            "avg_value": round(float(r["avg_value"]), 3),
            "max_value": round(float(r["max_value"]), 3),
            "nb_points": int(r["nb_points"]),
        }
        for r in rows
    ]
