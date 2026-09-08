"""
Agrégats KPI du dashboard.

Tout est calculé à la demande en SQL sur la vue `v_incident`, avec un
cache Redis court (CACHE_TTL). L'ancienne vue matérialisée
`mv_kpi_node_monthly` et son rafraîchissement synchrone ont été
supprimés : l'ETL réécrit fact_incident toutes les 5 minutes, donc une
vue matérialisée aurait dû être rafraîchie à la même cadence, ce qui
coûte plus cher que de recalculer l'agrégat d'un mois sur une table
indexée. Le cache Redis joue le même rôle pour bien moins de complexité.

Toutes les requêtes lisent `v_incident` et jamais `fact_incident` :
c'est la vue qui traduit les sévérités et statuts propres à chaque outil
vers le vocabulaire unique du dashboard.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import NOC_BUSINESS_HOURS
from app.services import cache_service
from app.services.periods import (
    elapsed_minutes,
    month_bounds,
    period_payload,
    previous_month,
    shift_month,
)

logger = logging.getLogger(__name__)

CACHE_PREFIX = "noc:kpi:"

# Les incidents tombant dans une fenêtre de maintenance planifiée sont
# exclus de tous les KPI : ce sont des coupures voulues, les compter
# comme des pannes fausse à la fois le volume d'incidents et le SLA.
_NOT_MAINTENANCE = "AND NOT i.is_maintenance"


def _cache_key(name: str, *parts) -> str:
    return CACHE_PREFIX + name + ":" + ":".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Disponibilité
# ---------------------------------------------------------------------------
def _availability(db: Session, start, end, locality_id: int | None = None) -> float | None:
    """Disponibilité réseau sur la période, en pourcentage.

    Deux méthodes, dans cet ordre :

    1. Moyenne des métriques `availability_pct` remontées par les outils
       (etl/transform/normalize_metrics.py). C'est la mesure directe,
       préférée dès qu'elle existe.
    2. À défaut, déduction depuis les temps d'indisponibilité des
       incidents : 100 − (somme des downtime / (nb équipements × durée de
       la période)). Approximation, mais elle donne un chiffre plausible
       tant que les outils ne publient pas de métrique de disponibilité —
       ce qui est le cas si NAGIOS_MODE / NSP_FM_MODE ne sont pas encore
       arrêtés côté agence.
    """
    measured = db.execute(
        text(
            """
            SELECT avg(m.value)
            FROM metric_value m
            JOIN dim_node n ON n.id = m.node_id
            WHERE m.metric_type = 'availability_pct'
              AND m.time >= :start AND m.time < :end
              AND (CAST(:locality_id AS INT) IS NULL OR n.locality_id = :locality_id)
            """
        ),
        {"start": start, "end": end, "locality_id": locality_id},
    ).scalar()
    if measured is not None:
        return round(float(measured), 2)

    row = db.execute(
        text(
            """
            SELECT
                COALESCE(sum(i.downtime_minutes), 0) AS downtime,
                (SELECT count(*) FROM dim_node n
                  WHERE n.is_active
                    AND (CAST(:locality_id AS INT) IS NULL
                         OR n.locality_id = :locality_id)) AS nb_nodes
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              AND (CAST(:locality_id AS INT) IS NULL OR i.locality_id = :locality_id)
            """
            + _NOT_MAINTENANCE
        ),
        {"start": start, "end": end, "locality_id": locality_id},
    ).mappings().first()

    nb_nodes = int(row["nb_nodes"] or 0)
    if nb_nodes == 0:
        return None
    total_minutes = nb_nodes * max(1, int((end - start).total_seconds() // 60))
    availability = 100.0 - (float(row["downtime"]) / total_minutes * 100.0)
    return round(max(0.0, min(100.0, availability)), 2)


def _period_availability(db: Session, month: int, year: int, locality_id=None) -> float | None:
    start, end = month_bounds(month, year)
    # Pour le mois en cours, on ne divise que par le temps écoulé.
    minutes = elapsed_minutes(month, year)
    from datetime import timedelta

    horizon = min(end, start + timedelta(minutes=minutes))
    return _availability(db, start, horizon, locality_id)


# ---------------------------------------------------------------------------
# Synthèse
# ---------------------------------------------------------------------------
def get_summary(db: Session, month: int, year: int) -> dict:
    cached = cache_service.get_cached(_cache_key("summary", month, year))
    if cached:
        return cached

    start, end = month_bounds(month, year)
    hour_start, hour_end = NOC_BUSINESS_HOURS

    row = db.execute(
        text(
            f"""
            SELECT
                count(*)                                              AS total_incidents,
                count(*) FILTER (WHERE i.status IN ('resolved','closed'))
                    AS resolved,
                count(*) FILTER (WHERE i.status IN ('open','acknowledged'))
                    AS open,
                count(*) FILTER (WHERE i.severity = 'critical')       AS critical,
                avg(i.mttr_minutes) FILTER (WHERE i.mttr_minutes IS NOT NULL) AS avg_mttr,
                avg(i.mtta_minutes) FILTER (WHERE i.mtta_minutes IS NOT NULL) AS avg_mtta,
                count(*) FILTER (
                    WHERE i.detected_hour < :hour_start OR i.detected_hour > :hour_end
                )                                                     AS off_hours
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              {_NOT_MAINTENANCE}
            """
        ),
        {"start": start, "end": end, "hour_start": hour_start, "hour_end": hour_end},
    ).mappings().first()

    critical_localities = db.execute(
        text(
            f"""
            SELECT count(*) FROM (
                SELECT i.locality_id
                FROM v_incident i
                WHERE i.detected_at >= :start AND i.detected_at < :end
                  AND i.locality_id IS NOT NULL
                  {_NOT_MAINTENANCE}
                GROUP BY i.locality_id
                HAVING count(*) FILTER (WHERE i.severity IN ('critical','high')) >= 3
            ) t
            """
        ),
        {"start": start, "end": end},
    ).scalar()

    recurrent_nodes = db.execute(
        text(
            f"""
            SELECT count(*) FROM (
                SELECT i.node_id
                FROM v_incident i
                WHERE i.detected_at >= :start AND i.detected_at < :end
                  AND i.node_id IS NOT NULL
                  {_NOT_MAINTENANCE}
                GROUP BY i.node_id
                HAVING count(*) >= 3
            ) t
            """
        ),
        {"start": start, "end": end},
    ).scalar()

    total = int(row["total_incidents"] or 0)
    resolved = int(row["resolved"] or 0)
    availability = _period_availability(db, month, year)

    prev_month, prev_year = previous_month(month, year)
    prev_start, prev_end = month_bounds(prev_month, prev_year)
    prev_total = db.execute(
        text(
            f"""
            SELECT count(*) FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end {_NOT_MAINTENANCE}
            """
        ),
        {"start": prev_start, "end": prev_end},
    ).scalar() or 0
    prev_availability = _period_availability(db, prev_month, prev_year)

    payload = {
        "period": period_payload(month, year),
        "kpi": {
            "total_incidents": total,
            "resolved": resolved,
            "open": int(row["open"] or 0),
            "critical": int(row["critical"] or 0),
            "resolution_rate_pct": round(resolved / total * 100, 1) if total else 0.0,
            "avg_mttr_minutes": round(float(row["avg_mttr"]), 1) if row["avg_mttr"] else 0.0,
            "avg_mtta_minutes": round(float(row["avg_mtta"]), 1) if row["avg_mtta"] else 0.0,
            "network_availability_pct": availability if availability is not None else 0.0,
            "critical_localities": int(critical_localities or 0),
            "recurrent_nodes": int(recurrent_nodes or 0),
            "off_hours_detected": int(row["off_hours"] or 0),
        },
        "vs_previous_month": {
            "incidents_delta": total - int(prev_total),
            "availability_delta": (
                round((availability or 0.0) - (prev_availability or 0.0), 2)
                if availability is not None and prev_availability is not None
                else 0.0
            ),
        },
    }
    cache_service.set_cached(_cache_key("summary", month, year), payload)
    return payload


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------
def get_localities(db: Session, month: int, year: int, limit: int = 10) -> list[dict]:
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                i.locality_id,
                COALESCE(i.locality, 'Site non rattaché') AS locality,
                COALESCE(i.region, '—')                   AS region,
                count(*)                                  AS total_incidents,
                count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                count(*) FILTER (WHERE i.severity = 'critical')           AS critical,
                avg(i.mttr_minutes)                       AS avg_mttr,
                COALESCE(sum(i.downtime_minutes), 0)      AS downtime
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              {_NOT_MAINTENANCE}
            GROUP BY i.locality_id, i.locality, i.region
            ORDER BY total_incidents DESC
            LIMIT :limit
            """
        ),
        {"start": start, "end": end, "limit": limit},
    ).mappings().all()

    return [
        {
            "locality_id": r["locality_id"],
            "locality": r["locality"],
            "region": r["region"],
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "critical": int(r["critical"]),
            "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
            "availability_pct": _period_availability(db, month, year, r["locality_id"]),
        }
        for r in rows
    ]


