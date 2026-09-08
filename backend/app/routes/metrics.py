"""
Métriques réseau.

Lecture seule : la route d'ingestion de l'ancien backend a disparu avec
la table `fact_metric`. L'ETL alimente désormais `metric_value`
directement.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.metrics import (
    METRIC_TYPE_PATTERN,
    MetricPointOut,
    NetworkKpiOut,
    NetworkSeriesPointOut,
    NodeDownOut,
    TopNodeMetricOut,
)
from app.services import metrics_service

router = APIRouter(
    prefix="/api/metrics",
    tags=["métriques"],
    dependencies=[Depends(read_rate_limit)],
)


@router.get("/network", response_model=NetworkKpiOut)
def get_network_kpi(
    hours: int = Query(24, ge=1, le=8760),
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return metrics_service.get_network_kpi(db, hours, locality_id)


@router.get("/network/series", response_model=list[NetworkSeriesPointOut])
def get_network_series(
    metric_type: str = Query(pattern=METRIC_TYPE_PATTERN),
    hours: int = Query(24, ge=1, le=8760),
    locality_id: int | None = None,
    ministry_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Courbe d'une métrique agrégée sur le parc — la vue « santé réseau »."""
    return metrics_service.get_network_series(
        db, metric_type, hours, locality_id, ministry_id
    )


@router.get("/top", response_model=list[TopNodeMetricOut])
def get_top_nodes(
    metric_type: str = Query(pattern=METRIC_TYPE_PATTERN),
    hours: int = Query(24, ge=1, le=8760),
    limit: int = Query(10, ge=1, le=50),
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Classement des équipements sur une métrique.

    Le sens du tri suit la métrique : latence et pertes du pire au
    meilleur, disponibilité l'inverse (voir metrics_service._WORST_IS_HIGH).
    """
    return metrics_service.get_top_nodes(db, metric_type, hours, limit, locality_id)


@router.get("/nodes/down", response_model=list[NodeDownOut])
def get_nodes_down(
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return metrics_service.get_nodes_down(db, locality_id)


@router.get("/nodes/{node_id}/series", response_model=list[MetricPointOut])
def get_node_series(
    node_id: int,
    metric_type: str = Query(pattern=METRIC_TYPE_PATTERN),
    hours: int = Query(24, ge=1, le=8760),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return metrics_service.get_node_series(db, node_id, metric_type, hours)


@router.get("/nodes/{node_id}/latest")
def get_node_latest(
    node_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return metrics_service.get_node_latest(db, node_id)
