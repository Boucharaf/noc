"""
Point d'entrée de l'API NOC.

Deux différences structurelles avec l'ancien backend :

1. Le veilleur d'incidents (services/watcher_service.py) démarre avec
   l'application. C'est lui qui remplace l'ancien endpoint d'ingestion :
   sans lui, les incidents écrits par l'ETL n'entraîneraient ni
   diffusion WebSocket ni notification.

2. Le démarrage vérifie que sql/01_backend_extensions.sql a été appliqué.
   Sans ces vues, chaque requête métier échouerait en 500 avec un message
   PostgreSQL peu lisible ; mieux vaut un avertissement explicite dans les
   journaux dès la première seconde.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import CORS_ORIGINS, LOG_LEVEL, WATCHER_ENABLED
from app.db.session import SessionLocal
from app.routes import all_routers
from app.services.watcher_service import watcher_loop

# Sans cette configuration, le logger racine reste à WARNING sans
# gestionnaire : tous les logger.info/error de l'application seraient
# perdus, seuls les journaux d'accès d'uvicorn apparaîtraient.
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("noc.backend")


def _check_schema() -> None:
    db = SessionLocal()
    try:
        missing = db.execute(
            text(
                """
                SELECT array_agg(expected.name)
                FROM (VALUES ('v_node'), ('v_incident')) AS expected(name)
                WHERE NOT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_name = expected.name
                )
                """
            )
        ).scalar()
        if missing:
            logger.error(
                "Vues manquantes %s — appliquer backend/sql/01_backend_extensions.sql "
                "sur la base de l'entrepôt AVANT d'utiliser l'API.",
                missing,
            )
        else:
            logger.info("Schéma de l'entrepôt vérifié : vues de lecture présentes.")
    except Exception as exc:
        logger.error("Entrepôt injoignable au démarrage : %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_schema()

    watcher_task = None
    if WATCHER_ENABLED:
        watcher_task = asyncio.create_task(watcher_loop())
    else:
        logger.warning(
            "Veilleur désactivé (WATCHER_ENABLED=false) : aucune alerte temps réel "
            "ni notification ne sera émise."
        )

    yield

    if watcher_task is not None:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="API NOC RESINA",
    description=(
        "Backend du centre de supervision réseau. Lit l'entrepôt unique "
        "alimenté par l'ETL (Zabbix, iTop, NetXMS, Centreon, Nagios, Nokia NSP)."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,   # requis : le refresh token circule en cookie httpOnly
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in all_routers:
    app.include_router(router)


@app.get("/")
def read_root():
    return {"service": "API NOC RESINA", "version": "2.0.0", "docs": "/docs"}
