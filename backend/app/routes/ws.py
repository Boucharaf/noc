"""
Flux d'alertes temps réel.

L'authentification se fait par la PREMIÈRE TRAME WebSocket
(`{"type":"auth","token":"..."}`) et non par un paramètre `?token=` : un
navigateur ne peut pas poser d'en-tête Authorization sur une poignée de
main WebSocket, et un jeton passé dans l'URL finit enregistré en clair
dans les journaux du reverse proxy. Une trame, elle, n'est pas journalisée.

La source des messages est le veilleur d'incidents (watcher_service), qui
publie sur le canal Redis ALERT_CHANNEL.
"""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import REDIS_URL
from app.services.alert_broadcaster import ALERT_CHANNEL
from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["temps réel"])

HEARTBEAT_INTERVAL_S = 20
AUTH_TIMEOUT_S = 5


@router.websocket("/ws/alerts")
async def alerts_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_S)
        message = json.loads(raw)
        if message.get("type") != "auth":
            raise ValueError("Première trame attendue : {'type': 'auth', 'token': ...}")
        decode_access_token(message.get("token", ""))
    except Exception:
        try:
            await websocket.send_text(json.dumps({"type": "auth_error"}))
        finally:
            await websocket.close(code=4401, reason="Non authentifié")
        return

    client = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(ALERT_CHANNEL)
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_INTERVAL_S
            )
            if message is not None:
                await websocket.send_text(message["data"])
            else:
                # Battement de cœur : empêche les proxys inactifs (nginx)
                # de couper la connexion, et révèle un client mort par
                # l'échec de l'envoi.
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info("Flux d'alertes fermé : %s", exc)
    finally:
        try:
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            pass
