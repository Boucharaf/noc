"""
Journal historique : périodes d'état et vie des alertes.

POURQUOI CE FICHIER EXISTE. L'architecture ne recopie pas les données des
outils ; l'historique du NOC se limitait à des moyennes journalières par site
(collector/rollup.py). Impossible, avec elles, de répondre à « quelle a été
la disponibilité de CE lien sur l'année ? », de calculer un MTTR technique,
ou de reconstituer un bilan journalier perdu. Ce journal garde, non pas les
mesures, mais les CHANGEMENTS :

  hist_state  une ligne par période d'état d'un équipement (`node`) ou d'un
              lien surveillé (`link`, NetXMS) : ouverte au changement d'état,
              close au suivant ;
  hist_alert  une ligne par alerte (outils et tickets iTop), de son
              ouverture (date de la source) à sa disparition.

Quelques Mo par mois : les tables ne grandissent qu'aux changements. Une
période ouverte est prolongée à chaque cycle (`last_seen_at`) par une seule
requête groupée.

CE QUI N'EST JAMAIS FAIT :
  * clore une période ou une alerte parce que son OUTIL n'a pas répondu :
    seuls les outils dont le flux a été lu à ce cycle (frais ou repris du
    dernier succès) peuvent faire disparaître quelque chose ;
  * compter comme disponible un temps non observé : au-delà de trois cycles
    sans observation (collecteur arrêté, outil muet), la période est close à
    sa dernière observation, et le trou reste un trou.

PRÉCISION : un changement est daté du cycle où il est vu, soit à
COLLECT_INTERVAL_S près (5 min par défaut). L'ouverture d'une alerte, elle,
est la date donnée par l'outil.

NE CASSE PAS LE CYCLE : `record` est appelé après la publication de
l'instantané, borné dans le temps, et toute erreur est journalisée sans
remonter (collector/cycle.py). HISTORY_ENABLED=false le coupe.

Recalcul des bilans journaliers depuis le journal :
    python -m collector.history rebuild-daily --from 2026-10-01 [--to …] [--overwrite]
    python -m collector.history backfill [--days 30]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from . import config

logger = logging.getLogger(__name__)

# Au-delà de trois cycles sans observation, la période est close.
MAX_GAP = timedelta(seconds=3 * config.COLLECT_INTERVAL_S)
INTERVAL = timedelta(seconds=config.COLLECT_INTERVAL_S)
_DAY_S = 86400.0
_last_purge: date | None = None


# ---------------------------------------------------------------------------
# Ce qui est observé à ce cycle
# ---------------------------------------------------------------------------
def subjects(merged, maintenance_keys: set[str]) -> dict[str, dict]:
    """Équipements et liens surveillés du cycle, indexés par sujet.

    `state` est l'état affiché (« maintenance » pendant une maintenance
    planifiée) ; `measured_state` l'état que mesurent les outils. Un lien
    hérite de la maintenance de son équipement.
    """
    rows: dict[str, dict] = {}
    for node in merged:
        in_maintenance = node.id in maintenance_keys or node.state == "maintenance"
        base = {
            "node_id": node.id,
            "site": node.site,
            "province": node.province,
            "region": node.region,
            "tools": ",".join(sorted(node.sources)),
        }
        rows[node.id] = {
            **base,
            "subject_kind": "node",
            "subject_id": node.id,
            "name": node.name,
            "state": "maintenance" if in_maintenance else node.state,
            "measured_state": node.state,
        }
        for tool, facts in (node.details or {}).items():
            for link in (facts or {}).get("links") or []:
                subject_id = f"{node.id}|{tool}:{link['ref']}"
                rows[subject_id] = {
                    **base,
                    "tools": tool,
                    "subject_kind": "link",
                    "subject_id": subject_id,
                    "name": f"{node.name} — {link.get('name') or link['ref']}",
                    "state": "maintenance" if in_maintenance else link.get("state", "unknown"),
                    "measured_state": link.get("state", "unknown"),
                }
    return rows


def alert_rows(alerts, merged) -> dict[str, dict]:
    """Alertes du cycle, avec l'équipement et la localité où elles sont vues."""
    by_source = {
        f"{tool}:{ref}": node for node in merged for tool, ref in node.sources.items()
    }
    rows = {}
    for alert in alerts:
        node = by_source.get(f"{alert.tool}:{alert.node_ref}")
        rows[alert.key()] = {
            "alert_key": alert.key(),
            "tool": alert.tool,
            "kind": alert.kind,
            "node_id": node.id if node else None,
            "node_name": (node.name if node else None) or alert.node_name,
            "site": node.site if node else None,
            "province": node.province if node else None,
            "region": node.region if node else None,
            "severity": alert.severity,
            "message": (alert.message or "")[:1000],
            "opened_at": alert.since,
        }
    return rows


