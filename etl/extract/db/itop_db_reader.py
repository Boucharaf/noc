"""
Lecteur BDD restaurée iTop.

Schéma : iTop nomme ses tables selon la convention `<classe_en_minuscules>`
(ex. table `incident`, `networkdevice`) avec un préfixe configurable
(souvent aucun, parfois `itop_`). Les noms exacts de colonnes ci-dessous
supposent le schéma standard iTop 3.2 sans personnalisation — à vérifier
sur le dump réel de l'agence avant mise en production (les organisations
personnalisent fréquemment leur datamodel iTop).

Optionnel : n'est utilisé que si ITOP_DB_RESTORE_ENABLED=true.
"""
from __future__ import annotations

from datetime import datetime

from .common import ToolDBUnavailable, fetch_all


def fetch_incidents(dsn: str, since: datetime) -> list[dict]:
    try:
        rows = fetch_all(
            dsn,
            """
            SELECT id, ref, status, start_date, resolution_date, close_date, priority, org_id
            FROM incident
            WHERE start_date >= %s
            """,
            (since,),
        )
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "itop",
            "external_id": str(r["id"]),
            "itop_ticket_ref": r["ref"],
            "status": r["status"],
            "detected_at": r["start_date"],
            "resolved_at": r["resolution_date"] or r["close_date"],
            "severity": r["priority"],
            "ministry_external_ref": r["org_id"],
        }
        for r in rows
    ]


def fetch_nodes(dsn: str) -> list[dict]:
    nodes = []
    for table, cls in (("networkdevice", "NetworkDevice"), ("server", "Server")):
        try:
            rows = fetch_all(dsn, f"SELECT id, name, status, org_id, location_id FROM {table}")
        except ToolDBUnavailable:
            continue
        for r in rows:
            nodes.append(
                {
                    "source_tool": "itop",
                    "external_ref": str(r["id"]),
                    "external_type": cls,
                    "name": r["name"],
                    "is_active": r["status"] not in ("obsolete", "decommissioned"),
                    "ministry_external_ref": r["org_id"],
                    "locality_external_ref": r["location_id"],
                }
            )
    return nodes


def fetch_metrics(dsn: str, since: datetime) -> list[dict]:
    return []  # iTop = CMDB/ITSM, pas de métriques temporelles