def get_localities_map(db: Session, month: int, year: int) -> list[dict]:
    """Sites géolocalisés pour la carte.

    Renvoie TOUS les sites ayant des coordonnées, pas seulement ceux qui
    ont eu des incidents : un site sain doit apparaître en vert sur la
    carte, pas disparaître. Les sites sans coordonnées sont exclus —
    dim_locality.latitude/longitude restent NULL tant que
    etl/scripts/discover_geography.py n'a pas trouvé la donnée dans iTop.
    """
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                l.id            AS locality_id,
                l.name          AS locality,
                COALESCE(r.name, '—') AS region,
                l.latitude,
                l.longitude,
                COALESCE(agg.total_incidents, 0) AS total_incidents,
                COALESCE(agg.resolved, 0)        AS resolved,
                COALESCE(agg.critical, 0)        AS critical,
                agg.avg_mttr,
                (SELECT count(*) FROM dim_node n
                  WHERE n.locality_id = l.id AND n.is_active) AS nb_nodes
            FROM dim_locality l
            LEFT JOIN dim_region r ON r.id = l.region_id
            LEFT JOIN LATERAL (
                SELECT count(*) AS total_incidents,
                       count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                       count(*) FILTER (WHERE i.severity = 'critical')           AS critical,
                       avg(i.mttr_minutes) AS avg_mttr
                FROM v_incident i
                WHERE i.locality_id = l.id
                  AND i.detected_at >= :start AND i.detected_at < :end
                  {_NOT_MAINTENANCE}
            ) agg ON TRUE
            WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL
            ORDER BY total_incidents DESC
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()

    return [
        {
            "locality_id": r["locality_id"],
            "locality": r["locality"],
            "region": r["region"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "nb_nodes": int(r["nb_nodes"]),
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "critical": int(r["critical"]),
            "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
            "availability_pct": _period_availability(db, month, year, r["locality_id"]),
        }
        for r in rows
    ]


def get_locality_nodes(db: Session, locality_id: int, month: int, year: int) -> dict:
    start, end = month_bounds(month, year)

    header = db.execute(
        text(
            """
            SELECT l.id, l.name AS locality, COALESCE(r.name, '—') AS region
            FROM dim_locality l
            LEFT JOIN dim_region r ON r.id = l.region_id
            WHERE l.id = :locality_id
            """
        ),
        {"locality_id": locality_id},
    ).mappings().first()
    if header is None:
        return {}

    rows = db.execute(
        text(
            f"""
            SELECT
                n.node_id,
                n.code,
                n.name,
                COALESCE(n.node_type, 'inconnu')  AS node_type,
                COALESCE(n.source_tool, '—')      AS source_tool,
                n.source_tools,
                n.is_active,
                COALESCE(agg.total_incidents, 0)  AS total_incidents,
                COALESCE(agg.resolved, 0)         AS resolved,
                COALESCE(agg.open, 0)             AS open,
                agg.avg_mttr
            FROM v_node n
            LEFT JOIN LATERAL (
                SELECT count(*) AS total_incidents,
                       count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                       count(*) FILTER (WHERE i.status IN ('open','acknowledged')) AS open,
                       avg(i.mttr_minutes) AS avg_mttr
                FROM v_incident i
                WHERE i.node_id = n.node_id
                  AND i.detected_at >= :start AND i.detected_at < :end
                  {_NOT_MAINTENANCE}
            ) agg ON TRUE
            WHERE n.locality_id = :locality_id
            ORDER BY total_incidents DESC, n.name
            """
        ),
        {"locality_id": locality_id, "start": start, "end": end},
    ).mappings().all()

    return {
        "locality_id": header["id"],
        "locality": header["locality"],
        "region": header["region"],
        "period": period_payload(month, year),
        "nodes": [
            {
                "node_id": r["node_id"],
                "code": r["code"],
                "name": r["name"],
                "node_type": r["node_type"],
                "source_tool": r["source_tool"],
                "source_tools": list(r["source_tools"] or []),
                "is_active": bool(r["is_active"]),
                "total_incidents": int(r["total_incidents"]),
                "resolved": int(r["resolved"]),
                "open": int(r["open"]),
                "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
                "availability_pct": None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Équipements
# ---------------------------------------------------------------------------
def get_nodes(
    db: Session, month: int, year: int, locality_id: int | None = None, limit: int = 10
) -> list[dict]:
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                i.node_id,
                COALESCE(n.code, '—')     AS code,
                COALESCE(n.name, '—')     AS name,
                COALESCE(i.locality, '—') AS locality,
                COALESCE(n.source_tool, i.source_tool) AS source_tool,
                count(*)                  AS total_incidents,
                count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                avg(i.mttr_minutes)       AS avg_mttr
            FROM v_incident i
            LEFT JOIN v_node n ON n.node_id = i.node_id
            WHERE i.detected_at >= :start AND i.detected_at < :end
              AND i.node_id IS NOT NULL
              AND (CAST(:locality_id AS INT) IS NULL OR i.locality_id = :locality_id)
              {_NOT_MAINTENANCE}
            GROUP BY i.node_id, n.code, n.name, i.locality, n.source_tool, i.source_tool
            ORDER BY total_incidents DESC
            LIMIT :limit
            """
        ),
        {"start": start, "end": end, "locality_id": locality_id, "limit": limit},
    ).mappings().all()

    return [
        {
            "node_id": r["node_id"],
            "code": r["code"],
            "name": r["name"],
            "locality": r["locality"],
            "source_tool": r["source_tool"],
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
        }
        for r in rows
    ]


def get_recurrent(db: Session, month: int, year: int, min_count: int = 3) -> list[dict]:
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                i.node_id,
                COALESCE(i.node_code, '—') AS code,
                COALESCE(i.node_name, '—') AS name,
                COALESCE(i.locality, '—')  AS locality,
                count(*)                   AS total_incidents,
                mode() WITHIN GROUP (ORDER BY i.cause_category) AS main_cause
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              AND i.node_id IS NOT NULL
              {_NOT_MAINTENANCE}
            GROUP BY i.node_id, i.node_code, i.node_name, i.locality
            HAVING count(*) >= :min_count
            ORDER BY total_incidents DESC
            """
        ),
        {"start": start, "end": end, "min_count": min_count},
    ).mappings().all()

    return [
        {
            "node_id": r["node_id"],
            "code": r["code"],
            "name": r["name"],
            "locality": r["locality"],
            "total_incidents": int(r["total_incidents"]),
            "main_cause": r["main_cause"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Séries temporelles
# ---------------------------------------------------------------------------
def get_trend(db: Session, month: int, year: int, months: int = 6) -> list[dict]:
    """Tendance sur les `months` derniers mois, mois courant inclus."""
    points = []
    for offset in range(-(months - 1), 1):
        m, y = shift_month(month, year, offset)
        start, end = month_bounds(m, y)
        row = db.execute(
            text(
                f"""
                SELECT count(*) AS total_incidents,
                       count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                       avg(i.mttr_minutes) AS avg_mttr
                FROM v_incident i
                WHERE i.detected_at >= :start AND i.detected_at < :end
                  {_NOT_MAINTENANCE}
                """
            ),
            {"start": start, "end": end},
        ).mappings().first()
        points.append(
            {
                **period_payload(m, y),
                "total_incidents": int(row["total_incidents"] or 0),
                "resolved": int(row["resolved"] or 0),
                "avg_mttr": round(float(row["avg_mttr"]), 1) if row["avg_mttr"] else None,
                "availability_pct": _period_availability(db, m, y),
            }
        )
    return points


def get_hour_distribution(db: Session, month: int, year: int) -> list[dict]:
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT i.detected_hour AS hour, count(*) AS total_incidents
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              {_NOT_MAINTENANCE}
            GROUP BY i.detected_hour
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()

    # Les 24 heures sont toujours renvoyées : un histogramme à trous
    # laisserait croire à une absence de données plutôt qu'à zéro incident.
    counts = {int(r["hour"]): int(r["total_incidents"]) for r in rows if r["hour"] is not None}
    return [{"hour": h, "total_incidents": counts.get(h, 0)} for h in range(24)]


def get_causes(db: Session, month: int, year: int) -> list[dict]:
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                COALESCE(i.cause_category, 'non_identifie') AS category,
                COALESCE(i.cause_label, 'Cause non identifiée') AS label,
                count(*) AS total_incidents,
                avg(i.mttr_minutes) AS avg_mttr
            FROM v_incident i
            WHERE i.detected_at >= :start AND i.detected_at < :end
              {_NOT_MAINTENANCE}
            GROUP BY i.cause_category, i.cause_label
            ORDER BY total_incidents DESC
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()

    total = sum(int(r["total_incidents"]) for r in rows) or 1
    return [
        {
            "category": r["category"],
            "label": r["label"],
            "total_incidents": int(r["total_incidents"]),
            "share_pct": round(int(r["total_incidents"]) / total * 100, 1),
            "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
        }
        for r in rows
    ]


def get_compare(db: Session, month: int, year: int) -> dict:
    """Comparaison mois courant / mois précédent."""
    prev_month_, prev_year = previous_month(month, year)
    current = get_summary(db, month, year)["kpi"]
    previous = get_summary(db, prev_month_, prev_year)["kpi"]

    def _delta(key: str) -> float:
        return round(float(current[key]) - float(previous[key]), 2)

    return {
        "current": {"period": period_payload(month, year), "kpi": current},
        "previous": {"period": period_payload(prev_month_, prev_year), "kpi": previous},
        "delta": {
            "total_incidents": _delta("total_incidents"),
            "resolved": _delta("resolved"),
            "avg_mttr_minutes": _delta("avg_mttr_minutes"),
            "network_availability_pct": _delta("network_availability_pct"),
            "resolution_rate_pct": _delta("resolution_rate_pct"),
        },
    }


# ---------------------------------------------------------------------------
# Ministères — dimension propre au nouvel ETL, absente de l'ancien schéma
# ---------------------------------------------------------------------------
def get_ministries(db: Session, month: int, year: int) -> list[dict]:
    """Incidents et disponibilité par ministère.

    `dim_ministry` est peuplée par etl/scripts/discover_geography.py
    depuis les organisations iTop. Tant que ce script n'a pas tourné, la
    table est vide et cet endpoint renvoie une liste vide — ce n'est pas
    une erreur.
    """
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            f"""
            SELECT
                m.id   AS ministry_id,
                m.name AS ministry,
                (SELECT count(*) FROM dim_node n
                  WHERE n.ministry_id = m.id AND n.is_active) AS nb_nodes,
                COALESCE(agg.total_incidents, 0) AS total_incidents,
                COALESCE(agg.resolved, 0)        AS resolved,
                COALESCE(agg.critical, 0)        AS critical,
                agg.avg_mttr
            FROM dim_ministry m
            LEFT JOIN LATERAL (
                SELECT count(*) AS total_incidents,
                       count(*) FILTER (WHERE i.status IN ('resolved','closed')) AS resolved,
                       count(*) FILTER (WHERE i.severity = 'critical')           AS critical,
                       avg(i.mttr_minutes) AS avg_mttr
                FROM v_incident i
                WHERE i.ministry_id = m.id
                  AND i.detected_at >= :start AND i.detected_at < :end
                  {_NOT_MAINTENANCE}
            ) agg ON TRUE
            ORDER BY total_incidents DESC, m.name
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()

    return [
        {
            "ministry_id": r["ministry_id"],
            "ministry": r["ministry"],
            "nb_nodes": int(r["nb_nodes"]),
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "critical": int(r["critical"]),
            "avg_mttr": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
        }
        for r in rows
    ]


def invalidate_cache() -> None:
    cache_service.invalidate_prefix(CACHE_PREFIX)
