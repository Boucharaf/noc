"""
Lecteur BDD Nagios via NDOUtils.

Contrairement aux autres lecteurs de ce dossier, celui-ci n'est PAS
purement optionnel dans l'hypothèse où Nagios Core ne serait accessible
ni via Livestatus ni via Nagios XI (voir extract/api/README.md) : NDOUtils
serait alors la seule voie de collecte pour cet outil, API ou pas.
`pipelines/collector.py` le traite malgré tout comme une source
"secondaire" au sens technique (module `extract/db/`), simplement activée
en permanence pour Nagios si `NAGIOS_MODE=ndoutils`.

Schéma NDOUtils (préfixe `nagios_` par défaut) : `nagios_hosts`,
`nagios_hoststatus`, `nagios_servicestatus`, `nagios_statehistory`.
"""
from __future__ import annotations

from datetime import datetime

from .common import ToolDBUnavailable, fetch_all


def fetch_nodes(dsn: str) -> list[dict]:
    try:
        rows = fetch_all(dsn, "SELECT host_object_id, display_name, address FROM nagios_hosts")
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "nagios",
            "external_ref": str(r["host_object_id"]),
            "name": r["display_name"],
            "ip_address": r["address"],
            "is_active": True,
        }
        for r in rows
    ]


def fetch_incidents(dsn: str, since: datetime) -> list[dict]:
    try:
        rows = fetch_all(
            dsn,
            """
            SELECT statehistory_id, host_object_id, service_object_id, state,
                   state_time, state_change
            FROM nagios_statehistory
            WHERE state_time >= %s AND state != 0
            """,
            (since,),
        )
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "nagios",
            "external_id": str(r["statehistory_id"]),
            "node_external_ref": str(r["host_object_id"]),
            "severity": r["state"],
            "detected_at": r["state_time"],
            "status": "open",
        }
        for r in rows
    ]


def fetch_metrics(dsn: str, since: datetime) -> list[dict]:
    # Pas de perfdata structurée dans le schéma NDOUtils de base (dépend
    # d'un module additionnel type PNP4Nagios/Graphite non confirmé).
    return []
