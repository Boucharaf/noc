"""
Real-time alert stream. The browser side is hooks/useRealtime.js.

Each connection subscribes to the Redis ALERT_CHANNEL and forwards incidents
published by /api/incidents/ingest. Authentication happens via the first
WebSocket frame ({"type":"auth","token":"..."}), not a ?token= query
parameter: browsers cannot set an Authorization header on a WebSocket
handshake, and a token in the URL ends up recorded in plain text by reverse
proxies and access logs — a query string is logged, a message frame is not.
"""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.constants import REDIS_HOST, REDIS_PORT
from app.services.alert_broadcaster import ALERT_CHANNEL
from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

HEARTBEAT_INTERVAL_S = 20
AUTH_TIMEOUT_S = 5


@router.websocket("/ws/alerts")
async def alerts_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_S)
        message = json.loads(raw)
        if message.get("type") != "auth":
            raise ValueError("Premier message attendu : {'type': 'auth', 'token': ...}")
        decode_access_token(message.get("token", ""))
    except Exception:
        try:
            await websocket.send_text(json.dumps({"type": "auth_error"}))
        finally:
            await websocket.close(code=4401, reason="Not authenticated")
        return

    client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2
    )
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
                # Heartbeat so idle proxies (nginx) don't drop the connection,
                # and so a dead client is detected by the failed send.
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info("WebSocket alert stream closed: %s", exc)
    finally:
        try:
            await pubsub.close()
            await client.aclose()
        except Exception:
            pass
