"""
Inventaire des équipements supervisés.

Ce module apporte au dashboard le niveau 4 de l'architecture métier
(« Vue technique : équipement, interface, CPU, RAM, trafic, latence,
pertes, historique »). Les agrégats KPI existants répondent à « quels
sites souffrent ce mois-ci » ; ils ne répondent pas à « montre-moi
l'équipement X maintenant », qui est la question qu'un exploitant pose le
plus souvent.

ÉTAT D'UN ÉQUIPEMENT — l'ETL ne publie aucun champ up/down. L'état est
donc DÉDUIT, dans cet ordre de priorité :

  maintenance : une fenêtre ops_maintenance_window active le couvre ;
  down        : incident critique/majeur ouvert dont la cause est une
                indisponibilité (equipement_down, lien_down, alimentation),
                ou dernière mesure availability_pct nulle ;
  degraded    : au moins un incident ouvert, ou un seuil dépassé
                (disponibilité < 99 %, pertes > 5 %, CPU/RAM > 90 %) ;
  silent      : aucune métrique reçue depuis LATEST_METRIC_WINDOW_HOURS —
                l'outil de supervision ne remonte plus rien sur cet
                équipement, ce qui est une information en soi et pas un
                « tout va bien » ;
  up          : le reste.

Cette dérivation vit ici et pas dans le frontend pour deux raisons : le
tri « les plus dégradés d'abord » doit être fait par PostgreSQL sur
l'ensemble du parc (pas seulement sur la page affichée), et le même
vocabulaire doit servir la carte, l'inventaire et le mur d'alertes.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Fenêtre de la « dernière valeur connue » de chaque métrique, et donc
# seuil au-delà duquel un équipement est déclaré muet. Deux cycles de
# collecte (COLLECT_INTERVAL_S = 300 s) suffiraient en théorie ; 6 heures
# évite de noyer l'inventaire de faux muets quand un connecteur ne publie
# certaines métriques qu'une fois par heure.
LATEST_METRIC_WINDOW_HOURS = 6

_STATE_ORDER = """
    CASE state
        WHEN 'down'        THEN 0
        WHEN 'degraded'    THEN 1
        WHEN 'silent'      THEN 2
        WHEN 'maintenance' THEN 3
        WHEN 'up'          THEN 4
        ELSE 5
    END
