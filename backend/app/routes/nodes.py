"""
Inventaire des équipements — niveau 4 de l'architecture métier.

Distinct de /api/kpi/nodes, qui répond à « les 10 équipements les plus
incidentés du mois ». Ici on parcourt le parc entier avec les filtres
d'un exploitant (site, ministère, type, outil, état) et on obtient l'état
courant, pas un agrégat mensuel.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.nodes import (
    NODE_SORT_PATTERN,
    NODE_STATE_PATTERN,
    NodeDetailOut,
    NodeIncidentOut,
    NodeListResponse,
    NodeStateCounts,
)
from app.services import node_service

router = APIRouter(
    prefix="/api/nodes",
    tags=["équipements"],
    dependencies=[Depends(read_rate_limit)],
)


@router.get("", response_model=NodeListResponse)
def list_nodes(
    q: str | None = Query(None, max_length=200, description="Nom ou adresse IP, recherche partielle"),
    locality_id: int | None = None,
    region_id: int | None = None,
    ministry_id: int | None = None,
    node_type: str | None = None,
    source_tool: str | None = None,
    state: str | None = Query(None, pattern=NODE_STATE_PATTERN),
    sort: str = Query("state", pattern=NODE_SORT_PATTERN),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return node_service.list_nodes(
        db,
        q=q,
        locality_id=locality_id,
        region_id=region_id,
        ministry_id=ministry_id,
        node_type=node_type,
        source_tool=source_tool,
        state=state,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/states", response_model=NodeStateCounts)
def count_states(
    locality_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Répartition du parc par état, pour l'en-tête des vues parc."""
    return node_service.count_by_state(db, locality_id)


@router.get("/{node_id}", response_model=NodeDetailOut)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return node_service.get_node(db, node_id)


@router.get("/{node_id}/incidents", response_model=list[NodeIncidentOut])
def get_node_incidents(
    node_id: int,
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return node_service.get_node_incidents(db, node_id, limit)
