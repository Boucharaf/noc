"""
Routes d'exploitation : maintenances et interventions (lues dans iTop et
Zabbix), engagements de service, agrégats journaliers.

TOUT CE QUE MONTRE LE NOC VIENT DES OUTILS. Le NOC n'écrit en base que ses
paramètres (objectifs SLA), ses comptes et son journal d'audit ; il ne crée,
n'acquitte ni ne résout aucune alerte ou incident — cela se fait dans l'outil
source ou dans iTop.

RÈGLE DE DROITS. Lire est ouvert à tous les rôles authentifiés ; modifier un
objectif SLA est réservé au Directeur et au Chef NOC.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.services import audit_service, kpi_service, maintenance_service, sla_service

router = APIRouter(prefix="/api", tags=["exploitation"])


class SlaTargetIn(BaseModel):
    tta_target_minutes: int | None = Field(None, ge=1, le=10080)
    ttr_target_minutes: int | None = Field(None, ge=1, le=43200)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
# Un Annotated et non un même objet Query() partagé : FastAPI lierait alors
# les quatre paramètres au même nom d'URL (region=… filtrerait aussi province
# et site).
Place = Annotated[str | None, Query(max_length=200)]


@router.get("/maintenance")
async def list_maintenance(
    scope: str = Query("all", pattern="^(all|active|upcoming|past)$"),
    region: Place = None,
    province: Place = None,
    site: Place = None,
    search: Place = None,
    current_user: User = Depends(get_current_user),
):
    """Maintenances planifiées, lues dans iTop (changements) et Zabbix.
    Lecture seule : elles se planifient dans ces outils."""
    return await maintenance_service.list_windows(scope, region, province, site, search)


@router.get("/interventions")
async def list_interventions(
    status: str = Query("all", pattern="^(all|open|closed)$"),
    region: Place = None,
    province: Place = None,
    site: Place = None,
    search: Place = None,
    current_user: User = Depends(get_current_user),
):
    """Interventions : ordres de travail iTop. Lecture seule : elles
    s'affectent et se clôturent dans iTop."""
    return await maintenance_service.list_work_orders(status, region, province, site, search)


# ---------------------------------------------------------------------------
# Engagements de service
# ---------------------------------------------------------------------------
@router.get("/sla/targets")
def sla_targets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return sla_service.list_targets(db)


@router.put("/sla/targets/{severity}")
def update_sla_target(
    severity: str,
    body: SlaTargetIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("directeur", "chef_noc")),
):
    if severity not in SEVERITIES:
        raise HTTPException(400, f"Gravité inconnue : {severity}")
    before = next(
        (row for row in sla_service.list_targets(db) if row["severity"] == severity), {}
    )
    updated = sla_service.update_target(
        db,
        severity,
        body.tta_target_minutes,
        body.ttr_target_minutes,
    )
    audit_service.record(
        db, "sla.target_updated", actor=current_user, target=severity,
        detail={
            field: {"from": before.get(field), "to": updated[field]}
            for field in ("tta_target_minutes", "ttr_target_minutes")
            if before.get(field) != updated[field]
        },
        request=request,
    )
    return updated


# ---------------------------------------------------------------------------
# Tendances (agrégats journaliers)
# ---------------------------------------------------------------------------
@router.get("/kpi/trend")
def kpi_trend(
    days: int = Query(30, ge=1, le=730),
    region: str | None = Query(None, max_length=200),
    province: str | None = Query(None, max_length=200),
    site: str | None = Query(None, max_length=150),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tendance journalière du périmètre (site, province, région ou réseau)."""
    return kpi_service.trend(db, days, kpi_service.rollup_key(region, province, site))


@router.get("/kpi/monthly")
def kpi_monthly(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    region: str | None = Query(None, max_length=200),
    province: str | None = Query(None, max_length=200),
    site: str | None = Query(None, max_length=150),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return kpi_service.monthly_summary(
        db, year, month, kpi_service.rollup_key(region, province, site)
    )


@router.get("/kpi/sites")
async def kpi_sites(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    sort: str = Query("availability", pattern="^(availability|alerts)$"),
    region: str | None = Query(None, max_length=200),
    province: str | None = Query(None, max_length=200),
    site: str | None = Query(None, max_length=150),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classement des sites, restreint aux sites du périmètre demandé."""
    sites = None
    if region or province or site:
        from app.services import geo_service

        nodes, _alerts, _incidents = await geo_service.scoped(
            db, region=region, province=province, site=site
        )
        sites = {node["site"] for node in nodes if node.get("site")}
    return kpi_service.sites_ranking(db, days, limit, sort, sites=sites)
