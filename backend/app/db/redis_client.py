"""
Accès Redis du backend.

DEUX CLIENTS, ET C'EST DÉLIBÉRÉ :

  * `store` — le SnapshotStore partagé avec le collecteur (asynchrone). Il
    connaît le contrat de clés défini dans collector/state.py, et c'est le
    seul chemin par lequel le backend lit l'état courant et le cache
    d'historique. Faire écrire au backend ses propres clés d'instantané
    créerait une seconde source de vérité.

  * `redis_sync` — un client synchrone, réservé aux usages qui vivent hors de
    la boucle asyncio : le magasin de sessions (app/core/session_store.py) et
    la limitation de débit, appelés depuis des dépendances FastAPI
    synchrones. Les mélanger obligerait à convertir tout le chemin
    d'authentification en asynchrone pour un gain nul.
"""
from __future__ import annotations

import logging

import redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import COLLECT_INTERVAL_S, REDIS_URL

logger = logging.getLogger(__name__)

# `decode_responses=True` des deux côtés : tout ce qu'on stocke est du JSON
# textuel, et manipuler des bytes n'apporterait que des `.decode()` partout.
#
# Les délais sont courts VOLONTAIREMENT. Redis est sur le même réseau ; s'il
# met plus de deux secondes à répondre, il est en difficulté, et faire
# patienter l'opérateur n'améliorera rien. Mieux vaut échouer vite et
# afficher « cache indisponible ».
redis_sync = redis.from_url(
    REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
)

_async_client: AsyncRedis | None = None
_pubsub_client: AsyncRedis | None = None
_store = None


def get_redis() -> AsyncRedis:
    """Client asynchrone, créé à la première demande.

    Pas au chargement du module : un client asyncio créé hors d'une boucle
    en cours s'attache à la mauvaise boucle d'événements, et le premier appel
    échoue avec un « attached to a different loop » difficile à relier à sa
    cause.
    """
    global _async_client
    if _async_client is None:
        _async_client = AsyncRedis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
    return _async_client


def get_pubsub_redis() -> AsyncRedis:
    """Client dédié à l'abonnement temps réel, SANS délai de lecture.

    Un abonné pub/sub passe l'essentiel de son temps à attendre : c'est son
    métier. Avec le `socket_timeout` du client ordinaire, chaque période de
    calme dépasse le délai, la lecture lève `TimeoutError`, la boucle croit
    Redis tombé et se reconnecte — en boucle, toutes les cinq secondes, en
    remplissant les journaux d'erreurs qui n'en sont pas.

    Le délai de CONNEXION reste, lui, en place : ne pas pouvoir se connecter
    est une vraie panne, et il faut la voir vite.
    """
    global _pubsub_client
    if _pubsub_client is None:
        _pubsub_client = AsyncRedis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=None,
            # Maintient la connexion vivante à travers les pare-feux et les
            # répartiteurs qui coupent les sessions inactives.
            socket_keepalive=True,
            health_check_interval=30,
        )
    return _pubsub_client


def get_store():
    """Le SnapshotStore, partagé avec le collecteur."""
    global _store
    if _store is None:
        from collector.state import SnapshotStore

        _store = SnapshotStore(get_redis(), COLLECT_INTERVAL_S)
    return _store


async def aclose() -> None:
    global _async_client, _pubsub_client, _store
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
        _store = None
    if _pubsub_client is not None:
        await _pubsub_client.aclose()
        _pubsub_client = None