"""

# Tri : liste blanche stricte. Le paramètre arrive de l'URL, il ne doit
# jamais être concaténé tel quel dans le SQL.
_SORTS = {
    "state": f"{_STATE_ORDER}, open_incidents DESC, name",
    "name": "name",
    "locality": "locality NULLS LAST, name",
    "open_incidents": "open_incidents DESC, name",
    "incidents_30d": "incidents_30d DESC, name",
    "availability": "availability_pct ASC NULLS LAST, name",
    "last_incident": "last_incident_at DESC NULLS LAST",
}

# Bloc commun à la liste et au détail : évite que les deux divergent sur
# la définition de l'état, ce qui donnerait un équipement « down » dans
# l'inventaire et « up » sur sa fiche.
_ENRICHED_NODES = """
WITH latest_metric AS (
    SELECT DISTINCT ON (m.node_id, m.metric_type)
           m.node_id, m.metric_type, m.value, m.time
    FROM metric_value m
    WHERE m.time > now() - make_interval(hours => :metric_window_h)
    ORDER BY m.node_id, m.metric_type, m.time DESC
),
node_metric AS (
    SELECT node_id,
           max(time)                                                     AS last_metric_at,
           max(value) FILTER (WHERE metric_type = 'availability_pct')    AS availability_pct,
           max(value) FILTER (WHERE metric_type = 'latency_ms')          AS latency_ms,
           max(value) FILTER (WHERE metric_type = 'packet_loss_pct')     AS packet_loss_pct,
           max(value) FILTER (WHERE metric_type = 'cpu_pct')             AS cpu_pct,
           max(value) FILTER (WHERE metric_type = 'ram_pct')             AS ram_pct,
           max(value) FILTER (WHERE metric_type = 'bandwidth_in_mbps')   AS bandwidth_in_mbps,
           max(value) FILTER (WHERE metric_type = 'bandwidth_out_mbps')  AS bandwidth_out_mbps
    FROM latest_metric
    GROUP BY node_id
),
node_incident AS (
    SELECT i.node_id,
           count(*) FILTER (WHERE i.status IN ('open','acknowledged'))            AS open_incidents,
           count(*) FILTER (WHERE i.status IN ('open','acknowledged')
                              AND i.severity = 'critical')                       AS critical_incidents,
           count(*) FILTER (WHERE i.detected_at > now() - INTERVAL '30 days')    AS incidents_30d,
           max(i.detected_at)                                                    AS last_incident_at,
           min(i.severity_rank) FILTER (WHERE i.status IN ('open','acknowledged')) AS worst_open_rank,
           min(i.detected_at) FILTER (
               WHERE i.status IN ('open','acknowledged')
                 AND i.severity IN ('critical','high')
                 AND i.cause_category IN ('equipement_down','lien_down','alimentation')
           )                                                                     AS down_since
    FROM v_incident i
    WHERE NOT i.is_maintenance
    GROUP BY i.node_id
),
node_maintenance AS (
    SELECT n.node_id, max(w.ends_at) AS maintenance_until
    FROM v_node n
    JOIN ops_maintenance_window w
      ON (w.node_id = n.node_id OR w.locality_id = n.locality_id)
     AND now() BETWEEN w.starts_at AND w.ends_at
    GROUP BY n.node_id
),
enriched AS (
    SELECT
        n.node_id, n.code, n.name, n.ip_address, n.node_type, n.is_active,
        n.locality_id, n.locality, n.region_id, n.region,
        n.ministry_id, n.ministry, n.latitude, n.longitude,
        n.source_tools, n.nb_source_tools, n.source_tool,
        mt.last_metric_at, mt.availability_pct, mt.latency_ms, mt.packet_loss_pct,
        mt.cpu_pct, mt.ram_pct, mt.bandwidth_in_mbps, mt.bandwidth_out_mbps,
        COALESCE(ni.open_incidents, 0)     AS open_incidents,
        COALESCE(ni.critical_incidents, 0) AS critical_incidents,
        COALESCE(ni.incidents_30d, 0)      AS incidents_30d,
        ni.last_incident_at,
        ni.worst_open_rank,
        ni.down_since,
        nm.maintenance_until,
        CASE
            WHEN NOT n.is_active                       THEN 'inactive'
            WHEN nm.maintenance_until IS NOT NULL      THEN 'maintenance'
            WHEN ni.down_since IS NOT NULL
              OR mt.availability_pct = 0               THEN 'down'
            WHEN COALESCE(ni.open_incidents, 0) > 0
              OR mt.availability_pct < 99
              OR mt.packet_loss_pct > 5
              OR mt.cpu_pct > 90
              OR mt.ram_pct > 90                       THEN 'degraded'
            WHEN mt.last_metric_at IS NULL             THEN 'silent'
            ELSE 'up'
        END AS state
    FROM v_node n
    LEFT JOIN node_metric      mt ON mt.node_id = n.node_id
    LEFT JOIN node_incident    ni ON ni.node_id = n.node_id
    LEFT JOIN node_maintenance nm ON nm.node_id = n.node_id
)
"""

STATES = ("down", "degraded", "silent", "maintenance", "up", "inactive")


def _base_params() -> dict:
    return {"metric_window_h": LATEST_METRIC_WINDOW_HOURS}


def _row(r) -> dict:
    data = dict(r)
    data["source_tools"] = list(data.get("source_tools") or [])
    return data


def list_nodes(
    db: Session,
    *,
    q: str | None = None,
    locality_id: int | None = None,
    region_id: int | None = None,
    ministry_id: int | None = None,
    node_type: str | None = None,
    source_tool: str | None = None,
    state: str | None = None,
    sort: str = "state",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    page = max(1, page)
    page_size = max(1, min(200, page_size))

    where = ["TRUE"]
    params = _base_params()

    if q:
        # Un exploitant tape un fragment de nom ou une IP, jamais l'un des
        # deux exactement : la recherche porte sur les deux à la fois.
        where.append("(name ILIKE :q OR COALESCE(ip_address,'') ILIKE :q)")
        params["q"] = f"%{q}%"
    if locality_id is not None:
        where.append("locality_id = :locality_id")
        params["locality_id"] = locality_id
    if region_id is not None:
        where.append("region_id = :region_id")
        params["region_id"] = region_id
    if ministry_id is not None:
        where.append("ministry_id = :ministry_id")
        params["ministry_id"] = ministry_id
    if node_type:
        where.append("node_type = :node_type")
        params["node_type"] = node_type
    if source_tool:
        where.append(":source_tool = ANY(source_tools)")
        params["source_tool"] = source_tool
    if state:
        where.append("state = :state")
        params["state"] = state

    where_sql = " AND ".join(where)
    order_sql = _SORTS.get(sort, _SORTS["state"])

    total = db.execute(
        text(f"{_ENRICHED_NODES} SELECT count(*) FROM enriched WHERE {where_sql}"),
        params,
    ).scalar() or 0

    rows = db.execute(
        text(
            f"""
            {_ENRICHED_NODES}
            SELECT * FROM enriched
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()

    return {
        "items": [_row(r) for r in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "pages": max(1, (int(total) + page_size - 1) // page_size),
    }


def count_by_state(db: Session, locality_id: int | None = None) -> dict[str, int]:
    """Répartition du parc par état — l'en-tête de toutes les vues parc."""
    rows = db.execute(
        text(
            f"""
            {_ENRICHED_NODES}
            SELECT state, count(*) AS nb
            FROM enriched
            WHERE (CAST(:locality_id AS INT) IS NULL OR locality_id = :locality_id)
            GROUP BY state
            """
        ),
        {**_base_params(), "locality_id": locality_id},
    ).mappings().all()

    counts = {r["state"]: int(r["nb"]) for r in rows}
    # Les états absents doivent valoir 0 et non disparaître : un compteur
    # qui s'efface quand il tombe à zéro fait sauter la mise en page.
    for state in STATES:
        counts.setdefault(state, 0)
    counts["total"] = sum(counts[state] for state in STATES)
    return counts


def get_node(db: Session, node_id: int) -> dict:
    row = db.execute(
        text(f"{_ENRICHED_NODES} SELECT * FROM enriched WHERE node_id = :node_id"),
        {**_base_params(), "node_id": node_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Équipement introuvable.")

    node = _row(row)

    # Identifiants dans chaque outil : indispensable pour rebondir vers
    # Zabbix ou Centreon depuis la fiche, et pour comprendre pourquoi un
    # même équipement porte deux incidents apparemment identiques.
    node["source_refs"] = [
        dict(r)
        for r in db.execute(
            text(
                """
                SELECT source_tool, external_ref
                FROM dim_node_source_map
                WHERE node_id = :node_id
                ORDER BY source_tool
                """
            ),
            {"node_id": node_id},
        ).mappings().all()
    ]

    node["metric_types"] = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT DISTINCT metric_type FROM metric_value
                WHERE node_id = :node_id AND time > now() - INTERVAL '7 days'
                ORDER BY metric_type
                """
            ),
            {"node_id": node_id},
        ).all()
    ]

    stats = db.execute(
        text(
            """
            SELECT
                count(*) FILTER (WHERE detected_at > now() - INTERVAL '90 days')  AS incidents_90d,
                avg(mttr_minutes) FILTER (WHERE resolved_at IS NOT NULL
                                            AND detected_at > now() - INTERVAL '90 days') AS avg_mttr,
                sum(downtime_minutes) FILTER (WHERE detected_at > now() - INTERVAL '30 days') AS downtime_30d
            FROM v_incident
            WHERE node_id = :node_id AND NOT is_maintenance
            """
        ),
        {"node_id": node_id},
    ).mappings().first()

    node["incidents_90d"] = int(stats["incidents_90d"] or 0)
    node["avg_mttr_minutes"] = (
        round(float(stats["avg_mttr"]), 1) if stats["avg_mttr"] is not None else None
    )
    node["downtime_30d_minutes"] = (
        round(float(stats["downtime_30d"]), 1) if stats["downtime_30d"] is not None else None
    )
    return node


def get_node_incidents(db: Session, node_id: int, limit: int = 20) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT i.id, i.severity, i.status, i.description,
                   i.cause_category, i.cause_label, i.source_tool,
                   i.detected_at, i.acknowledged_at, i.resolved_at,
                   i.mttr_minutes, i.is_maintenance,
                   EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60 AS age_minutes
            FROM v_incident i
            WHERE i.node_id = :node_id
            ORDER BY i.detected_at DESC NULLS LAST
            LIMIT :limit
            """
        ),
        {"node_id": node_id, "limit": max(1, min(200, limit))},
    ).mappings().all()

    return [
        {
            **dict(r),
            "age_minutes": int(r["age_minutes"]) if r["age_minutes"] is not None else None,
        }
        for r in rows
    ]
