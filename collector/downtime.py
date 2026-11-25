"""
Pannes enregistrées par les outils : la source fait foi.

Deux sources, par ordre de priorité : NetXMS (table `downtime_log`) et
Centreon (changements d'état HARD des hôtes, lus par l'API REST v2 — ou par
l'export du journal en local). Ce qui suit est écrit pour NetXMS ; la même
règle s'applique à Centreon (CENTREON_DOWNTIME_ENABLED), qui n'est retenu que
pour les équipements que NetXMS ne supervise pas.

POURQUOI. Le journal du NOC (collector/history.py) déduit les pannes de ce
qu'il observe toutes les COLLECT_INTERVAL_S secondes : une panne y est datée
à un cycle près, une coupure plus courte qu'un cycle peut passer inaperçue,
et rien n'est su pendant un arrêt du collecteur. NetXMS, lui, enregistre
chaque indisponibilité d'un équipement, à la seconde, dans `downtime_log`.
L'agence demande que la disponibilité des équipements NetXMS en soit tirée.

RÈGLE, pour un équipement que NetXMS supervise (« netxms » parmi ses outils) :
  * NetXMS est la SOURCE MAÎTRE du « en panne / pas en panne » : en panne
    exactement pendant les périodes de `downtime_log`, et en service le reste
    du temps supervisé — même si un autre outil le voyait en panne ;
  * le NOC reste maître de ce que NetXMS ne dit pas : maintenance planifiée,
    temps inconnu ou non supervisé (jamais comptés), état dégradé ;
  * les trous d'observation du NOC (collecteur arrêté) ENTRE deux
    observations sont comblés par la source : NetXMS supervisait, son
    journal dit s'il y a eu panne. Avant la première et après la dernière
    observation du NOC, rien n'est inventé ;
  * la source ne fait foi que jusqu'à son HORIZON (dernière donnée connue) :
    au-delà — dump, base figée — elle ne sait rien, et les observations du
    NOC reprennent la main ;
  * les écarts entre les deux sont publiés (rapprochement) : temps vu en
    panne par le NOC mais absent du journal NetXMS, et l'inverse.

Le calcul (disponibilité, épisodes de panne, MTTR, MTBF) reste celui du NOC :
`overlay` rend des périodes au format du journal, que summarise() et
daily_rows() traitent sans rien savoir de leur origine.

ACTIVATION : NETXMS_DOWNTIME_ENABLED=true, et une connexion en lecture seule
à la base NetXMS (NETXMS_DOWNTIME_DSN, ou NETXMS_API_URL si c'est déjà une
URL postgresql://). Voir database/netxms_readonly_role.sql pour les droits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import config

logger = logging.getLogger(__name__)

SOURCE = "netxms"
SOURCE_LABEL = "netxms_downtime_log"
# Sources maîtres possibles, par ordre de priorité : un équipement vu par
# NetXMS ET Centreon prend les pannes de NetXMS (une seule source par
# équipement, jamais deux pannes comptées pour la même coupure).
SOURCES = ("netxms", "centreon", "zabbix", "nagios")
LABELS = {
    "netxms": "netxms_downtime_log",      # table downtime_log, à la seconde
    "centreon": "centreon_host_events",   # changements d'état HARD des hôtes
    "zabbix": "zabbix_trigger_events",    # déclencheurs de disponibilité
    "nagios": "nagios_host_events",       # changements d'état HARD des hôtes
}
# Au-delà de ce délai sans synchronisation réussie, le backend revient aux
# observations du NOC : un journal source figé fausserait les chiffres.
STALE_AFTER = timedelta(hours=6)
# Relecture des pannes closes récemment : une panne close après la dernière
# synchronisation doit voir sa fin enregistrée.
_REREAD = timedelta(days=2)
_MEASURED = ("up", "down", "degraded")
_last_sync: dict[str, datetime] = {}


class Period(dict):
    """Période au format du journal, lisible en `row["x"]` comme en `row.x`
    (le collecteur manipule des dictionnaires, le backend des objets)."""

    __getattr__ = dict.get


_FIELDS = ("subject_kind", "subject_id", "node_id", "name", "site", "province",
           "region", "tools", "state", "measured_state", "started_at", "ended_at",
           "last_seen_at")


def as_period(row) -> Period:
    if isinstance(row, dict):
        return Period(row)
    return Period({name: getattr(row, name, None) for name in _FIELDS})


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def node_tools(periods) -> set[str]:
    tools: set[str] = set()
    for row in periods:
        value = row.get("tools") if isinstance(row, dict) else getattr(row, "tools", None)
        tools.update(item for item in (value or "").split(",") if item)
    return tools


def master_source(periods, active) -> str | None:
    """Source maître de l'équipement parmi les sources actives, ou None."""
    tools = node_tools(periods)
    return next((source for source in SOURCES if source in active and source in tools), None)


