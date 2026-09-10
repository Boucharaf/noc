"""
Flux d'alertes temps réel.

AUTHENTIFICATION PAR LA PREMIÈRE TRAME (`{"type":"auth","token":"…"}`) et
non par un paramètre `?token=` : un navigateur ne peut pas poser d'en-tête
Authorization sur une poignée de main WebSocket, et un jeton passé dans
l'URL finit enregistré en clair dans les journaux du reverse proxy. Une
trame, elle, n'est pas journalisée.

CE QUI A CHANGÉ AVEC LA NOUVELLE ARCHITECTURE. Chaque connexion ouvrait
auparavant son propre abonnement Redis. Avec quarante opérateurs, c'était
quarante connexions Redis en attente permanente. Le backend tient désormais
UN seul abonnement (services/realtime_service.py) et redistribue en
mémoire : une connexion Redis, quel que soit le nombre d'écrans ouverts.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.auth_service import decode_access_token
from app.services.realtime_service import hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["temps réel"])

# Le battement empêche les proxys inactifs (nginx coupe à 60 s par défaut)
# de fermer la connexion, et révèle un client mort par l'échec de l'envoi.
HEARTBEAT_INTERVAL_S = 20
AUTH_TIMEOUT_S = 5


@router.websocket("/ws/alerts")
async def alerts_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_S)
        message = json.loads(raw)
        if message.get("type") != "auth":
            raise ValueError("Première trame attendue : {'type': 'auth', 'token': …}")
        decode_access_token(message.get("token", ""))
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps({"type": "auth_error"}))
        with contextlib.suppress(Exception):
            await websocket.close(code=4401, reason="Non authentifié")
        return

    await hub.add(websocket)
    try:
        while True:
            # Le client n'a rien à envoyer après l'authentification : cette
            # attente sert uniquement à détecter sa déconnexion. À son
            # expiration, on envoie un battement.
            try:
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=HEARTBEAT_INTERVAL_S
                )
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — une connexion qui tombe est
        # un événement ordinaire, pas une erreur du service.
        logger.debug("Flux d'alertes fermé : %s", exc)
    finally:
        await hub.discard(websocket)
