"""
Conservation des données de la base du NOC.

DÉSACTIVÉE PAR DÉFAUT : tant que l'agence n'a pas fixé de durée légale, rien
n'est supprimé. RETENTION_ENABLED=true ne suffit pas : chaque table demande
en plus sa durée (0 = conservation indéfinie).

Au plus une purge par jour, tracée dans le journal d'audit.

JAMAIS PURGÉS ICI :
  report_snapshot     rapports figés (la base le refuse)
  noc_asset*          registre d'identité : il donne son sens à l'historique
  hist_downtime       le calcul tient le journal copié pour complet ; y
                      retirer des pannes gonflerait la disponibilité passée
  ops_alert_notified  le retirer ferait renotifier des alertes ouvertes
hist_state et hist_alert suivent HISTORY_RETENTION_DAYS (collector/history.py).

    python -m collector.retention preview
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

from . import config

logger = logging.getLogger(__name__)

# table -> (variable, colonne de date, condition, minimum de jours accepté)
RULES = {
    "ops_audit_log": ("RETENTION_AUDIT_DAYS", "created_at", "TRUE", 365),
    "ops_notification_log": ("RETENTION_NOTIFICATION_DAYS", "created_at", "TRUE", 30),
    "ops_notification_retry": (
        "RETENTION_NOTIFICATION_DAYS", "updated_at", "status <> 'pending'", 30,
    ),
    "hist_tool_health": (
        "RETENTION_TOOL_HEALTH_DAYS", "ended_at", "ended_at IS NOT NULL", 90,
    ),
    "kpi_daily": ("RETENTION_KPI_DAYS", "day", "TRUE", 400),
}
_BATCH = 10_000
_MAX_BATCHES = 50
_last_run: date | None = None


def limits(now: datetime) -> dict[str, datetime]:
    """Date avant laquelle chaque table est purgée ; absente = jamais."""
    result = {}
    for table, (variable, _column, _condition, minimum) in RULES.items():
        days = config.RETENTION_DAYS.get(variable, 0)
        if days <= 0:
            continue
        if days < minimum:
            logger.error("%s=%d refusé (minimum %d jours) : %s conservée",
                         variable, days, minimum, table)
            continue
        result[table] = now - timedelta(days=days)
    return result


async def _connect():
    import psycopg

    return await psycopg.AsyncConnection.connect(config.DATABASE_URL, connect_timeout=10)


async def run(now: datetime) -> dict[str, int]:
    """Purge du jour. Lève en cas d'erreur de base."""
    global _last_run
    if not config.RETENTION_ENABLED or _last_run == now.date():
        return {}
    removed: dict[str, int] = {}
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            for table, limit in limits(now).items():
                _variable, column, condition, _minimum = RULES[table]
                total = 0
                # Par lots : un premier passage sur des années de données ne
                # doit pas bloquer les écritures du cycle suivant.
                for _ in range(_MAX_BATCHES):
                    await cur.execute(
                        f"DELETE FROM {table} WHERE ctid IN (SELECT ctid FROM {table} "  # noqa: S608
                        f"WHERE {column} < %s AND {condition} LIMIT {_BATCH})",
                        (limit,),
                    )
                    total += cur.rowcount
                    if cur.rowcount < _BATCH:
                        break
                if total:
                    removed[table] = total
            if removed:
                await cur.execute(
                    "INSERT INTO ops_audit_log (action, target, detail) "
                    "VALUES ('retention.purged', 'base du NOC', %s)",
                    (json.dumps(removed),),
                )
        await conn.commit()
    _last_run = now.date()
    if removed:
        logger.info("Conservation : lignes supprimées %s", removed)
    return removed


async def preview(now: datetime) -> list[tuple[str, int, int]]:
    """(table, lignes, lignes qui seraient supprimées), sans rien supprimer."""
    bounds = limits(now)
    rows = []
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            for table, (_variable, column, condition, _minimum) in RULES.items():
                await cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
                total = (await cur.fetchone())[0]
                due = 0
                if table in bounds:
                    await cur.execute(
                        f"SELECT count(*) FROM {table} "  # noqa: S608
                        f"WHERE {column} < %s AND {condition}", (bounds[table],),
                    )
                    due = (await cur.fetchone())[0]
                rows.append((table, total, due))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m collector.retention")
    parser.add_argument("command", choices=["preview"])
    parser.parse_args()
    print(f"Purge {'activée' if config.RETENTION_ENABLED else 'désactivée'}")
    for table, total, due in asyncio.run(preview(datetime.now(timezone.utc))):
        print(f"{table:26} {total:>10} ligne(s)  {due:>10} à supprimer")


if __name__ == "__main__":
    main()