def uses_source(periods) -> bool:
    """L'équipement est-il supervisé par NetXMS ?"""
    return master_source(periods, {SOURCE}) is not None


def merge_intervals(downtimes, now: datetime) -> list[tuple[datetime, datetime]]:
    """Pannes triées et fusionnées ; une panne en cours (fin absente) dure
    jusqu'à maintenant. Plusieurs étiquettes (tags) peuvent se chevaucher."""
    spans = sorted(
        (_aware(start), _aware(end) or now) for start, end in downtimes if start is not None
    )
    merged: list[list[datetime]] = []
    for start, end in spans:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _split(start: datetime, end: datetime, downs) -> list[tuple]:
    """Découpe [start, end) en morceaux (début, fin, en panne ?, début RÉEL
    de la panne selon la source — antérieur au morceau si la panne avait
    commencé avant)."""
    pieces = []
    cursor = start
    for down_start, down_end in downs:
        if down_end <= cursor or down_start >= end:
            continue
        if down_start > cursor:
            pieces.append((cursor, down_start, False, None))
        pieces.append((max(cursor, down_start), min(end, down_end), True, down_start))
        cursor = min(end, down_end)
        if cursor >= end:
            break
    if cursor < end:
        pieces.append((cursor, end, False, None))
    return pieces


