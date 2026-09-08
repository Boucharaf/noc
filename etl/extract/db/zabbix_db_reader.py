"""
Lecteur BDD restaurée Zabbix — schéma natif Zabbix (tables `hosts`,
`events`, `history_uint`/`history`, `trends`), utile principalement pour
combler un historique plus profond que ce que l'API expose par défaut.

Optionnel : n'est utilisé que si ZABBIX_DB_RESTORE_ENABLED=true.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .common import ToolDBUnavailable, fetch_all


def fetch_nodes(dsn: str) -> list[dict]:
    try:
        rows = fetch_all(dsn, "SELECT hostid, host, name, status FROM hosts WHERE flags = 0")
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "zabbix",
            "external_ref": str(r["hostid"]),
            "name": r["name"] or r["host"],
            "is_active": r["status"] == 0,
        }
        for r in rows
    ]


def fetch_incidents(dsn: str, since: datetime) -> list[dict]:
    try:
        rows = fetch_all(
            dsn,
            """
            SELECT e.eventid, e.objectid, e.clock, e.r_eventid, e.severity, h.hostid
            FROM events e
            JOIN functions f ON f.triggerid = e.objectid
            JOIN items i ON i.itemid = f.itemid
            JOIN hosts h ON h.hostid = i.hostid
            WHERE e.source = 0 AND e.object = 0 AND e.value = 1
              AND e.clock >= %s
            """,
            (int(since.replace(tzinfo=timezone.utc).timestamp()),),
        )
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "zabbix",
            "external_id": str(r["eventid"]),
            "node_external_ref": str(r["hostid"]),
            "severity": r["severity"],
            "detected_at": datetime.fromtimestamp(r["clock"], tz=timezone.utc),
            "resolved_at": None,  # jointure r_eventid -> events pour la date de résolution si besoin
            "status": "open",
        }
        for r in rows
    ]


def fetch_metrics(dsn: str, since: datetime) -> list[dict]:
    # Volumétrie potentiellement énorme sur history_uint/history : à activer
    # au cas par cas (fenêtre de rattrapage explicite), pas en routine.
    return []
