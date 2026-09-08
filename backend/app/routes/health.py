"""
Sonde de santé.

Vérifie les trois dépendances réelles du backend : l'entrepôt, Redis, et
la fraîcheur de la collecte ETL. Un backend qui répond alors que l'ETL
n'a rien collecté depuis deux heures est « vivant » mais inutile — d'où
`etl` dans la réponse.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.redis_client import redis_client
from app.db.session import get_db
from app.services import interop_service

router = APIRouter(prefix="/api", tags=["santé"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    checks: dict = {}

    try:
        db.execute(text("SELECT 1"))
        # La présence des vues confirme que sql/01_backend_extensions.sql
        # a bien été appliqué : sans elles, tout le backend renverrait des
        # 500 à la première requête métier.
        has_views = db.execute(
            text(
                """
                SELECT count(*) FROM information_schema.views
                WHERE table_name IN ('v_node','v_incident')
                """
            )
        ).scalar()
        checks["database"] = {
            "status": "ok" if has_views == 2 else "degraded",
            "detail": (
                "ok" if has_views == 2
                else "Vues v_node/v_incident absentes — appliquer sql/01_backend_extensions.sql"
            ),
        }
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)[:200]}

    try:
        redis_client.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": str(exc)[:200]}

    try:
        now = datetime.now(UTC)
        status = interop_service.get_interop_status(db, now.month, now.year)
        checks["etl"] = {
            "status": "ok" if status["tools_healthy"] > 0 else "degraded",
            "tools_healthy": status["tools_healthy"],
            "tools_total": status["tools_total"],
        }
    except Exception as exc:
        checks["etl"] = {"status": "error", "detail": str(exc)[:200]}

    overall = "ok"
    if any(c.get("status") == "error" for c in checks.values()):
        overall = "error"
    elif any(c.get("status") == "degraded" for c in checks.values()):
        overall = "degraded"

    return {"status": overall, "checks": checks}
