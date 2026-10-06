"""
Temps réel — du collecteur au navigateur.

CE QUI A REMPLACÉ QUOI. L'ancien « veilleur » relisait la table
`fact_incident` toutes les trente secondes pour y découvrir les nouveautés.
Il n'a plus de raison d'être : le collecteur SAIT déjà ce qui est nouveau,
puisqu'il compare chaque instantané au précédent. Il publie donc directement
sur un canal Redis, et ce module s'y abonne.

Deux conséquences qui valaient le changement :

  * plus de sondage de base de données — trente requêtes par minute et par
    backend ont disparu ;
  * plusieurs backends derrière un répartiteur reçoivent tous la
    publication, là où le veilleur devait être activé sur un seul conteneur
    sous peine d'alertes en double. La contrainte « UN SEUL backend doit
    l'activer », que personne ne lit jamais dans un fichier de compose, a
    disparu avec lui.

Le canal Redis est en « au plus une fois » : un message publié pendant une
coupure de la connexion est perdu. C'est acceptable ICI et seulement ici —
le navigateur relit l'instantané complet à chaque événement et à chaque
reconnexion, donc un message manqué retarde l'affichage d'au plus un cycle,
il ne le fausse jamais. Rien de durable ne transite par ce canal.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from app.core.config import NOTIFY_SEVERITIES
from app.db.redis_client import get_pubsub_redis

logger = logging.getLogger(__name__)

CHANNEL_ALERTS = "noc:events:alerts"


class ConnectionHub:
    """Les WebSocket ouverts, et la diffusion vers eux.

    Un `set` et non une liste : un client peut se déconnecter pendant qu'on
    lui écrit, et le retirer d'une liste pendant l'itération sauterait le
    voisin.
    """

    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._lock = asyncio.Lock()

    async def add(self, websocket) -> None:
        async with self._lock:
            self._clients.add(websocket)
        logger.info("WebSocket connecté (%d client(s))", len(self._clients))

    async def discard(self, websocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, payload: dict) -> None:
        """Envoie à tous, en retirant ceux qui ne répondent plus.

        Les envois sont faits en parallèle : un client dont la fenêtre est
        en veille peut mettre plusieurs secondes à accuser réception, et le
        traiter en série retarderait tous les suivants.
        """
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return

        message = json.dumps(payload, ensure_ascii=False, default=str)
        results = await asyncio.gather(
            *(client.send_text(message) for client in clients),
            return_exceptions=True,
        )
        dead = [
            client
            for client, result in zip(clients, results)
            if isinstance(result, BaseException)
        ]
        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)
            logger.info("%d WebSocket fermé(s) retiré(s)", len(dead))


hub = ConnectionHub()


async def subscribe_loop(stop: asyncio.Event) -> None:
    """Relaie le canal Redis du collecteur vers les navigateurs.

    La boucle se reconnecte indéfiniment : Redis peut redémarrer, et un
    backend qui cesserait d'écouter laisserait le tableau de bord figé sans
    que rien ne le signale — le pire des états.
    """
    while not stop.is_set():
        pubsub = None
        try:
            pubsub = get_pubsub_redis().pubsub()
            await pubsub.subscribe(CHANNEL_ALERTS)
            logger.info("Abonné au canal temps réel %s", CHANNEL_ALERTS)

            async for message in pubsub.listen():
                if stop.is_set():
                    break
                if message.get("type") != "message":
                    continue
                await _dispatch(message.get("data"))

        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — voir docstring : cette boucle ne
            # doit jamais mourir définitivement.
            logger.exception("Canal temps réel interrompu — nouvelle tentative dans 5 s")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5)
        finally:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()


async def _dispatch(raw) -> None:
    try:
        alerts = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Message temps réel illisible, ignoré")
        return
    if not isinstance(alerts, list) or not alerts:
        return

    logger.info("%d nouvelle(s) alerte(s) reçue(s) du collecteur", len(alerts))

    await hub.broadcast(
        {
            "type": "alerts.new",
            "count": len(alerts),
            "alerts": [
                {
                    "key": f"{a.get('tool')}:{a.get('ref')}",
                    "tool": a.get("tool"),
                    "severity": a.get("severity"),
                    "message": a.get("message"),
                    "node_name": a.get("node_name"),
                    "since": a.get("since"),
                }
                for a in alerts
            ],
        }
    )

    actionable = [a for a in alerts if a.get("severity") in NOTIFY_SEVERITIES]
    if actionable:
        await _notify(actionable)


async def _notify(alerts: list[dict]) -> None:
    """Notifications sortantes (SMS, courriel, push navigateur).

    Importé ici et non en tête de module : le service de notification tire
    Twilio et py_vapid, dépendances lourdes qu'un déploiement sans
    notifications n'a aucune raison de charger.

    Un échec d'envoi ne remonte pas : la diffusion WebSocket a déjà eu lieu,
    et l'alerte est visible à l'écran. Une passerelle SMS injoignable ne doit
    pas faire tomber le canal temps réel.
    """
    try:
        from app.services import notification_service

        await notification_service.notify_new_alerts(alerts)
    except Exception:  # noqa: BLE001
        logger.exception("Notifications sortantes en échec — alertes tout de même diffusées")
