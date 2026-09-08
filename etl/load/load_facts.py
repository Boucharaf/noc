"""
Chargement de fact_incident (upsert par (source_tool, external_id)) et
calcul quotidien de fact_supervision_coverage_daily.
"""
from __future__ import annotations

from datetime import date

import psycopg2

from .load_dimensions import resolve_node_id


def load_incidents(conn: "psycopg2.extensions.connection", incidents: list[dict]):
    with conn.cursor() as cur:
        for inc in incidents:
            node_id = (
                resolve_node_id(cur, inc["source_tool"], inc["node_external_ref"])
                if inc.get("node_external_ref")
                else None
            )
            cur.execute(
                """
                INSERT INTO fact_incident (
                    source_tool, external_id, node_id, itop_ticket_ref, status, severity,
                    detected_at, acknowledged_at, resolved_at,
                    mtta_minutes, mttr_minutes, downtime_minutes,
                    description, cause_category
                ) VALUES (%(source_tool)s, %(external_id)s, %(node_id)s, %(itop_ticket_ref)s,
                          %(status)s, %(severity)s, %(detected_at)s, %(acknowledged_at)s,
                          %(resolved_at)s, %(mtta_minutes)s, %(mttr_minutes)s,
                          %(downtime_minutes)s, %(description)s, %(cause_category)s)
                ON CONFLICT (source_tool, external_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    acknowledged_at = COALESCE(fact_incident.acknowledged_at, EXCLUDED.acknowledged_at),
                    resolved_at = COALESCE(EXCLUDED.resolved_at, fact_incident.resolved_at),
                    mtta_minutes = COALESCE(fact_incident.mtta_minutes, EXCLUDED.mtta_minutes),
                    mttr_minutes = COALESCE(EXCLUDED.mttr_minutes, fact_incident.mttr_minutes),
                    downtime_minutes = COALESCE(EXCLUDED.downtime_minutes, fact_incident.downtime_minutes)
                """,
                {**inc, "node_id": node_id},
            )
    conn.commit()


def refresh_supervision_coverage(conn: "psycopg2.extensions.connection", as_of: date):
    """Recalcule la couverture de supervision du jour à partir de
    dim_node / dim_node_source_map : un équipement est "supervisé" dès
    qu'il a au moins une ligne dans dim_node_source_map."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fact_supervision_coverage_daily
                (date, ministry_id, locality_id, nb_equip_total, nb_equip_supervised)
            SELECT %s, n.ministry_id, n.locality_id,
                   COUNT(*) AS nb_equip_total,
                   COUNT(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM dim_node_source_map m WHERE m.node_id = n.id
                   )) AS nb_equip_supervised
            FROM dim_node n
            GROUP BY n.ministry_id, n.locality_id
            ON CONFLICT (date, ministry_id, locality_id) DO UPDATE SET
                nb_equip_total = EXCLUDED.nb_equip_total,
                nb_equip_supervised = EXCLUDED.nb_equip_supervised
            """,
            (as_of,),
        )
    conn.commit()
