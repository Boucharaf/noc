"""
Lecteur BDD restaurée Centreon.

Centreon est nativement MariaDB/MySQL (base `centreon` config + base
`centreon_storage` temps réel/historique). Pour rester cohérent avec le
choix pg_dump de l'agence, ce lecteur suppose une conversion préalable de
`centreon_storage` vers un schéma PostgreSQL compatible (voir
scripts/restore_source_db.py) ; les noms de tables ci-dessous
(`hosts`, `services`, `log`) reprennent la convention `centreon_storage`.

Optionnel : n'est utilisé que si CENTREON_DB_RESTORE_ENABLED=true.
"""
from __future__ import annotations

from datetime import datetime

from .common import ToolDBUnavailable, fetch_all


def fetch_nodes(dsn: str) -> list[dict]:
    try:
        rows = fetch_all(dsn, "SELECT host_id, host_name, state FROM hosts")
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "centreon",
            "external_ref": str(r["host_id"]),
            "name": r["host_name"],
            "is_active": True,
        }
        for r in rows
    ]


def fetch_incidents(dsn: str, since: datetime) -> list[dict]:
    """La table `log` de centreon_storage contient l'historique complet des
    changements d'état (host/service) — c'est ce que l'API temps réel ne
    donne pas nativement (voir centreon_client.py)."""
    try:
        rows = fetch_all(
            dsn,
            """
            SELECT log_id, host_name, service_description, status, ctime
            FROM log
            WHERE ctime >= %s AND status != 0
            """,
            (int(since.timestamp()),),
        )
    except ToolDBUnavailable:
        return []
    return [
        {
            "source_tool": "centreon",
            "external_id": str(r["log_id"]),
            "node_external_ref": r["host_name"],
            "severity": r["status"],
            "detected_at": datetime.fromtimestamp(r["ctime"]),
            "description": r["service_description"],
            "status": "open",
        }
        for r in rows
    ]


def fetch_metrics(dsn: str, since: datetime) -> list[dict]:
    # Table `data_bin` (centreon_storage) pour les perfdata historiques —
    # à activer une fois le mapping metric_id -> metric_type confirmé.
    return []