def known_tools(source_status: dict, collection: str) -> set[str]:
    """Outils dont le flux a été lu à ce cycle (frais ou dernier succès)."""
    return {
        tool for tool, streams in (source_status or {}).items()
        if (streams or {}).get(collection, {}).get("collected_at")
    }


# ---------------------------------------------------------------------------
# Planification (pure, testée sans base)
# ---------------------------------------------------------------------------
def plan_states(open_rows: list[dict], current: dict[str, dict], known: set[str],
                now: datetime) -> tuple[list[tuple], list[dict], list[int]]:
    """(périodes à clore [(id, fin)], périodes à ouvrir, périodes prolongées)."""
    closes: list[tuple] = []
    inserts: list[dict] = []
    touches: list[int] = []
    seen: set[str] = set()
    for row in open_rows:
        subject_id = row["subject_id"]
        seen.add(subject_id)
        observed = current.get(subject_id)
        gap = now - row["last_seen_at"] > MAX_GAP
        if gap:
            # Trou d'observation : la période s'arrête à sa dernière
            # observation ; le temps qui suit n'est ni disponible ni en panne.
            closes.append((row["id"], row["last_seen_at"] + INTERVAL))
            if observed is not None:
                inserts.append(observed)
        elif observed is None:
            tools = {t for t in (row.get("tools") or "").split(",") if t}
            if tools and tools <= known:
                closes.append((row["id"], now))   # vraiment disparu du parc
            # Sinon : son outil n'a pas répondu, on ne conclut rien.
        elif observed["state"] != row["state"]:
            closes.append((row["id"], now))
            inserts.append(observed)
        else:
            touches.append(row["id"])
    inserts.extend(row for subject_id, row in current.items() if subject_id not in seen)
    return closes, inserts, touches


def plan_alerts(open_rows: list[dict], current: dict[str, dict], known: set[str],
                now: datetime) -> tuple[list[tuple], list[dict], list[tuple]]:
    """(alertes à clore [(id, fin)], à ouvrir, à prolonger [(id, gravité)])."""
    closes: list[tuple] = []
    touches: list[tuple] = []
    seen: set[str] = set()
    for row in open_rows:
        seen.add(row["alert_key"])
        observed = current.get(row["alert_key"])
        if observed is not None:
            touches.append((row["id"], observed["severity"]))
        elif row["tool"] in known:
            closes.append((row["id"], now))
    inserts = [row for key, row in current.items() if key not in seen]
    return closes, inserts, touches


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
async def record(merged, alerts, maintenance_keys: set[str], source_status: dict,
                 now: datetime) -> dict:
    """Met le journal à jour pour ce cycle. Lève en cas d'erreur de base :
    l'appelant (cycle.py) l'intercepte."""
    if not config.HISTORY_ENABLED:
        return {}
    import psycopg
    from psycopg.rows import dict_row

    current_states = subjects(merged, maintenance_keys)
    current_alerts = alert_rows(alerts, merged)
    async with await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, row_factory=dict_row, connect_timeout=10
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, subject_id, state, last_seen_at, tools "
                "FROM hist_state WHERE ended_at IS NULL"
            )
            closes, inserts, touches = plan_states(
                await cur.fetchall(), current_states, known_tools(source_status, "nodes"), now
            )
            if closes:
                await cur.executemany(
                    "UPDATE hist_state SET ended_at = %s WHERE id = %s",
                    [(ended, row_id) for row_id, ended in closes],
                )
            if touches:
                await cur.execute(
                    "UPDATE hist_state SET last_seen_at = %s WHERE id = ANY(%s)",
                    (now, touches),
                )
            if inserts:
                await cur.executemany(
                    """
                    INSERT INTO hist_state (
                        subject_kind, subject_id, node_id, name, site, province, region,
                        tools, state, measured_state, started_at, last_seen_at
                    ) VALUES (
                        %(subject_kind)s, %(subject_id)s, %(node_id)s, %(name)s, %(site)s,
                        %(province)s, %(region)s, %(tools)s, %(state)s, %(measured_state)s,
                        %(now)s, %(now)s
                    )
                    ON CONFLICT (subject_id) WHERE ended_at IS NULL DO NOTHING
                    """,
                    [{**row, "now": now} for row in inserts],
                )
            state_counts = (len(closes), len(inserts))

            await cur.execute(
                "SELECT id, alert_key, tool FROM hist_alert WHERE closed_at IS NULL"
            )
            a_closes, a_inserts, a_touches = plan_alerts(
                await cur.fetchall(), current_alerts, known_tools(source_status, "alerts"), now
            )
            if a_closes:
                await cur.executemany(
                    "UPDATE hist_alert SET closed_at = %s WHERE id = %s",
                    [(ended, row_id) for row_id, ended in a_closes],
                )
            if a_touches:
                await cur.executemany(
                    "UPDATE hist_alert SET last_seen_at = %s, severity = %s WHERE id = %s",
                    [(now, severity, row_id) for row_id, severity in a_touches],
                )
            if a_inserts:
                await cur.executemany(
                    """
                    INSERT INTO hist_alert (
                        alert_key, tool, kind, node_id, node_name, site, province, region,
                        severity, message, opened_at, first_seen_at, last_seen_at
                    ) VALUES (
                        %(alert_key)s, %(tool)s, %(kind)s, %(node_id)s, %(node_name)s,
                        %(site)s, %(province)s, %(region)s, %(severity)s, %(message)s,
                        %(opened_at)s, %(now)s, %(now)s
                    )
                    ON CONFLICT (alert_key) WHERE closed_at IS NULL DO NOTHING
                    """,
                    [{**row, "now": now} for row in a_inserts],
                )
            await _purge(cur, now)
        await conn.commit()
    return {
        "states_closed": state_counts[0], "states_opened": state_counts[1],
        "alerts_closed": len(a_closes), "alerts_opened": len(a_inserts),
    }


