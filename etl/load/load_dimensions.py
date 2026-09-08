"""
Chargement des dimensions dans l'entrepôt (upsert idempotent).

`load_nodes` prend en entrée :
    - les nœuds normalisés (transform/normalize_nodes.py)
    - les groupes de fusion produits par transform/identity_resolution.py

et garantit qu'un même équipement physique (plusieurs source_tool) ne crée
qu'une seule ligne `dim_node`, avec une entrée `dim_node_source_map` par
outil qui le supervise.
"""
from __future__ import annotations

import psycopg2
import psycopg2.extras


def load_nodes(conn: "psycopg2.extensions.connection", nodes: list[dict], merge_groups: list[dict]):
    with conn.cursor() as cur:
        # 1. construit un lookup (source_tool, external_ref) -> group_key pour les nœuds fusionnés
        ref_to_group: dict[tuple[str, str], str] = {}
        for group in merge_groups:
            for n in group["nodes"]:
                ref_to_group[(n["source_tool"], n["external_ref"])] = group["key"]

        group_key_to_node_id: dict[str, int] = {}

        for node in nodes:
            ref = (node["source_tool"], node["external_ref"])
            group_key = ref_to_group.get(ref)

            if group_key and group_key in group_key_to_node_id:
                node_id = group_key_to_node_id[group_key]
            else:
                node_id = _upsert_dim_node(cur, node)
                if group_key:
                    group_key_to_node_id[group_key] = node_id

            cur.execute(
                """
                INSERT INTO dim_node_source_map (node_id, source_tool, external_ref)
                VALUES (%s, %s, %s)
                ON CONFLICT (source_tool, external_ref) DO UPDATE SET node_id = EXCLUDED.node_id
                """,
                (node_id, node["source_tool"], node["external_ref"]),
            )
    conn.commit()


def _upsert_dim_node(cur, node: dict) -> int:
    cur.execute(
        """
        INSERT INTO dim_node (name, ip_address, is_active, ministry_id, locality_id)
        VALUES (%s, %s, %s,
                (SELECT id FROM dim_ministry WHERE external_ref = %s),
                (SELECT id FROM dim_locality WHERE external_ref = %s))
        ON CONFLICT (name, ip_address) DO UPDATE SET
            is_active = EXCLUDED.is_active
        RETURNING id
        """,
        (
            node["name"],
            node.get("ip_address"),
            node["is_active"],
            node.get("ministry_external_ref"),
            node.get("locality_external_ref"),
        ),
    )
    return cur.fetchone()[0]


def resolve_node_id(cur, source_tool: str, external_ref: str) -> int | None:
    cur.execute(
        "SELECT node_id FROM dim_node_source_map WHERE source_tool = %s AND external_ref = %s",
        (source_tool, external_ref),
    )
    row = cur.fetchone()
    return row[0] if row else None