def overlay(periods, downtimes, now: datetime, end_of, supervised=None,
            base=None, horizon=None) -> tuple[list[Period], dict]:
    """Périodes d'un équipement corrigées par le journal de pannes NetXMS.

    `periods` : périodes du journal du NOC pour UN sujet (objets ou dicts) ;
    `downtimes` : [(début, fin ou None)] lus dans downtime_log ;
    `end_of(row)` : fin effective d'une période (règle du journal) ;
    `supervised` : (depuis, horizon) — fenêtre où la SOURCE supervisait
    l'équipement et sait ce qui s'est passé (NetXMS : date de création de
    l'objet, dernière activité de sa base). Avant la première observation du
    NOC, cette fenêtre est reconstituée depuis la source seule (`history_s`) ;
    `base` : champs du sujet quand le NOC ne l'a jamais observé ;
    `horizon` : dernière donnée de la source. Après, ses pannes ne
    s'appliquent plus et ses trous ne sont plus comblés.

    Rend (périodes, rapprochement). Le rapprochement donne, en secondes, le
    temps vu en panne par le NOC hors du journal NetXMS (`noc_only_down_s`),
    et le temps en panne selon NetXMS que le NOC ne voyait pas
    (`source_only_down_s`) ou n'observait pas (`filled_s`).
    """
    rows = sorted((as_period(p) for p in periods), key=lambda p: _aware(p["started_at"]))
    downs = merge_intervals(downtimes, now)
    report = {"noc_only_down_s": 0.0, "source_only_down_s": 0.0, "filled_s": 0.0,
              "source_down_s": 0.0, "history_s": 0.0}
    segments: list[tuple[datetime, datetime, str, Period, bool]] = []
    since, until = (_aware(supervised[0]), _aware(supervised[1])) if supervised else (None, None)
    known_until = _aware(horizon) if horizon is not None else until
    # Panne encore ouverte à l'horizon : si le NOC voit l'équipement en panne
    # dès sa première observation ensuite, c'est la MÊME panne.
    open_since = next(
        (start for start, end in downs
         if known_until is not None and start < known_until < end),
        None,
    )
    if since is not None and until is not None:
        # Historique de la source AVANT la première observation du NOC (ou
        # sans observation du tout) : de la mise en supervision à l'horizon de
        # la source. Le temps entre l'horizon et la première observation du
        # NOC reste non observé : personne ne sait ce qui s'y est passé.
        first = _aware(rows[0]["started_at"]) if rows else None
        lead_end = min(first, until) if first else until
        if since < lead_end:
            subject = as_period(rows[0] if rows else (base or {}))
            segments.append((since, lead_end, "history", subject, False))
    previous_end: datetime | None = None
    for row in rows:
        start, end = _aware(row["started_at"]), _aware(end_of(row))
        if end <= start:
            continue
        if previous_end is not None and start > previous_end:
            # Trou d'observation du NOC : la source le couvre — jusqu'à son
            # horizon seulement, au-delà elle ne sait rien non plus.
            gap_end = start if known_until is None else min(start, known_until)
            if gap_end > previous_end:
                segments.append((previous_end, gap_end, "filled", segments[-1][3], False))
        is_open = row.get("ended_at") is None and end >= now
        if known_until is not None and start < known_until < end:
            segments.append((start, known_until, row["state"], row, False))
            segments.append((known_until, end, row["state"], row, is_open))
        else:
            segments.append((start, end, row["state"], row, is_open))
        previous_end = max(previous_end, end) if previous_end else end

    out: list[Period] = []

    def emit(start, end, state, base, is_open, measured, down_since=None):
        # Morceaux contigus de même état : une seule période (la localité
        # retenue est celle du premier).
        if out and out[-1]["state"] == state and out[-1]["ended_at"] == start:
            out[-1]["ended_at"] = end
            out[-1]["last_seen_at"] = end
        else:
            out.append(Period({**base, "state": state,
                               "measured_state": measured, "started_at": start,
                               "ended_at": end, "last_seen_at": end,
                               # Panne commencée AVANT ce morceau (selon la
                               # source) : son vrai début, pour ne pas la
                               # compter comme une panne nouvelle de la période.
                               "down_since": down_since}))
        if is_open:
            out[-1]["ended_at"] = None
            out[-1]["last_seen_at"] = now

    for index, (start, end, state, row_base, is_open) in enumerate(segments):
        last = index == len(segments) - 1
        if state not in _MEASURED and state not in ("filled", "history"):
            # Maintenance, inconnu, silencieux : le NOC fait foi.
            emit(start, end, state, row_base, is_open and last, row_base.get("measured_state"))
            continue
        if known_until is not None and start >= known_until:
            # La source ne sait plus rien : le NOC fait foi.
            if state in ("up", "degraded"):
                open_since = None
            emit(start, end, state, row_base, is_open and last, row_base.get("measured_state"),
                 open_since if state == "down" else None)
            continue
        pieces = _split(start, end, downs)
        for number, (p_start, p_end, in_down, down_start) in enumerate(pieces):
            seconds = (p_end - p_start).total_seconds()
            if state in ("filled", "history"):
                report[f"{state}_s"] += seconds
                new_state = "down" if in_down else "up"
            elif in_down:
                new_state = "down"
                if state != "down":
                    report["source_only_down_s"] += seconds
            else:
                new_state = "degraded" if state == "degraded" else "up"
                if state == "down":
                    report["noc_only_down_s"] += seconds
            if in_down:
                report["source_down_s"] += seconds
            emit(p_start, p_end, new_state, row_base, is_open and last and number == len(pieces) - 1,
                 state if state not in ("filled", "history") else None,
                 down_start if in_down and down_start < p_start else None)
    return out, {key: round(value) for key, value in report.items()}