async def _purge(cur, now: datetime) -> None:
    """Rétention : une fois par jour, retire ce qui est clos depuis plus de
    HISTORY_RETENTION_DAYS jours (0 = conserver indéfiniment)."""
    global _last_purge
    if config.HISTORY_RETENTION_DAYS <= 0 or _last_purge == now.date():
        return
    limit = now - timedelta(days=config.HISTORY_RETENTION_DAYS)
    await cur.execute("DELETE FROM hist_state WHERE ended_at < %s", (limit,))
    await cur.execute("DELETE FROM hist_alert WHERE closed_at < %s", (limit,))
    _last_purge = now.date()


# ---------------------------------------------------------------------------
# Recalcul des bilans journaliers (kpi_daily) depuis le journal
# ---------------------------------------------------------------------------
def effective_end(row: dict, now: datetime) -> datetime:
    """Fin d'une période : sa clôture, ou pour une période ouverte, l'instant
    présent — sauf trou d'observation, auquel cas sa dernière observation."""
    if row.get("ended_at"):
        return row["ended_at"]
    if now - row["last_seen_at"] <= MAX_GAP:
        return now
    return row["last_seen_at"] + INTERVAL


def _overlap(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    return max(0.0, (min(end, hi) - max(start, lo)).total_seconds())


def _places(row: dict) -> list[str | None]:
    """Localités d'agrégat, avec les mêmes clés que collector/rollup.py."""
    from .rollup import rollup_key

    places: list[str | None] = [None]
    if row.get("site"):
        places.append(row["site"])
    if row.get("region"):
        places.append(rollup_key("region", row["region"]))
    if row.get("province"):
        places.append(rollup_key("province", row["province"]))
    return places


def daily_rows(day: date, states: list[dict], alerts: list[dict], now: datetime) -> list[dict]:
    """Bilan d'une journée (UTC) calculé sur le journal, par localité.

    Même définition que le bilan cycle par cycle, pondérée par le temps :
    disponibilité = temps « en service » ÷ (temps observé − maintenance).
    """
    lo = datetime.combine(day, time.min, tzinfo=timezone.utc)
    hi = lo + timedelta(days=1)
    totals: dict = defaultdict(lambda: defaultdict(float))
    longest: dict = defaultdict(float)
    for row in states:
        if row["subject_kind"] != "node":
            continue
        seconds = _overlap(row["started_at"], effective_end(row, now), lo, hi)
        if not seconds:
            continue
        for place in _places(row):
            bucket = totals[place]
            bucket["observed"] += seconds
            bucket[row["state"]] += seconds
            longest[place] = max(longest[place], seconds)
    for row in alerts:
        if row["kind"] != "technical":
            continue
        end = row.get("closed_at") or max(row["last_seen_at"], row["opened_at"])
        seconds = _overlap(row["opened_at"], end, lo, hi)
        if not seconds:
            continue
        for place in _places(row):
            totals[place]["alerts"] += seconds
            if row["severity"] == "critical":
                totals[place]["critical"] += seconds
    rows = []
    for place, bucket in totals.items():
        if not bucket["observed"]:
            continue
        measured = bucket["observed"] - bucket["maintenance"]
        rows.append({
            "day": day,
            "site": place,
            "samples": int(round(longest[place] / INTERVAL.total_seconds())),
            "avg_nodes": round(bucket["observed"] / _DAY_S, 2),
            "avg_up": round(bucket["up"] / _DAY_S, 2),
            "avg_down": round(bucket["down"] / _DAY_S, 2),
            "avg_degraded": round(bucket["degraded"] / _DAY_S, 2),
            "avg_alerts": round(bucket["alerts"] / _DAY_S, 2),
            "avg_critical": round(bucket["critical"] / _DAY_S, 2),
            "fleet_availability_pct": (
                round(100.0 * bucket["up"] / measured, 2) if measured > 0 else None
            ),
        })
    return rows


async def rebuild_days(days: list[date], overwrite: bool = False) -> dict[date, int]:
    """Recalcule les bilans de ces jours depuis le journal. Sans `overwrite`,
    un jour qui a déjà son bilan n'est pas touché."""
    import psycopg
    from psycopg.rows import dict_row

    from .rollup import write_rows

    now = datetime.now(timezone.utc)
    written: dict[date, int] = {}
    async with await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, row_factory=dict_row, connect_timeout=10
    ) as conn:
        async with conn.cursor() as cur:
            for day in days:
                lo = datetime.combine(day, time.min, tzinfo=timezone.utc)
                hi = lo + timedelta(days=1)
                if not overwrite:
                    await cur.execute(
                        "SELECT 1 FROM kpi_daily WHERE day = %s AND site IS NULL", (day,)
                    )
                    if await cur.fetchone():
                        continue
                await cur.execute(
                    "SELECT * FROM hist_state WHERE subject_kind = 'node' "
                    "AND started_at < %s AND (ended_at IS NULL OR ended_at > %s)",
                    (hi, lo),
                )
                states = await cur.fetchall()
                await cur.execute(
                    "SELECT * FROM hist_alert WHERE kind = 'technical' "
                    "AND opened_at < %s AND (closed_at IS NULL OR closed_at > %s)",
                    (hi, lo),
                )
                rows = daily_rows(day, states, await cur.fetchall(), now)
                if rows:
                    if overwrite:
                        await cur.execute("DELETE FROM kpi_daily WHERE day = %s", (day,))
                        await conn.commit()
                    await write_rows(rows)
                    written[day] = len(rows)
    return written


