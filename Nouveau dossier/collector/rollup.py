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

# Compteurs accumulés en mémoire entre deux écritures. Volontairement pas en
# Redis : perdre le bilan partiel d'une journée sur un redémarrage n'a aucune
# conséquence — la moyenne du jour sera calculée sur moins d'échantillons, et
# le collecteur reprend au cycle suivant.
_ACCUMULATOR: dict[tuple[date, str], dict] = {}


def observe(day: date, site: str | None, nodes: list, alerts: list) -> None:
    """Enregistre l'observation d'un cycle dans l'accumulateur du jour."""
    key = (day, site or "—")
    bucket = _ACCUMULATOR.setdefault(
        key,
        {"samples": 0, "nodes": 0, "up": 0, "down": 0, "degraded": 0,
         "alerts": 0, "critical": 0},
    )
    bucket["samples"] += 1
    bucket["nodes"] += len(nodes)
    bucket["up"] += sum(1 for n in nodes if n.state == "up")
    bucket["down"] += sum(1 for n in nodes if n.state == "down")
    bucket["degraded"] += sum(1 for n in nodes if n.state == "degraded")
    bucket["alerts"] += len(alerts)
    bucket["critical"] += sum(1 for a in alerts if a.severity == "critical")


def _drain(day: date) -> list[dict]:
    """Extrait et vide les compteurs du jour donné.

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
                "site": None if site == "—" else site,
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
                    100.0 * counters["up"] / counters["nodes"], 2
                )
                if counters["nodes"]
                else None,
            }
        )
        del _ACCUMULATOR[(bucket_day, site)]
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
                    ON CONFLICT (day, site) DO UPDATE SET
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
    """Écrit le bilan de la veille une fois par jour, puis attend.

    L'écriture a lieu après minuit et non à minuit pile : un cycle de
    collecte en cours au changement de date doit avoir le temps de verser ses
    observations avant qu'on ne clôture la journée.
    """
    while not stop.is_set():
        now = datetime.now(timezone.utc)
        target = now.replace(
            hour=config.ROLLUP_HOUR, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                stop.wait(), timeout=(target - now).total_seconds()
            )
        if stop.is_set():
            return

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        try:
            await write_rows(_drain(yesterday))
        except Exception:  # noqa: BLE001 — une base indisponible ne doit pas
            # arrêter la collecte, qui est la fonction vitale.
            logger.exception(
                "Écriture des agrégats du %s impossible — journée perdue, "
                "la collecte continue",
                yesterday,
            )
