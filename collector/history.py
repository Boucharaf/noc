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
              ouverture (date de la source) à sa disparition, avec son
              premier acquittement ;
  hist_alert_event
              une ligne par changement de l'alerte : ouverture,
              acquittement, gravité, fermeture.

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
from .downtime import enabled_sources

logger = logging.getLogger(__name__)

# Au-delà de ce délai sans observation (trois cycles, 5 min au moins), la
# période est close.
MAX_GAP = timedelta(seconds=config.OBSERVATION_GAP_S)
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
        if not getattr(node, "observed", True):
            # Source arrêtée : personne ne l'observe. Le temps reste non
            # observé, au lieu de prolonger son dernier état connu.
            continue
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
            if tool in getattr(node, "frozen_sources", ()):
                continue
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
            # Source arrêtée : vue pour la dernière fois à sa dernière donnée.
            "seen_at": alert.last_observed_at if alert.frozen else None,
            "is_ack": bool(alert.acknowledged),
            "tool_ack_at": alert.acknowledged_at,
            # iTop : l'agent saisi sur le ticket en est le preneur en charge.
            "actor": (alert.details or {}).get("acknowledged_by")
            or (alert.details or {}).get("agent"),
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
    """(alertes à clore [(id, fin)], à ouvrir, à prolonger [(id, gravité, vue à)])."""
    closes: list[tuple] = []
    touches: list[tuple] = []
    seen: set[str] = set()
    for row in open_rows:
        seen.add(row["alert_key"])
        observed = current.get(row["alert_key"])
        if observed is not None:
            touches.append((row["id"], observed["severity"], observed.get("seen_at") or now))
        elif row["tool"] in known:
            closes.append((row["id"], now))
    inserts = [row for key, row in current.items() if key not in seen]
    return closes, inserts, touches


def acknowledgement(previous: bool | None, last_seen_at: datetime | None,
                    opened_at: datetime, observed: dict,
                    now: datetime) -> tuple[datetime | None, str]:
    """(date, source) d'un acquittement vu à ce cycle.

    Sans date crédible de l'outil, l'instant du cycle n'est retenu que si le
    cycle précédent a vu l'alerte NON acquittée. Sinon (première observation,
    collecteur arrêté entre-temps) la date est inconnue, et le reste : une
    date inventée fausserait le MTTA.
    """
    at = observed.get("tool_ack_at")
    if at is not None and opened_at <= at <= now + INTERVAL:
        return at, "tool"
    if previous is False and last_seen_at is not None and now - last_seen_at <= MAX_GAP:
        return now, "observed"
    return None, "undated"


def plan_alert_changes(open_rows: list[dict], current: dict[str, dict],
                       now: datetime) -> tuple[list[dict], list[dict]]:
    """(mises à jour de hist_alert, événements) des alertes toujours ouvertes."""
    updates: list[dict] = []
    events: list[dict] = []
    for row in open_rows:
        observed = current.get(row["alert_key"])
        if observed is None:
            continue
        if observed["severity"] != row["severity"]:
            events.append(_event(row["id"], "severity", now, "observed",
                                 row["severity"], observed["severity"]))
        was, is_ack = row["acknowledged"], observed["is_ack"]
        first_at, by, source = row["acknowledged_at"], row["acknowledged_by"], row["ack_source"]
        if is_ack and was is not True:
            at, how = acknowledgement(was, row["last_seen_at"], row["opened_at"], observed, now)
            events.append(_event(row["id"], "acknowledged", at or now, how,
                                 actor=observed["actor"]))
            if source is None:   # premier acquittement : seul celui-ci est gardé
                first_at, by, source = at, observed["actor"], how
        elif was is True and not is_ack:
            events.append(_event(row["id"], "unacknowledged", now, "observed"))
        if was is not is_ack:
            updates.append({
                "id": row["id"], "acknowledged": is_ack, "acknowledged_at": first_at,
                "acknowledged_by": by, "ack_source": source,
            })
    return updates, events


def opening_events(alert_id: int, row: dict, now: datetime) -> list[dict]:
    """Ouverture (avec la gravité initiale) et acquittement déjà présent."""
    events = [_event(alert_id, "opened", row["opened_at"], "tool", None, row["severity"])]
    if row["acknowledged"]:
        events.append(_event(alert_id, "acknowledged", row["acknowledged_at"] or now,
                             row["ack_source"], actor=row["acknowledged_by"]))
    return events