async def backfill_missing(days_back: int = 7) -> dict[date, int]:
    """Bilans manquants des derniers jours (collecteur arrêté à l'heure du
    bilan, base indisponible) : recalculés depuis le journal."""
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=offset) for offset in range(days_back, 0, -1)]
    written = await rebuild_days(days, overwrite=False)
    if written:
        logger.info("Bilans journaliers rattrapés depuis le journal : %s",
                    ", ".join(day.isoformat() for day in written))
    return written


def _main() -> None:
    parser = argparse.ArgumentParser(prog="python -m collector.history")
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild-daily", help="recalculer kpi_daily sur une période")
    rebuild.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    rebuild.add_argument("--to", dest="end", type=date.fromisoformat,
                         help="dernier jour inclus (par défaut : hier)")
    rebuild.add_argument("--overwrite", action="store_true",
                         help="remplacer les bilans existants")
    fill = commands.add_parser("backfill", help="compléter les bilans manquants")
    fill.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=config.LOG_LEVEL, format="%(levelname)s %(message)s")

    if args.command == "backfill":
        written = asyncio.run(backfill_missing(args.days))
    else:
        end = args.end or (datetime.now(timezone.utc).date() - timedelta(days=1))
        days = [args.start + timedelta(days=n) for n in range((end - args.start).days + 1)]
        written = asyncio.run(rebuild_days(days, overwrite=args.overwrite))
    for day, count in sorted(written.items()):
        print(f"{day} : {count} ligne(s)")
    if not written:
        print("Aucun bilan écrit (jours déjà présents, ou pas d'historique sur la période).")


if __name__ == "__main__":
    _main()
