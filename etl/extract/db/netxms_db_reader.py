"""
Lecteur BDD restaurée NetXMS.

NetXMS supporte nativement PostgreSQL (entre autres), ce qui simplifie la
restauration par pg_dump/pg_restore par rapport aux autres outils.
Tables clés du schéma NetXMS : `nodes` (objets), `alarms` (historique
d'alarmes), `idata_*` (données de collecte, une table par période/nœud
selon la configuration de rétention — à confirmer sur l'instance réelle).

Optionnel : n'est utilisé que si NETXMS_DB_RESTORE_ENABLED=true.
"""
from __future__ import annotations

from datetime import datetime

from .common import ToolDBUnavailable, fetch_all


def fetch_nodes(dsn: str) -> list[dict]:
    try:
        rows = fetch_all(dsn, "SELECT id, name, status FROM nodes")
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "netxms",
            "external_ref": str(r["id"]),
            "name": r["name"],
            "is_active": r["status"] not in (2, 3),  # 2=UNMANAGED, 3=DISABLED selon convention NetXMS
        }
        for r in rows
    ]


def fetch_incidents(dsn: str, since: datetime) -> list[dict]:
    try:
        rows = fetch_all(
            dsn,
            """
            SELECT alarm_id, source_object_id, current_severity, creation_time, ack_time, term_time
            FROM alarms
            WHERE creation_time >= %s
            """,
            (int(since.timestamp()),),
        )
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "netxms",
            "external_id": str(r["alarm_id"]),
            "node_external_ref": str(r["source_object_id"]),
            "severity": r["current_severity"],
            "resolved_at": r["term_time"] or None,
            "status": "resolved" if r["term_time"] else "open",
        }
        for r in rows
    ]


def fetch_metrics(dsn: str, since: datetime) -> list[dict]:
    # Table idata_* réelle à confirmer sur le dump de l'agence (nommage
    # dépendant de la config de rétention NetXMS) avant implémentation.
    return []
