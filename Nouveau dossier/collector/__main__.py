"""
Point d'entrée du collecteur.

REMPLACE CELERY ET CELERY BEAT. L'ancienne pile faisait tourner un courtier
(Redis base 1), un backend de résultats (base 2), un worker et un
planificateur — quatre pièces mobiles pour exécuter une fonction toutes les
cinq minutes. Il n'y a ici ni file, ni sérialisation de tâches, ni
supervision de worker : une boucle asyncio dans un conteneur, dont l'échec
est visible par le healthcheck du conteneur lui-même.

Ce n'est pas un appauvrissement : Celery se justifie quand des tâches
hétérogènes doivent être réparties sur plusieurs machines, réessayées
individuellement et suivies à l'unité. Ici, une seule tâche périodique et
idempotente s'exécute sur un seul nœud — et la doubler créerait des
diffusions d'alertes en double, ce que Celery ne protège pas non plus.

CADENCE À DÉRIVE NULLE. Le prochain cycle est calé sur l'horloge, pas sur
« fin du précédent + intervalle ». Sans cela, un cycle de 40 s décalerait la
collecte de 40 s à chaque tour, et l'espacement réel des requêtes vers les
outils sources deviendrait imprévisible — l'inverse de ce qu'on a promis à
l'équipe sécurité de l'agence.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time

from redis.asyncio import Redis

from integrations.config import build_all_clients, configured_tools

from . import config
from .cycle import run_cycle
from .rollup import rollup_loop
from .state import SnapshotStore

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("noc.collector")


async def collect_loop(clients: dict, store: SnapshotStore, stop: asyncio.Event) -> None:
    interval = config.COLLECT_INTERVAL_S
    # Cale la première exécution sur une frontière d'intervalle : deux
    # collecteurs redémarrés à quelques secondes d'écart repartent alors en
    # phase, ce qui rend l'espacement des requêtes lisible côté outil source.
    next_run = time.monotonic()

    while not stop.is_set():
        try:
            await run_cycle(clients, store, config.CYCLE_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — la boucle ne meurt jamais : un
            # collecteur arrêté est un tableau de bord éteint.
            logger.exception("Cycle de collecte en échec — reprise au suivant")

        next_run += interval
        delay = next_run - time.monotonic()
        if delay < 0:
            # Le cycle a duré plus que l'intervalle. On repart de maintenant
            # plutôt que d'enchaîner les cycles en retard sans respirer.
            skipped = int(-delay // interval) + 1
            logger.warning(
                "Cycle plus long que l'intervalle (%.0f s de retard) — %d cycle(s) sauté(s)",
                -delay,
                skipped,
            )
            next_run = time.monotonic() + interval
            delay = interval

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


async def main() -> None:
    configured = configured_tools()
    if not configured:
        # Ce n'est pas une erreur fatale : une pile démarrée avant que les
        # accès aux outils ne soient obtenus doit tourner et le DIRE. Sortir
        # en erreur ferait redémarrer le conteneur en boucle.
        logger.warning(
            "Aucun outil configuré — renseigner <OUTIL>_API_URL dans .env. "
            "Le collecteur tourne à vide et l'écran Interopérabilité l'affichera."
        )
    else:
        logger.info("Outils configurés : %s", ", ".join(configured))

    redis = Redis.from_url(config.REDIS_URL, decode_responses=True)
    store = SnapshotStore(redis, config.COLLECT_INTERVAL_S)
    clients = build_all_clients()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # Windows n'a pas SIGTERM
            loop.add_signal_handler(sig, stop.set)

    tasks = [asyncio.create_task(collect_loop(clients, store, stop), name="collecte")]
    if config.ROLLUP_ENABLED:
        tasks.append(asyncio.create_task(rollup_loop(store, stop), name="agregats"))

    logger.info(
        "Collecteur démarré — cadence %d s, délai de cycle %d s",
        config.COLLECT_INTERVAL_S,
        config.CYCLE_TIMEOUT_S,
    )

    try:
        await stop.wait()
    finally:
        logger.info("Arrêt demandé — fermeture des connecteurs")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients.values():
            with contextlib.suppress(Exception):
                await client.aclose()
        await redis.aclose()
        logger.info("Collecteur arrêté proprement")


if __name__ == "__main__":
    asyncio.run(main())