def apply_to_states(states: list[dict], downtime_rows: list[dict], now: datetime,
                    end_of, active=frozenset({SOURCE}), objects=None,
                    horizons=None) -> list[Period]:
    """Corrige toutes les périodes d'équipement d'un lot (bilans journaliers).

    `downtime_rows` : lignes de hist_downtime (source, node_id, started_at,
    ended_at) ; `end_of(row, now)` : fin effective d'une période
    (history.effective_end) ; `active` : sources synchronisées ;
    `objects` : lignes de hist_source_object (fenêtres de supervision) et
    `horizons` : {source: horizon} — les équipements que la source
    supervisait sont reconstitués même si le NOC ne les a jamais observés.
    Les liens et les équipements sans source maître passent tels quels."""
    windows = source_windows(objects or [], horizons or {})
    by_node: dict[tuple[str, str], list] = {}
    for row in downtime_rows:
        key = (row.get("source") or SOURCE, row["node_id"])
        by_node.setdefault(key, []).append((row["started_at"], row["ended_at"]))
    grouped: dict[str, list] = {}
    others: list[Period] = []
    for row in states:
        if row["subject_kind"] == "node":
            grouped.setdefault(row["subject_id"], []).append(row)
        else:
            others.append(as_period(row))
    for (source, node_id), (_window, subject) in windows.items():
        if source in active and node_id not in grouped:
            grouped[node_id] = []
    result = others
    for subject_id, rows in grouped.items():
        source = master_source(rows or _subjects(windows, subject_id), active)
        if source:
            window, subject = windows.get((source, subject_id), (None, None))
            corrected, _report = overlay(
                rows, by_node.get((source, subject_id), []), now, lambda row: end_of(row, now),
                supervised=window, base=subject, horizon=_horizon(horizons, source),
            )
            result.extend(corrected)
        else:
            result.extend(as_period(row) for row in rows)
    return result


def _horizon(horizons, source: str):
    bounds = (horizons or {}).get(source)
    return bounds[0] if isinstance(bounds, tuple) else bounds


def source_windows(objects, horizons: dict) -> dict:
    """{(source, node_id): ((depuis, horizon), sujet)} pour les équipements
    supervisés par leur source. Un équipement non géré n'a pas de fenêtre."""
    windows = {}
    for obj in objects:
        get = obj.get if isinstance(obj, dict) else (lambda name, o=obj: getattr(o, name, None))
        bounds = horizons.get(get("source"))
        # `horizons` : {source: horizon} ou {source: (horizon, complet depuis)}.
        horizon, complete_since = bounds if isinstance(bounds, tuple) else (bounds, None)
        since = get("supervised_since")
        if not get("managed") or since is None or horizon is None:
            continue
        if complete_since is not None:
            # Avant, le journal de la source n'est plus complet (rétention) :
            # rien n'est reconstitué, ce temps reste non observé.
            since = max(_aware(since), _aware(complete_since))
            if since >= _aware(horizon):
                continue
        subject = Period({
            "subject_kind": "node", "subject_id": get("node_id"), "node_id": get("node_id"),
            "name": get("name"), "site": get("site"), "province": get("province"),
            "region": get("region"), "tools": get("tools"), "state": "up",
            "measured_state": None,
        })
        windows[(get("source"), get("node_id"))] = ((_aware(since), _aware(horizon)), subject)
    return windows


def _subjects(windows: dict, node_id: str) -> list:
    return [subject for (_source, node), (_w, subject) in windows.items() if node == node_id]


def reconciliation_minutes(report: dict, source: str = SOURCE) -> dict:
    return {
        "source": LABELS.get(source, source),
        "noc_only_down_minutes": round(report.get("noc_only_down_s", 0) / 60, 1),
        "source_only_down_minutes": round(report.get("source_only_down_s", 0) / 60, 1),
        "filled_minutes": round(report.get("filled_s", 0) / 60, 1),
        # Temps reconstitué depuis la source seule, avant que le NOC observe.
        "history_minutes": round(report.get("history_s", 0) / 60, 1),
    }


# ---------------------------------------------------------------------------
# Synchronisation : journaux des outils → hist_downtime (NOC)
# ---------------------------------------------------------------------------
def enabled_sources() -> tuple[str, ...]:
    flags = {
        "netxms": config.NETXMS_DOWNTIME_ENABLED,
        "centreon": config.CENTREON_DOWNTIME_ENABLED,
        "zabbix": config.ZABBIX_DOWNTIME_ENABLED,
        "nagios": config.NAGIOS_DOWNTIME_ENABLED,
    }
    return tuple(source for source in SOURCES if flags[source])


def _interval(source: str) -> int:
    return {
        "netxms": config.NETXMS_DOWNTIME_SYNC_S,
        "zabbix": config.ZABBIX_DOWNTIME_SYNC_S,
    }.get(source, config.CENTREON_DOWNTIME_SYNC_S)


def _backfill_days(source: str) -> int:
    return {
        "netxms": config.NETXMS_DOWNTIME_BACKFILL_DAYS,
        "zabbix": config.ZABBIX_DOWNTIME_BACKFILL_DAYS,
    }.get(source, config.CENTREON_DOWNTIME_BACKFILL_DAYS)


