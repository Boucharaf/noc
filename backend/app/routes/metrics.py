from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import ingest_rate_limit, read_rate_limit
from app.core.security import get_current_user, verify_api_key
from app.db.session import get_db
from app.schemas.metrics import (
    MetricBulkIngestPayload,
    MetricBulkIngestResponse,
    NetworkKpiOut,
    NodeDownOut,
)
from app.services import cache_service, metrics_service

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post(
    "/ingest/bulk",
    response_model=MetricBulkIngestResponse,
)
def ingest_metrics_bulk(
    payload: MetricBulkIngestPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    """Batch d'un pass de collecte de métriques — voir
    etl/pipelines/tasks.collect_metrics. Pas de notification/broadcast : une
    lecture de métrique n'est jamais un événement à faire remonter à un
    humain en direct, seulement une donnée pour les KPI et les graphes."""
    result = metrics_service.ingest_metrics_bulk(db, payload.metrics)
    if result["created"]:
        cache_service.invalidate_prefix("kpi:")
    return result


@router.get(
    "/network",
    response_model=NetworkKpiOut,
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)
def get_network_kpi(
    hours: int = Query(1, ge=1, le=720, description="Fenêtre d'agrégation, en heures"),
    db: Session = Depends(get_db),
):
    """KPI réseau (disponibilité, perte de paquets, latence, bande passante)
    agrégés sur les `hours` dernières heures — le bloc de KPI que fact_metric
    rend possible pour la première fois (voir l'audit du schéma)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return metrics_service.get_network_kpi(db, since=since.replace(tzinfo=None))


@router.get(
    "/nodes/down",
    response_model=list[NodeDownOut],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)
def list_nodes_down(db: Session = Depends(get_db)):
    """Équipements dont la dernière lecture de disponibilité connue est DOWN
    — la liste détaillée derrière le compteur `nodes_down` de /network."""
    return metrics_service.list_nodes_down(db)
