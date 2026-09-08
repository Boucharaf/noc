"""
Routes internes, appelées par l'ETL et par personne d'autre.

Elles sont protégées par la clé statique `INTERNAL_API_KEY` et non par un
JWT : l'appelant est un worker Celery, pas un utilisateur connecté.

CONTRAT AVEC L'ETL
------------------
`etl/report_trigger.py` porte aujourd'hui ce TODO :

    # TODO: remplacer par l'URL interne réelle du backend une fois définie
    # (ex. POST {BACKEND_INTERNAL_URL}/internal/reports/monthly).

C'est cet endpoint qui le referme. Côté ETL, remplacer le corps de
`trigger_monthly_report` par :

    import os, requests

    def trigger_monthly_report(as_of):
        url = os.getenv("BACKEND_INTERNAL_URL")
        key = os.getenv("INTERNAL_API_KEY")
        if not (url and key):
            return {"triggered": False, "reason": "backend non configuré"}
        try:
            response = requests.post(
                f"{url}/api/internal/reports/monthly",
                json={"as_of": as_of.isoformat()},
                headers={"Authorization": f"Bearer {key}"},
                timeout=120,
            )
            return {"triggered": response.ok, "status": response.status_code}
        except Exception as exc:
            # Ne jamais laisser un backend injoignable faire échouer la
            # tâche Celery : la collecte doit continuer sans le rapport.
            return {"triggered": False, "reason": str(exc)}

Le mois généré est le mois PRÉCÉDANT `as_of` : la tâche planifiée est
programmée le 1er du mois à 02:30 (etl/celery_app.py), donc au moment où
elle s'exécute, le mois à clôturer est celui qui vient de s'achever.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_internal_key
from app.schemas.maintenance import (
    MaintenanceWindowBulkImport,
    MaintenanceWindowBulkImportResponse,
)
from app.services import kpi_service, maintenance_service, report_service, watcher_service
from app.services.periods import previous_month

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/internal",
    tags=["interne (ETL)"],
    dependencies=[Depends(require_internal_key)],
)


class MonthlyReportTrigger(BaseModel):
    as_of: datetime | None = None
    # Permet de régénérer explicitement un mois donné (rattrapage).
    month: int | None = None
    year: int | None = None


@router.post("/reports/monthly")
def trigger_monthly_report(
    payload: MonthlyReportTrigger,
    db: Session = Depends(get_db),
):
    as_of = payload.as_of or datetime.now(UTC)
    if payload.month and payload.year:
        month, year = payload.month, payload.year
    else:
        month, year = previous_month(as_of.month, as_of.year)

    generated = {}
    errors = {}
    for output_format in ("pdf", "docx"):
        try:
            generated[output_format] = report_service.generate(db, month, year, output_format)
        except Exception as exc:
            # Un format en échec ne doit pas empêcher l'autre d'aboutir :
            # le PDF a besoin de fpdf2, le DOCX de python-docx, et l'un
            # peut manquer sans l'autre.
            logger.exception("Génération %s en échec : %s", output_format, exc)
            errors[output_format] = str(exc)[:300]

    return {
        "triggered": bool(generated),
        "month": month,
        "year": year,
        "files": generated,
        "errors": errors or None,
    }


@router.post("/maintenance-windows", response_model=MaintenanceWindowBulkImportResponse)
def import_maintenance_windows(
    payload: MaintenanceWindowBulkImport,
    db: Session = Depends(get_db),
):
    """Import des maintenances planifiées détectées par l'ETL.

    L'ETL ne collecte pas encore ces fenêtres (aucun connecteur ne lit le
    mode maintenance de Zabbix ni les downtimes Centreon). Cet endpoint
    est prêt pour le jour où ce sera le cas ; en attendant, les fenêtres
    se créent depuis le dashboard.
    """
    return maintenance_service.import_windows(
        db, [window.model_dump() for window in payload.windows]
    )


@router.post("/cache/invalidate")
def invalidate_cache():
    """Vide le cache KPI.

    Utile après un import massif ou une correction de données : sans
    cela, le dashboard servirait des agrégats périmés jusqu'à
    l'expiration naturelle (CACHE_TTL).
    """
    kpi_service.invalidate_cache()
    return {"invalidated": True}


@router.post("/watcher/run")
def run_watcher_once():
    """Force un passage du veilleur d'incidents.

    Permet à l'ETL de signaler « je viens de charger un lot » et de
    déclencher immédiatement la diffusion, sans attendre le prochain
    passage périodique.
    """
    processed = watcher_service.run_once()
    return {"processed": processed}