def source_client(source: str = SOURCE):
    """Connecteur qui sait lire le journal de pannes de cette source, ou None."""
    if source not in enabled_sources():
        return None
    if source != "netxms":
        # Le connecteur déjà configuré (Centreon : API REST v2 ou export du
        # journal ; Zabbix : API JSON-RPC ; Nagios : CGI ou Livestatus) :
        # aucun accès supplémentaire n'est demandé.
        from integrations.config import build_client

        try:
            client = build_client(source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s non configuré : pannes non lues (%s)", source, exc)
            return None
        return client if hasattr(client, "fetch_downtimes") else None
    dsn = config.NETXMS_DOWNTIME_DSN
    if not dsn.startswith(("postgresql://", "postgres://")):
        logger.warning(
            "NETXMS_DOWNTIME_ENABLED=true mais aucune URL postgresql:// pour la base "
            "NetXMS (NETXMS_DOWNTIME_DSN) : journal des pannes NetXMS non lu"
        )
        return None
    from integrations.netxms_db import NetXMSDatabaseClient

    return NetXMSDatabaseClient(
        dsn, config.NETXMS_DOWNTIME_USER, config.NETXMS_DOWNTIME_PASSWORD,
        timeout_s=config.NETXMS_DOWNTIME_TIMEOUT_S,
    )


def rows_to_store(records: list[dict], merged, source: str = SOURCE) -> list[dict]:
    """Rattache chaque panne à l'équipement du NOC qui porte cet objet.

    Une fin sans début (`start` None : la panne avait commencé avant la
    fenêtre relue) n'est pas une ligne : voir closures()."""
    by_ref = {
        str(ref): node for node in merged for tool, ref in (node.sources or {}).items()
        if tool == source
    }
    tags = config.NETXMS_DOWNTIME_TAGS if source == "netxms" else frozenset()
    rows = []
    for record in records:
        if record.get("start") is None:
            continue
        if tags and (record.get("tag") or "") not in tags:
            continue
        ref = str(record["object_id"])
        node = by_ref.get(ref)
        rows.append({
            "source": source,
            "object_ref": ref,
            "node_id": node.id if node else f"{source}:{ref}",
            "name": node.name if node else None,
            "tag": record.get("tag") or "",
            "started_at": record["start"],
            "ended_at": record.get("end"),
        })
    return rows


def objects_to_store(objects: list[dict], merged, source: str = SOURCE) -> list[dict]:
    """Fenêtres de supervision rattachées à l'équipement du NOC. Un objet que
    le NOC ne connaît pas (aucun équipement fusionné) est écarté : on ne sait
    ni le nommer ni le situer."""
    by_ref = {
        str(ref): node for node in merged for tool, ref in (node.sources or {}).items()
        if tool == source
    }
    rows = []
    for obj in objects:
        node = by_ref.get(str(obj["object_id"]))
        if node is None:
            continue
        rows.append({
            "source": source,
            "object_ref": str(obj["object_id"]),
            "node_id": node.id,
            "name": node.name,
            "site": node.site,
            "province": node.province,
            "region": node.region,
            "tools": ",".join(sorted(node.sources)),
            "supervised_since": obj.get("since"),
            "managed": bool(obj.get("managed", True)),
        })
    return rows


def closures(records: list[dict]) -> list[tuple[str, str, datetime]]:
    """Fins de panne dont le début précède la fenêtre relue (sources à
    événements : Centreon, Zabbix, Nagios). Elles closent la panne restée
    ouverte de même objet et de même étiquette."""
    return [
        (str(record["object_id"]), record.get("tag") or "", record["end"])
        for record in records
        if record.get("start") is None and record.get("end") is not None
    ]


async def sync(merged, now: datetime, client=None, source: str | None = None) -> dict:
    """Recopie les pannes récentes de chaque source activée dans
    hist_downtime. Une source en échec n'empêche pas les autres."""
    if source is not None:
        return await _sync_one(source, merged, now, client)
    result: dict = {}
    for name in enabled_sources():
        try:
            result[name] = await _sync_one(name, merged, now)
        except Exception:  # noqa: BLE001
            logger.exception("Pannes %s non synchronisées", name)
    return result


async def _sync_one(source: str, merged, now: datetime, client=None) -> dict:
    """Au plus une fois par intervalle de la source ; lève en cas d'erreur."""
    previous_run = _last_sync.get(source)
    if previous_run and now - previous_run < timedelta(seconds=_interval(source)):
        return {}
    client = client or source_client(source)
    if client is None:
        return {}
    import psycopg
    from psycopg.rows import dict_row

    async with await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, row_factory=dict_row, connect_timeout=10
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT synced_at FROM hist_source_sync WHERE source = %s", (source,)
            )
            previous = await cur.fetchone()
            since = (
                previous["synced_at"] - _REREAD if previous
                else now - timedelta(days=_backfill_days(source))
            )
            records = await client.fetch_downtimes(since)
            rows = rows_to_store(records, merged, source)
            ends = closures(records)
            if ends:
                await cur.executemany(
                    "UPDATE hist_downtime SET ended_at = %s, imported_at = now() "
                    "WHERE source = %s AND object_ref = %s AND tag = %s "
                    "AND ended_at IS NULL AND started_at < %s",
                    [(end, source, ref, tag, end) for ref, tag, end in ends],
                )
            if rows:
                await cur.executemany(
                    """
                    INSERT INTO hist_downtime (
                        source, object_ref, node_id, name, tag, started_at, ended_at
                    ) VALUES (
                        %(source)s, %(object_ref)s, %(node_id)s, %(name)s, %(tag)s,
                        %(started_at)s, %(ended_at)s
                    )
                    ON CONFLICT (source, object_ref, tag, started_at) DO UPDATE SET
                        ended_at = EXCLUDED.ended_at,
                        node_id = EXCLUDED.node_id,
                        name = COALESCE(EXCLUDED.name, hist_downtime.name),
                        imported_at = now()
                    """,
                    rows,
                )
            horizon = complete_since = None
            if hasattr(client, "fetch_supervision"):
                supervision = await client.fetch_supervision()
                horizon = supervision.get("horizon")
                complete_since = supervision.get("complete_since")
                objects = objects_to_store(supervision.get("objects") or [], merged, source)
                if objects:
                    await cur.executemany(
                        """
                        INSERT INTO hist_source_object (
                            source, object_ref, node_id, name, site, province, region,
                            tools, supervised_since, managed, updated_at
                        ) VALUES (
                            %(source)s, %(object_ref)s, %(node_id)s, %(name)s, %(site)s,
                            %(province)s, %(region)s, %(tools)s, %(supervised_since)s,
                            %(managed)s, now()
                        )
                        ON CONFLICT (source, object_ref) DO UPDATE SET
                            node_id = EXCLUDED.node_id,
                            name = COALESCE(EXCLUDED.name, hist_source_object.name),
                            site = COALESCE(EXCLUDED.site, hist_source_object.site),
                            province = COALESCE(EXCLUDED.province, hist_source_object.province),
                            region = COALESCE(EXCLUDED.region, hist_source_object.region),
                            tools = COALESCE(EXCLUDED.tools, hist_source_object.tools),
                            supervised_since = EXCLUDED.supervised_since,
                            managed = EXCLUDED.managed,
                            updated_at = now()
                        """,
                        objects,
                    )
            await cur.execute(
                """
                INSERT INTO hist_source_sync (
                    source, synced_at, rows_read, horizon_at, complete_since
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source) DO UPDATE SET
                    synced_at = EXCLUDED.synced_at, rows_read = EXCLUDED.rows_read,
                    horizon_at = EXCLUDED.horizon_at,
                    -- Le NOC garde ce qu'il a copié : la complétude ne recule
                    -- jamais vers le présent, même quand NetXMS purge.
                    complete_since = LEAST(hist_source_sync.complete_since,
                                           EXCLUDED.complete_since)
                """,
                (source, now, len(rows), horizon, complete_since),
            )
        await conn.commit()
    _last_sync[source] = now
    logger.info("Pannes %s (%s) : %d ligne(s), %d fin(s) relue(s) depuis %s",
                source, LABELS[source], len(rows), len(ends), since.isoformat())
    return {"downtimes": len(rows), "closures": len(ends)}
