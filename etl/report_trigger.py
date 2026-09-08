"""
Point d'intégration entre l'ETL et le service de reporting du backend.

L'ETL ne génère pas les rapports : il signale qu'un cycle mensuel est
clos, et le backend (report_service) produit le PDF et le DOCX à partir
de l'entrepôt. La frontière est là parce que le rapport doit refléter
exactement les mêmes agrégats que le dashboard — les recalculer une
seconde fois côté ETL, avec un autre code, garantirait qu'ils finissent
par diverger.

RÈGLE ABSOLUE : un backend injoignable ne doit JAMAIS faire échouer la
tâche Celery. La collecte est le service critique ; le rapport est un
livrable mensuel qui peut être régénéré à la main depuis l'interface
(écran Rapports). D'où le `try/except` large et le retour d'un
dictionnaire de diagnostic plutôt qu'une exception.

Configuration (etl/.env) :
    BACKEND_INTERNAL_URL=http://backend:8000
    INTERNAL_API_KEY=<la même valeur que dans backend/.env>

Sans ces deux variables, la fonction ne tente rien et le dit.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# Génération PDF + DOCX sur un mois complet : la requête peut légitimement
# durer une minute sur un gros parc. Un timeout court provoquerait un
# échec alors que le rapport est en train d'être produit correctement.
REQUEST_TIMEOUT_S = int(os.getenv("BACKEND_REPORT_TIMEOUT_S", "180"))


def trigger_monthly_report(as_of: datetime) -> dict:
    """Demande au backend de produire le rapport du mois PRÉCÉDENT.

    `as_of` est l'instant d'exécution de la tâche (le 1er à 02 h 30) ; le
    backend en déduit le mois à clôturer, c'est-à-dire celui qui vient de
    s'achever. Cette convention est portée par le backend et non ici,
    pour qu'un appel manuel depuis un autre client donne le même
    résultat.
    """
    base_url = os.getenv("BACKEND_INTERNAL_URL", "").rstrip("/")
    api_key = os.getenv("INTERNAL_API_KEY", "")

    if not base_url or not api_key:
        logger.warning(
            "Rapport mensuel non déclenché : BACKEND_INTERNAL_URL ou "
            "INTERNAL_API_KEY absente de l'environnement de l'ETL."
        )
        return {
            "triggered": False,
            "as_of": as_of.isoformat(),
            "reason": "BACKEND_INTERNAL_URL / INTERNAL_API_KEY non configurées",
        }

    try:
        response = requests.post(
            f"{base_url}/api/internal/reports/monthly",
            json={"as_of": as_of.isoformat()},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT_S,
        )
    except Exception as exc:  # requests lève une famille entière d'exceptions
        logger.error("Rapport mensuel : backend injoignable (%s)", exc)
        return {"triggered": False, "as_of": as_of.isoformat(), "reason": str(exc)}

    if not response.ok:
        logger.error(
            "Rapport mensuel refusé par le backend : HTTP %s — %s",
            response.status_code,
            response.text[:300],
        )
        return {
            "triggered": False,
            "as_of": as_of.isoformat(),
            "status": response.status_code,
            "reason": response.text[:300],
        }

    logger.info("Rapport mensuel déclenché (HTTP %s).", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    return {"triggered": True, "as_of": as_of.isoformat(), "response": payload}
