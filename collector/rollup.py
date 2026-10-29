"""
Agrégats journaliers — la seule chose que le collecteur écrit sur disque.

POURQUOI ILS EXISTENT. L'architecture ne recopie aucun historique : les
courbes d'un équipement sont lues chez l'outil source à la demande. Mais le
tableau Direction demande « l'évolution du nombre d'incidents sur douze
mois », et répondre à cette question par fédération obligerait à interroger
Zabbix, Centreon et iTop sur 365 jours à chaque affichage — plusieurs
dizaines de secondes, sur des outils de production, pour une question posée
plusieurs fois par jour.

CE QU'ILS COÛTENT. Une ligne par jour, par site et par outil. Pour trente
sites et six outils, cela fait moins de deux cents lignes par jour, soit
quelques mégaoctets par an. À comparer aux millions de lignes quotidiennes
de l'ancienne hypertable `metric_value` : c'est le rapport entre un carnet
de bord et une photocopie de la base de Zabbix.

CE QU'ILS NE SONT PAS. Ce n'est pas une copie de l'historique : on n'y
retrouve pas un incident particulier, seulement des comptes et des moyennes.
Pour un incident précis, la réponse reste chez l'outil source. C'est la
frontière qui rend cette table petite, et elle doit le rester.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta, timezone

from . import config
from .state import SnapshotStore

logger = logging.getLogger(__name__)

# Compteurs accumulés entre deux écritures, en mémoire ET sauvegardés dans
# Redis à chaque cycle (SnapshotStore.save_rollup) : un redémarrage du
# collecteur en cours de journée reprend les compteurs du jour au lieu de
# repartir de zéro, et un bilan non écrit (base indisponible) reste en
# attente jusqu'à ce qu'il le soit.
_ACCUMULATOR: dict[tuple[date, str | None], dict] = {}
_COUNTERS = ("samples", "nodes", "up", "down", "degraded", "maintenance", "alerts", "critical")


def rollup_key(level: str, name: str) -> str:
    """Clé d'agrégat d'une région ou d'une province dans la colonne `site`.

    `kpi_daily` n'a qu'une colonne de localité : une région y est rangée sous
    « @region:<nom> », une province sous « @province:<nom> ». Le préfixe « @ »
    ne peut pas apparaître dans un nom de site réel, et les classements de
    sites l'excluent (kpi_service.sites_ranking).
    """
    return f"@{level}:{name}"


def observe(
    day: date,
    site: str | None,
    nodes: list,
    alerts: list,
    maintenance_node_keys: set[str] | None = None,
    maintenance_sites: set[str] | None = None,
) -> None:
    """Enregistre l'observation d'un cycle dans l'accumulateur du jour."""
    maintenance_node_keys = maintenance_node_keys or set()
    maintenance_sites = maintenance_sites or set()

    def is_maintenance(node) -> bool:
        return (
            node.state == "maintenance"
            or getattr(node, "id", None) in maintenance_node_keys
            or bool(node.site and node.site in maintenance_sites)
        )

    key = (day, site or None)
    bucket = _ACCUMULATOR.setdefault(
        key,
        {"samples": 0, "nodes": 0, "up": 0, "down": 0, "degraded": 0,
         "maintenance": 0, "alerts": 0, "critical": 0},
    )
    bucket["samples"] += 1
    bucket["nodes"] += len(nodes)
    bucket["up"] += sum(1 for n in nodes if not is_maintenance(n) and n.state == "up")
    bucket["down"] += sum(1 for n in nodes if not is_maintenance(n) and n.state == "down")
    bucket["degraded"] += sum(
        1 for n in nodes if not is_maintenance(n) and n.state == "degraded"
    )
    bucket["maintenance"] += sum(1 for n in nodes if is_maintenance(n))
    bucket["alerts"] += len(alerts)
    bucket["critical"] += sum(1 for a in alerts if a.severity == "critical")


def export_accumulator() -> list[dict]:
    """Compteurs en cours, sous une forme JSON (sauvegarde Redis)."""
    return [
        {"day": day.isoformat(), "site": site, **counters}
        for (day, site), counters in _ACCUMULATOR.items()
    ]


def restore_accumulator(payload: list) -> int:
    """Recharge les compteurs sauvegardés, au démarrage du collecteur.

    Les compteurs rechargés REMPLACENT ceux du même jour et du même site :
    appelé deux fois, il ne double rien. Une entrée illisible est ignorée.
    """
    restored = 0
    for item in payload or []:
        try:
            key = (date.fromisoformat(item["day"]), item.get("site"))
            counters = {name: int(item.get(name) or 0) for name in _COUNTERS}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        _ACCUMULATOR[key] = counters
        restored += 1
    return restored


def pending_days(now: datetime | None = None) -> list[date]:
    """Jours dont le bilan peut être écrit : avant aujourd'hui, et, pour la
    veille, seulement après ROLLUP_HOUR — un cycle commencé avant minuit doit
    avoir le temps de verser ses observations."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    return sorted({
        day for day, _site in _ACCUMULATOR
        if day < today - timedelta(days=1)
        or (day == today - timedelta(days=1) and now.hour >= config.ROLLUP_HOUR)
    })


def discard(day: date) -> None:
    """Oublie les compteurs d'un jour dont le bilan est écrit."""
    for key in [key for key in _ACCUMULATOR if key[0] == day]:
        del _ACCUMULATOR[key]


