"""
Routes territoriales et incidents.

  /api/geo/*        lecture région -> province -> site -> nœud (instantané Redis)
  /api/incidents*   incidents iTop, enrichis par les alertes des outils
  /api/sla/incidents  respect des engagements, ventilé par territoire —
                    ⚠️ interroge iTop (tickets résolus), avec cache court
  /api/sla/at-risk  incidents ouverts qui vont manquer leur objectif
  /api/kpi/incidents  volumes, récurrence, causes, organisations — même
                    source que /sla/incidents

Les filtres de périmètre (`region`, `province`, `site`, `search`) ont le même
sens partout : voir app/services/geo_service.py.
"""
from __future__ import annotations

import logging

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.routes.live import _one_of, _unavailable
from app.services import geo_service, incident_service, live_service, search_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["territoire et incidents"])

# Mêmes rôles que l'ancien historique d'incidents (frontend : VIEW_INCIDENTS).
_VIEW_INCIDENTS = ("directeur", "chef_noc", "technicien")

Place = Annotated[str | None, Query(max_length=200)]
Search = Annotated[str | None, Query(max_length=200)]


@router.get("/geo/options")
async def geo_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await geo_service.options(db)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/geo/breakdown")
async def geo_breakdown(
    region: Place = None,
    province: Place = None,
    site: Place = None,
    search: Search = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await geo_service.breakdown(db, region, province, site, search)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/geo/sites/{site:path}")
async def geo_site(
    site: Annotated[str, Path(min_length=1, max_length=200)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        detail = await geo_service.site_detail(db, site)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    if detail is None:
        raise HTTPException(404, "Site inconnu dans l'instantané")
    return detail


@router.get("/search/suggest")
async def search_suggest(
    q: Annotated[str, Query(min_length=1, max_length=100)],
    kinds: str | None = Query(None, max_length=200),
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggestions pendant la frappe, lues dans l'instantané.
    `kinds` : liste séparée par des virgules parmi search_service.KINDS."""
    wanted = tuple(k for k in (kinds or "").split(",") if k in search_service.KINDS) or search_service.KINDS
    try:
        return await search_service.suggest(db, q, wanted, limit)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/incidents")
async def list_incidents(
    region: Place = None,
    province: Place = None,
    site: Place = None,
    search: Search = None,
    severity: str | None = Query(None, pattern=_one_of(SEVERITIES)),
    status: str | None = Query(None, max_length=40),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_VIEW_INCIDENTS)),
):
    try:
        return await incident_service.list_incidents(
            db, region, province, site, search, severity, status, limit, offset
        )
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


def _itop_unavailable(exc: incident_service.IncidentsUnavailable) -> HTTPException:
    logger.warning("Historique iTop indisponible : %s", exc.detail)
    return HTTPException(
        status_code=503,
        detail={
            "error": "itop_unavailable",
            "message": "iTop n'a pas pu fournir l'historique des incidents. Réessayer plus tard.",
        },
    )


# Déclarée AVANT /incidents/{key:path}, qui capturerait « history ».
@router.get("/incidents/history")
async def incident_history(
    days: int = Query(30, ge=1, le=365),
    region: Place = None,
    province: Place = None,
    site: Place = None,
    search: Search = None,
    severity: str | None = Query(None, pattern=_one_of(SEVERITIES)),
    status: str | None = Query(None, max_length=40),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_VIEW_INCIDENTS)),
):
    try:
        return await incident_service.incident_history(
            db, days, region, province, site, search, severity, status, offset, limit
        )
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    except incident_service.IncidentsUnavailable as exc:
        raise _itop_unavailable(exc) from exc


@router.get("/incidents/{key:path}")
async def get_incident(
    key: Annotated[str, Path(min_length=1, max_length=300)],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_VIEW_INCIDENTS)),
):
    try:
        incident = await incident_service.get_incident(db, key)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    if incident is None:
        raise HTTPException(404, "Incident introuvable (clos ou absent de l'instantané)")
    return incident


@router.get("/sla/incidents")
async def sla_incidents(
    group_by: str = Query("region", pattern=_one_of(incident_service.GROUP_LEVELS)),
    days: int = Query(30, ge=1, le=365),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    region: Place = None,
    province: Place = None,
    site: Place = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await incident_service.sla_by_group(
            db, group_by, days, start_at, end_at, region, province, site
        )
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    except incident_service.IncidentsUnavailable as exc:
        raise _itop_unavailable(exc) from exc


@router.get("/sla/at-risk")
async def sla_at_risk(
    region: Place = None,
    province: Place = None,
    site: Place = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Incidents iTop ouverts qui vont manquer leur objectif de résolution.

    Le plus utile des indicateurs SLA : les autres racontent le passé, celui-ci
    laisse encore le temps d'agir. Lu sur l'instantané, sans appel à iTop.
    """
    try:
        return await incident_service.at_risk(db, region, province, site)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/sla/contract")
async def sla_contract(current_user: User = Depends(get_current_user)):
    """Engagements de service (SLT) déclarés dans iTop — lus chez iTop, cache
    de 5 minutes. Affichés à côté des objectifs du NOC, sans les remplacer."""
    try:
        return await incident_service.contract_targets()
    except incident_service.IncidentsUnavailable as exc:
        raise _itop_unavailable(exc) from exc


@router.get("/kpi/incidents")
async def kpi_incidents(
    days: int = Query(30, ge=1, le=365),
    region: Place = None,
    province: Place = None,
    site: Place = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await incident_service.incident_kpis(db, days, region, province, site)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    except incident_service.IncidentsUnavailable as exc:
        raise _itop_unavailable(exc) from exc
