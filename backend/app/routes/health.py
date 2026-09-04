"""Health check pour le dashboard NOC lui-même : sans ça, l'outil qui
supervise tout le réseau n'a personne pour le superviser, lui.

Délibérément public (pas de get_current_user, pas de rate limit) : un
load-balancer ou un système de monitoring externe ne dispose généralement
pas d'un JWT applicatif.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.redis_client import redis_client
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    db_ok = True
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    finally:
        db.close()

    redis_ok = True
    try:
        redis_client.ping()
    except Exception:
        redis_ok = False

    payload = {"status": "ok" if db_ok and redis_ok else "degraded", "db": db_ok, "redis": redis_ok}
    return JSONResponse(content=payload, status_code=200 if db_ok and redis_ok else 503)