def _event(alert_id: int, event: str, at: datetime, source: str,
           from_value: str | None = None, to_value: str | None = None,
           actor: str | None = None) -> dict:
    return {"alert_id": alert_id, "event": event, "at": at, "source": source,
            "from_value": from_value, "to_value": to_value, "actor": actor}


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
                "SELECT id, alert_key, tool, severity, opened_at, last_seen_at, acknowledged, "
                "acknowledged_at, acknowledged_by, ack_source "
                "FROM hist_alert WHERE closed_at IS NULL"
            )
            open_alerts = await cur.fetchall()
            a_closes, a_inserts, a_touches = plan_alerts(
                open_alerts, current_alerts, known_tools(source_status, "alerts"), now
            )
            a_updates, events = plan_alert_changes(open_alerts, current_alerts, now)
            events += [_event(row_id, "closed", ended, "observed") for row_id, ended in a_closes]
            if a_closes:
                await cur.executemany(
                    "UPDATE hist_alert SET closed_at = %s WHERE id = %s",
                    [(ended, row_id) for row_id, ended in a_closes],
                )
            if a_touches:
                await cur.executemany(
                    "UPDATE hist_alert SET last_seen_at = %s, severity = %s WHERE id = %s",
                    [(seen, severity, row_id) for row_id, severity, seen in a_touches],
                )
            if a_updates:
                await cur.executemany(
                    "UPDATE hist_alert SET acknowledged = %(acknowledged)s, "
                    "acknowledged_at = %(acknowledged_at)s, "
                    "acknowledged_by = %(acknowledged_by)s, ack_source = %(ack_source)s "
                    "WHERE id = %(id)s",
                    a_updates,
                )
            if a_inserts:
                new_rows = {}
                for row in a_inserts:
                    at, how = (
                        acknowledgement(None, None, row["opened_at"], row, now)
                        if row["is_ack"] else (None, None)
                    )
                    new_rows[row["alert_key"]] = {
                        **row, "now": now, "seen": row.get("seen_at") or now,
                        "acknowledged": row["is_ack"],
                        "acknowledged_at": at, "ack_source": how,
                        "acknowledged_by": row["actor"] if row["is_ack"] else None,
                    }
                await cur.executemany(
                    """
                    INSERT INTO hist_alert (
                        alert_key, tool, kind, node_id, node_name, site, province, region,
                        severity, message, opened_at, first_seen_at, last_seen_at,
                        acknowledged, acknowledged_at, acknowledged_by, ack_source
                    ) VALUES (
                        %(alert_key)s, %(tool)s, %(kind)s, %(node_id)s, %(node_name)s,
                        %(site)s, %(province)s, %(region)s, %(severity)s, %(message)s,
                        %(opened_at)s, %(now)s, %(seen)s,
                        %(acknowledged)s, %(acknowledged_at)s, %(acknowledged_by)s,
                        %(ack_source)s
                    )
                    ON CONFLICT (alert_key) WHERE closed_at IS NULL DO NOTHING
                    """,
                    list(new_rows.values()),
                )
                # first_seen_at = now : seulement les lignes insérées ici.
                await cur.execute(
                    "SELECT id, alert_key FROM hist_alert WHERE alert_key = ANY(%s) "
                    "AND closed_at IS NULL AND first_seen_at = %s",
                    (list(new_rows), now),
                )
                for inserted in await cur.fetchall():
                    events += opening_events(
                        inserted["id"], new_rows[inserted["alert_key"]], now
                    )
            if events:
                await cur.executemany(
                    "INSERT INTO hist_alert_event "
                    "(alert_id, event, at, from_value, to_value, actor, source) VALUES "
                    "(%(alert_id)s, %(event)s, %(at)s, %(from_value)s, %(to_value)s, "
                    "%(actor)s, %(source)s)",
                    events,
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
    disponibilité = temps où il répond ÷ temps SUPERVISÉ (en service,
    dégradé, en panne) : maintenance et temps « inconnu » (non supervisé)
    n'y entrent pas (AM-29). « Disponible » = l'équipement RÉPOND (KPI-01) :
    en service ou dégradé.
    """
    lo = datetime.combine(day, time.min, tzinfo=timezone.utc)
    hi = lo + timedelta(days=1)
    totals: dict = defaultdict(lambda: defaultdict(float))
    # Temps observé par sujet : le plus long d'un lieu est le temps pendant
    # lequel ce lieu a été observé, et donc la base de ses moyennes.
    seen: dict = defaultdict(lambda: defaultdict(float))
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
            seen[place][row.get("subject_id")] += seconds
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
        measured = bucket["up"] + bucket["degraded"] + bucket["down"]
        covered = min(_DAY_S, max(seen[place].values()))
        rows.append({
            "day": day,
            "site": place,
            "samples": int(round(covered / INTERVAL.total_seconds())),
            "avg_nodes": round(bucket["observed"] / covered, 2),
            "avg_up": round(bucket["up"] / covered, 2),
            "avg_down": round(bucket["down"] / covered, 2),
            "avg_degraded": round(bucket["degraded"] / covered, 2),
            # Une alerte reste ouverte pendant un arrêt du collecteur : jour plein.
            "avg_alerts": round(bucket["alerts"] / _DAY_S, 2),
            "avg_critical": round(bucket["critical"] / _DAY_S, 2),
            "fleet_availability_pct": (
                round(100.0 * (bucket["up"] + bucket["degraded"]) / measured, 2)
                if measured > 0 else None
            ),
            "responding_s": round(bucket["up"] + bucket["degraded"]),
            "supervised_s": round(measured),
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
                if enabled_sources():
                    states = await _with_source_downtimes(cur, states, lo, hi, now)
                # (Un jour antérieur au journal du NOC n'a de bilan que si une
                # source maître en connaît les équipements.)
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


async def _with_source_downtimes(cur, states, lo, hi, now):
    """Périodes corrigées par les journaux de pannes des outils (NetXMS,
    Centreon) déjà synchronisés au moins une fois (collector/downtime.py)."""
    from . import downtime

    await cur.execute(
        "SELECT source, COALESCE(horizon_at, synced_at) AS horizon_at, complete_since "
        "FROM hist_source_sync "
        "WHERE source = ANY(%s)",
        (list(downtime.enabled_sources()),),
    )
    synced = await cur.fetchall()
    active = {row["source"] for row in synced}
    if not active:
        return states
    horizons = {row["source"]: (row["horizon_at"], row["complete_since"]) for row in synced}
    # Équipements supervisés par leur source ce jour-là, même jamais observés
    # par le NOC : leur journée est reconstituée depuis la source.
    await cur.execute(
        "SELECT * FROM hist_source_object WHERE source = ANY(%s) AND managed "
        "AND supervised_since < %s",
        (list(active), hi),
    )
    objects = await cur.fetchall()
    await cur.execute(
        "SELECT source, node_id, started_at, ended_at FROM hist_downtime "
        "WHERE source = ANY(%s) AND started_at < %s AND (ended_at IS NULL OR ended_at > %s)",
        (list(active), hi, lo - MAX_GAP),
    )
    return downtime.apply_to_states(
        states, await cur.fetchall(), now, effective_end, active, objects, horizons
    )


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


async def purge_frozen(apply: bool = False) -> list[tuple]:
    """Retire du journal les périodes observées APRÈS la dernière donnée d'une
    source arrêtée, sur les équipements qu'elle est seule à superviser : elles
    recopiaient un état figé. Rien n'est perdu, les lignes sont déplacées dans
    `hist_state_frozen`. Recalculer ensuite les bilans (rebuild-daily).
    """
    import psycopg

    from integrations.config import build_all_clients

    from .cycle import _frozen_since

    result = []
    clients = build_all_clients()
    try:
        horizons = {name: await _frozen_since(name, client) for name, client in clients.items()}
    finally:
        for client in clients.values():
            await client.aclose()
    async with await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, connect_timeout=10
    ) as conn:
        async with conn.cursor() as cur:
            if apply:
                await cur.execute(
                    "CREATE TABLE IF NOT EXISTS hist_state_frozen (LIKE hist_state)"
                )
            for tool, horizon in horizons.items():
                if horizon is None:
                    continue
                where = "tools = %s AND started_at > %s"
                if apply:
                    await cur.execute(
                        f"WITH gone AS (DELETE FROM hist_state WHERE {where} RETURNING *) "
                        "INSERT INTO hist_state_frozen SELECT * FROM gone", (tool, horizon),
                    )
                    count = cur.rowcount
                else:
                    await cur.execute(
                        f"SELECT count(*) FROM hist_state WHERE {where}", (tool, horizon)
                    )
                    count = (await cur.fetchone())[0]
                result.append((tool, horizon, count))
        await conn.commit()
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(prog="python -m collector.history")
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild-daily", help="recalculer kpi_daily sur une période")
    rebuild.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    rebuild.add_argument("--to", dest="end", type=date.fromisoformat,
                         help="dernier jour inclus (par défaut : hier)")
    rebuild.add_argument("--overwrite", action="store_true",
                         help="remplacer les bilans existants")
    frozen = commands.add_parser(
        "purge-frozen", help="retirer les observations faites sur une source arrêtée"
    )
    frozen.add_argument("--apply", action="store_true", help="sans elle : compter seulement")
    fill = commands.add_parser("backfill", help="compléter les bilans manquants")
    fill.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=config.LOG_LEVEL, format="%(levelname)s %(message)s")

    if args.command == "purge-frozen":
        for tool, horizon, count in asyncio.run(purge_frozen(args.apply)):
            print(f"{tool} (arrêté au {horizon:%d/%m/%Y %H:%M}) : {count} période(s) "
                  + ("archivée(s)" if args.apply else "à archiver"))
        return
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
