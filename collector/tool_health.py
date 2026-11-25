"""
Santé des outils dans le temps (hist_tool_health).

POURQUOI. Redis ne garde que l'état courant de chaque outil. Sans historique,
rien ne dit, des mois plus tard, pourquoi des équipements n'ont pas été
observés tel jour : outil en panne, ou collecteur arrêté ?

Une ligne par période, comme hist_state : seuls les changements s'ajoutent.
  up       l'outil a répondu, inventaire et alertes lus
  partial  une partie seulement a été lue
  down     rien n'a été lu
Un trou (collecteur arrêté) n'est compté ni disponible ni en panne.
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import config
from .history import INTERVAL, MAX_GAP

logger = logging.getLogger(__name__)


def observed(healths: dict, source_status: dict) -> dict[str, dict]:
    """État de chaque outil à ce cycle."""
    rows = {}
    for tool, health in healths.items():
        fresh = [
            bool(stream.get("collected_at")) and not stream.get("stale")
            for stream in (source_status.get(tool) or {}).values()
        ]
        if health.reachable and all(fresh):
            state = "up"
        elif any(fresh):
            state = "partial"
        else:
            state = "down"
        rows[tool] = {
            "tool": tool, "state": state, "version": health.version,
            "error": (health.error or "")[:500] or None if state != "up" else None,
        }
    return rows


def plan(open_rows: list[dict], current: dict[str, dict],
         now: datetime) -> tuple[list[tuple], list[dict], list[int]]:
    """(périodes à clore [(id, fin)], à ouvrir, à prolonger)."""
    closes, touches, seen = [], [], set()
    inserts = []
    for row in open_rows:
        seen.add(row["tool"])
        seen_now = current.get(row["tool"])
        if now - row["last_seen_at"] > MAX_GAP:
            closes.append((row["id"], row["last_seen_at"] + INTERVAL))
            if seen_now:
                inserts.append(seen_now)
        elif seen_now is None:
            closes.append((row["id"], now))   # outil retiré de la configuration
        elif seen_now["state"] != row["state"]:
            closes.append((row["id"], now))
            inserts.append(seen_now)
        else:
            touches.append(row["id"])
    inserts.extend(row for tool, row in current.items() if tool not in seen)
    return closes, inserts, touches


async def record(healths: dict, source_status: dict, now: datetime) -> None:
    """Lève en cas d'erreur de base : l'appelant l'intercepte."""
    import psycopg
    from psycopg.rows import dict_row

    current = observed(healths, source_status)
    async with await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, row_factory=dict_row, connect_timeout=10
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, tool, state, last_seen_at FROM hist_tool_health "
                "WHERE ended_at IS NULL"
            )
            closes, inserts, touches = plan(await cur.fetchall(), current, now)
            if closes:
                await cur.executemany(
                    "UPDATE hist_tool_health SET ended_at = %s WHERE id = %s",
                    [(ended, row_id) for row_id, ended in closes],
                )
            if touches:
                await cur.execute(
                    "UPDATE hist_tool_health SET last_seen_at = %s WHERE id = ANY(%s)",
                    (now, touches),
                )
            if inserts:
                await cur.executemany(
                    "INSERT INTO hist_tool_health "
                    "(tool, state, error, version, started_at, last_seen_at) VALUES "
                    "(%(tool)s, %(state)s, %(error)s, %(version)s, %(now)s, %(now)s) "
                    "ON CONFLICT (tool) WHERE ended_at IS NULL DO NOTHING",
                    [{**row, "now": now} for row in inserts],
                )
        await conn.commit()
