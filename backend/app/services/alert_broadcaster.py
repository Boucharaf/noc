"""Pont Redis pub/sub entre le veilleur d'incidents et /ws/alerts.

Le veilleur (watcher_service) publie sur ALERT_CHANNEL ; chaque
connexion WebSocket ouverte, y compris sur un autre worker uvicorn, y est
abonnée et relaie le message à son client.
"""
import json
import logging
from typing import Any

from app.db.redis_client import redis_client

logger = logging.getLogger(__name__)

ALERT_CHANNEL = "noc:alerts"


def publish_alert(event: dict[str, Any]) -> None:
    try:
        redis_client.publish(ALERT_CHANNEL, json.dumps(event, default=str))
    except Exception as exc:  # une diffusion cassée ne doit rien interrompre
        logger.warning("Diffusion d'alerte échouée : %s", exc)
