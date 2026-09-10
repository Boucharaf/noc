"""
Sonde de santé.

Vérifie les TROIS dépendances réelles du backend, et dans cet ordre
d'importance :

  redis      — l'instantané. Sans lui, aucun écran « maintenant » ne
               fonctionne. C'est la dépendance critique.
  collecteur — Redis peut répondre alors que le collecteur est mort : les
               clés expirent au bout de trois cycles et le tableau de bord
               s'éteint. Un backend « vivant » devant un instantané périmé
               est inutile, et la sonde doit le dire.
  base       — les comptes et le travail d'exploitation. Sa perte empêche
               de se connecter et d'acquitter, mais l'affichage temps réel
               continue de fonctionner : c'est une dégradation, pas une
               panne totale.

La distinction `degraded` / `error` suit cette hiérarchie, et c'est elle qui
décide si le conteneur est retiré du répartiteur de charge.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import COLLECT_INTERVAL_S
from app.db.redis_client import redis_sync
from app.db.session import get_db
from app.services import live_service

router = APIRouter(prefix="/api", tags=["santé"])


@router.get("/health")
async def health(response: Response, db: Session = Depends(get_db)):
    checks: dict = {}

    # -- Redis ------------------------------------------------------------
    try:
        redis_sync.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"status": "error", "detail": str(exc)[:200]}

    # -- Collecteur -------------------------------------------------------
    try:
        age = await live_service.snapshot_age_s()
        if age is None:
            checks["collector"] = {
                "status": "error",
                "detail": (
                    "Aucun instantané. Le collecteur ne publie plus depuis au "
                    f"moins {COLLECT_INTERVAL_S * 3} s, ou n'a jamais démarré."
                ),
            }
        elif age > COLLECT_INTERVAL_S * 2:
            checks["collector"] = {
                "status": "degraded",
                "age_s": round(age),
                "detail": f"Instantané vieux de {round(age)} s.",
            }
        else:
            checks["collector"] = {"status": "ok", "age_s": round(age)}
    except Exception as exc:  # noqa: BLE001
        checks["collector"] = {"status": "error", "detail": str(exc)[:200]}

    # -- Base -------------------------------------------------------------
    try:
        db.execute(text("SELECT 1"))
        # La présence des tables confirme que backend/sql/schema.sql a été
        # appliqué. Sans elles, la connexion elle-même échouerait à la
        # première requête, avec un message PostgreSQL peu lisible.
        tables = db.execute(
            text(
                """
                SELECT count(*) FROM information_schema.tables
                WHERE table_name IN ('noc_user', 'ops_alert_state', 'kpi_daily')
                """
            )
        ).scalar()
        checks["database"] = (
            {"status": "ok"}
            if tables == 3
            else {
                "status": "degraded",
                "detail": (
                    "Schéma incomplet — appliquer backend/sql/schema.sql sur "
                    "la base du NOC."
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"status": "error", "detail": str(exc)[:200]}

    if any(c.get("status") == "error" for c in checks.values()):
        overall = "error"
        # 503 et non 200 : c'est ce code qui fait retirer le conteneur du
        # répartiteur. Répondre 200 sur un backend incapable de servir la
        # moindre donnée le laisserait recevoir du trafic.
        response.status_code = 503
    elif any(c.get("status") == "degraded" for c in checks.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "checks": checks}


@router.get("/health/live")
def liveness():
    """Vivacité seule — le processus répond-il ?

    Séparée de `/health` pour la sonde de redémarrage de l'orchestrateur :
    redémarrer le backend parce que Redis est tombé n'arrangerait rien et
    ferait perdre les sessions en cours.
    """
    return {"status": "ok"}