def _drain(day: date) -> list[dict]:
    """Calcule le bilan du jour donné et vide ses compteurs.

    Les moyennes sont calculées ici plutôt qu'à la lecture : le nombre
    d'échantillons dépend du nombre de cycles réellement exécutés, et une
    journée où le collecteur a été arrêté trois heures ne doit pas être
    divisée par le nombre de cycles théorique.
    """
    rows = []
    for (bucket_day, site), counters in list(_ACCUMULATOR.items()):
        if bucket_day != day:
            continue
        samples = max(1, counters["samples"])
        rows.append(
            {
                "day": bucket_day,
                "site": site,
                "samples": counters["samples"],
                "avg_nodes": round(counters["nodes"] / samples, 2),
                "avg_up": round(counters["up"] / samples, 2),
                "avg_down": round(counters["down"] / samples, 2),
                "avg_degraded": round(counters["degraded"] / samples, 2),
                "avg_alerts": round(counters["alerts"] / samples, 2),
                "avg_critical": round(counters["critical"] / samples, 2),
                # Disponibilité du parc : proportion moyenne d'équipements
                # « up » parmi ceux que la supervision voyait. Ce n'est PAS
                # une disponibilité au sens SLA d'un équipement donné — c'est
                # un indicateur de santé globale, et il est nommé comme tel.
                "fleet_availability_pct": round(
                    100.0 * counters["up"]
                    / (counters["nodes"] - counters["maintenance"]),
                    2,
                )
                if counters["nodes"] > counters["maintenance"]
                else None,
            }
        )
        del _ACCUMULATOR[(bucket_day, site)]
    return rows


def rows_for(day: date) -> list[dict]:
    """Bilan du jour SANS vider ses compteurs : ils ne sont oubliés
    qu'une fois le bilan écrit (`discard`), pour pouvoir réessayer."""
    saved = {key: dict(value) for key, value in _ACCUMULATOR.items() if key[0] == day}
    rows = _drain(day)
    _ACCUMULATOR.update(saved)
    return rows


async def write_rows(rows: list[dict]) -> None:
    """Écrit le bilan du jour dans PostgreSQL.

    L'import de psycopg est fait ici et non en tête de module : un
    déploiement qui désactive les agrégats (ROLLUP_ENABLED=false) ne doit pas
    exiger une base de données joignable pour démarrer.
    """
    if not rows:
        return
    import psycopg

    async with await psycopg.AsyncConnection.connect(config.DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            for row in rows:
                await cur.execute(
                    """
                    INSERT INTO kpi_daily (
                        day, site, samples, avg_nodes, avg_up, avg_down,
                        avg_degraded, avg_alerts, avg_critical,
                        fleet_availability_pct
                    )
                    VALUES (
                        %(day)s, %(site)s, %(samples)s, %(avg_nodes)s, %(avg_up)s,
                        %(avg_down)s, %(avg_degraded)s, %(avg_alerts)s,
                        %(avg_critical)s, %(fleet_availability_pct)s
                    )
                    -- Réécriture plutôt qu'échec : un collecteur redémarré en
                    -- fin de journée doit pouvoir compléter le bilan du jour.
                    ON CONFLICT (day, (COALESCE(site, ''))) DO UPDATE SET
                        samples = EXCLUDED.samples,
                        avg_nodes = EXCLUDED.avg_nodes,
                        avg_up = EXCLUDED.avg_up,
                        avg_down = EXCLUDED.avg_down,
                        avg_degraded = EXCLUDED.avg_degraded,
                        avg_alerts = EXCLUDED.avg_alerts,
                        avg_critical = EXCLUDED.avg_critical,
                        fleet_availability_pct = EXCLUDED.fleet_availability_pct
                    """,
                    row,
                )
        await conn.commit()
    logger.info("Agrégats journaliers écrits : %d ligne(s)", len(rows))


async def rollup_loop(store: SnapshotStore, stop: asyncio.Event) -> None:
    """Écrit les bilans en attente, puis attend la prochaine échéance.

    Échéance : chaque nuit à ROLLUP_HOUR pour la veille. Un bilan dont
    l'écriture échoue (base indisponible) reste en attente, sauvegardé dans
    Redis, et est réessayé toutes les ROLLUP_RETRY_S secondes jusqu'à ce
    qu'il soit écrit ; un collecteur arrêté à l'heure du bilan l'écrit à son
    redémarrage. Ensuite, les jours restés sans bilan sont recalculés depuis
    le journal historique (collector/history.py).
    """
    while not stop.is_set():
        failed = await write_pending(store)
        if config.HISTORY_ENABLED and not failed:
            from .history import backfill_missing

            try:
                await backfill_missing(7)
            except Exception:  # noqa: BLE001 — la collecte d'abord
                logger.exception("Rattrapage des bilans journaliers impossible")

        now = datetime.now(timezone.utc)
        target = now.replace(hour=config.ROLLUP_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        if failed:
            wait = min(wait, config.ROLLUP_RETRY_S)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=wait)


async def write_pending(store: SnapshotStore, now: datetime | None = None) -> bool:
    """Écrit les bilans en attente. Rend True si l'un d'eux a échoué."""
    failed = False
    for day in pending_days(now):
        try:
            await write_rows(rows_for(day))
        except Exception:  # noqa: BLE001 — une base indisponible ne doit pas
            # arrêter la collecte, qui est la fonction vitale.
            logger.exception(
                "Écriture du bilan du %s impossible — nouvel essai dans %d s",
                day, config.ROLLUP_RETRY_S,
            )
            failed = True
            continue
        discard(day)
    try:
        await store.save_rollup(export_accumulator())
    except Exception:  # noqa: BLE001
        logger.exception("Sauvegarde des compteurs du bilan impossible")
    return failed
