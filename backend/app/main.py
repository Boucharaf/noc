"""
Point d'entrée de l'API NOC.

TROIS DIFFÉRENCES STRUCTURELLES avec la version précédente :

1. **Plus de veilleur d'incidents.** L'ancien backend relisait
   `fact_incident` toutes les trente secondes pour y découvrir les
   nouveautés. Le collecteur sait déjà ce qui est nouveau — il compare
   chaque instantané au précédent — et publie sur un canal Redis. Le
   backend s'y abonne. Trente requêtes SQL par minute et par conteneur ont
   disparu, ainsi que la contrainte « UN SEUL backend doit l'activer » que
   personne ne lisait jamais dans le fichier de compose.

2. **La vérification de schéma ne bloque plus rien.** Le backend démarre
   même sans base : les écrans « maintenant » lisent Redis et fonctionnent.
   Seules l'authentification et l'exploitation sont indisponibles, ce que
   /api/health dit explicitement. Refuser de démarrer priverait le NOC de
   sa vue temps réel pour une panne qui ne l'affecte pas.

3. **Les connecteurs sont fermés proprement à l'arrêt.** Le backend en
   ouvre pour la fédération d'historique ; les laisser fuir laisserait des
   connexions ouvertes côté Zabbix à chaque redéploiement.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import (
    API_DOCS_ENABLED,
    CORS_ORIGINS,
    JWT_SECRET,
    LOG_LEVEL,
    REALTIME_ENABLED,
)
from app.db.session import SessionLocal
from app.routes import all_routers
from app.services.realtime_service import subscribe_loop

# Sans cette configuration, le logger racine reste à WARNING sans
# gestionnaire : tous les logger.info de l'application seraient perdus, et
# seuls les journaux d'accès d'uvicorn apparaîtraient.
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("noc.backend")


def _check_schema() -> None:
    """Contrôle non bloquant du schéma. Voir le point 2 de l'en-tête."""
    db = SessionLocal()
    try:
        missing = db.execute(
            text(
                """
                SELECT array_agg(expected.name)
                FROM (VALUES ('noc_user'), ('ops_alert_state'), ('kpi_daily'))
                     AS expected(name)
                WHERE NOT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = expected.name
                )
                """
            )
        ).scalar()
        if missing:
            logger.error(
                "Tables manquantes %s — appliquer backend/sql/schema.sql sur la "
                "base du NOC. Les écrans temps réel fonctionneront, "
                "l'authentification et l'exploitation non.",
                missing,
            )
        else:
            logger.info("Schéma de la base du NOC vérifié.")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Base du NOC injoignable au démarrage (%s). Les écrans temps réel "
            "restent servis depuis Redis.",
            exc,
        )
    finally:
        db.close()


def _check_secret() -> None:
    """Un secret de signature vide rendrait tous les jetons falsifiables.

    On refuse de démarrer plutôt que de servir une authentification
    décorative : c'est le seul cas où l'échec au démarrage est le bon
    comportement.
    """
    if not JWT_SECRET or len(JWT_SECRET) < 32:
        raise RuntimeError(
            "SECRET_KEY absente ou trop courte (32 caractères minimum). "
            "Générer : python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )


def _check_cors() -> None:
    """`*` avec des cookies de session : n'importe quel site pourrait lire les
    réponses de l'API au nom de l'utilisateur connecté."""
    if "*" in CORS_ORIGINS:
        raise RuntimeError(
            "CORS_ORIGINS=* est refusé : lister explicitement les origines du NOC."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secret()
    _check_cors()
    _check_schema()

    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []

    if REALTIME_ENABLED:
        tasks.append(asyncio.create_task(subscribe_loop(stop), name="temps-reel"))
        logger.info("Abonnement temps réel démarré.")
    else:
        logger.warning(
            "REALTIME_ENABLED=false : aucune alerte ne sera poussée vers les "
            "navigateurs. Les écrans se rafraîchiront par sondage uniquement."
        )

    yield

    stop.set()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Fermeture des connecteurs ouverts pour la fédération d'historique, et
    # du client Redis. Sans cela, chaque redéploiement laisserait des
    # connexions ouvertes côté Zabbix et Centreon.
    from app.db import redis_client
    from app.services import history_service

    with contextlib.suppress(Exception):
        await history_service.aclose_all()
    with contextlib.suppress(Exception):
        await redis_client.aclose()
    logger.info("Arrêt propre.")


app = FastAPI(
    title="API NOC RESINA",
    description=(
        "Backend du centre de supervision réseau.\n\n"
        "L'état courant est lu dans un instantané Redis réécrit toutes les "
        "300 secondes par le collecteur ; l'historique est interrogé à la "
        "demande chez les outils sources (Zabbix, Centreon, iTop) et mis en "
        "cache. Aucune métrique n'est recopiée dans le NOC — voir "
        "ARCHITECTURE.md."
    ),
    version="3.0.0",
    lifespan=lifespan,
    # Documentation interactive fermée par défaut : voir API_DOCS_ENABLED.
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,  # requis : le refresh token circule en cookie httpOnly
    # Les seules méthodes et en-têtes que le frontend emploie
    # (frontend/src/api/client.js), plutôt qu'un joker.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """En-têtes posés par l'API elle-même, et non par la seule passerelle :
    ils doivent tenir aussi quand le backend est joint autrement.

    `no-store` sur /api : ces réponses portent des jetons et des données
    nominatives, qu'aucun cache — navigateur ou proxy — n'a à conserver.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for router in all_routers:
    app.include_router(router)


@app.get("/")
def read_root():
    return {
        "service": "API NOC RESINA",
        "version": "3.0.0",
        "architecture": "instantané Redis + fédération d'historique",
        "docs": "/docs" if API_DOCS_ENABLED else None,
    }
