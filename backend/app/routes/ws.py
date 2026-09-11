"""
Flux d'alertes temps réel.

AUTHENTIFICATION PAR LA PREMIÈRE TRAME (`{"type":"auth","token":"…"}`) et
non par un paramètre `?token=` : un navigateur ne peut pas poser d'en-tête
Authorization sur une poignée de main WebSocket, et un jeton passé dans
l'URL finit enregistré en clair dans les journaux du reverse proxy. Une
trame, elle, n'est pas journalisée.

LA CONNEXION NE SURVIT PAS AU JETON. Elle est fermée (4401) dès que le jeton
d'accès expire ; le client se reconnecte avec le jeton rafraîchi
(frontend/src/hooks/useRealtime.js suit le jeton). Sans cela, un compte
désactivé continuerait de recevoir le flux d'alertes tant que son onglet
reste ouvert.

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
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import session_store
from app.db.session import SessionLocal
from app.models import User
from app.services.auth_service import decode_access_token
from app.services.realtime_service import hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["temps réel"])

# Le battement empêche les proxys inactifs (nginx coupe à 60 s par défaut)
# de fermer la connexion, et révèle un client mort par l'échec de l'envoi.
HEARTBEAT_INTERVAL_S = 20
AUTH_TIMEOUT_S = 5


def _session_still_valid(payload: dict) -> bool:
    """Les contrôles de get_current_user (dependencies/auth.py), hors requête
    HTTP : une signature valide ne suffit pas, le compte doit exister, être
    actif, avoir gardé son rôle et ne pas avoir vu ses sessions coupées."""
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.id == int(payload["sub"]), User.is_active.is_(True))
            .first()
        )
        return (
            user is not None
            and user.role == payload.get("role")
            and not session_store.is_access_token_revoked(user.id, payload.get("iat"))
        )
    finally:
        db.close()


@router.websocket("/ws/alerts")
async def alerts_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_S)
        message = json.loads(raw)
        if message.get("type") != "auth":
            raise ValueError("Première trame attendue : {'type': 'auth', 'token': …}")
        payload = decode_access_token(str(message.get("token", "")))
        # Requête SQL synchrone : dans un thread, pour ne pas bloquer la
        # boucle qui sert les autres connexions.
        if not await asyncio.to_thread(_session_still_valid, payload):
            raise ValueError("Compte désactivé, rôle modifié ou session révoquée")
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps({"type": "auth_error"}))
        with contextlib.suppress(Exception):
            await websocket.close(code=4401, reason="Non authentifié")
        return

    expires_at = float(payload["exp"])

    await hub.add(websocket)
    try:
        while True:
            # Vérifié à chaque tour et non au seul battement : un client qui
            # enverrait des trames sans arrêt repousserait sinon indéfiniment
            # le contrôle.
            if time.time() >= expires_at:
                await websocket.close(code=4401, reason="Jeton expiré")
                break
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
