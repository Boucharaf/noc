"""
Chargement en masse dans la hypertable `metric_value` (TimescaleDB).

Utilise `execute_values` (insertion par lots) plutôt qu'un INSERT par
ligne : les métriques sont potentiellement le plus gros volume de tout
le pipeline (une valeur par item/DCI/métrique et par intervalle de
collecte, pour ~150+ équipements).
"""
from __future__ import annotations

import psycopg2
import psycopg2.extras

from .load_dimensions import resolve_node_id


def load_metrics(conn: "psycopg2.extensions.connection", metrics: list[dict]):
    if not metrics:
        return
    with conn.cursor() as cur:
        rows = []
        for m in metrics:
            node_id = (
                resolve_node_id(cur, m["source_tool"], m["node_external_ref"])
                if m.get("node_external_ref")
                else None
            )
            if node_id is None and not m.get("link_external_ref"):
                continue  # métrique orpheline (nœud pas encore chargé) -> ignorée, pas d'erreur bloquante
            rows.append((m["time"], node_id, None, m["source_tool"], m["metric_type"], m["value"]))

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO metric_value (time, node_id, link_id, source_tool, metric_type, value)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )
    conn.commit()
