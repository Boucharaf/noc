"""
Routes d'exploitation — ce que le NOC écrit.

Acquittements, affectations, causes, incidents signalés à la main, fenêtres
de maintenance, engagements de service. Tout ce qui atterrit dans
PostgreSQL, par opposition aux routes de `live.py` qui ne font que lire
l'instantané.

RÈGLE DE DROITS. Lire est ouvert à tous les rôles authentifiés ; écrire
demande au moins le rôle « technicien ». Un agent de terrain peut signaler
un incident et rendre compte de son intervention, mais ne modifie ni les
engagements de service ni les fenêtres de maintenance — ce sont des
décisions d'exploitation, pas des constats.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.services import (
    kpi_service,
    maintenance_service,
    notification_service,
    sla_service,
)

router = APIRouter(prefix="/api", tags=["exploitation"])

# Rôles autorisés à écrire. `agent_terrain` en est exclu pour les décisions
# d'exploitation, mais reste autorisé sur les routes de terrain (field.py).
WRITERS = ("directeur", "chef_noc", "technicien")

# ANCRÉ : sans ^…$, pydantic accepte toute chaîne qui CONTIENT une gravité
# (« xxcriticalxx »), et elle serait enregistrée telle quelle.
_SEVERITY_PATTERN = "^(" + "|".join(SEVERITIES) + ")$"



# ---------------------------------------------------------------------------
# Corps de requête
# ---------------------------------------------------------------------------
class ManualIncidentIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    severity: str = Field("medium", pattern=_SEVERITY_PATTERN)
    description: str | None = Field(None, max_length=4000)
    node_key: str | None = Field(None, max_length=300)
    node_name: str | None = Field(None, max_length=300)
    site: str | None = Field(None, max_length=150)


class SlaTargetIn(BaseModel):
    tta_target_minutes: int | None = Field(None, ge=1, le=10080)
    ttr_target_minutes: int | None = Field(None, ge=1, le=43200)


def _validate_manual_incident_site(
    role: str, assigned_site: str | None, requested_site: str
) -> None:
    if role != "agent_terrain":
        return
    if not assigned_site:
        raise HTTPException(
            403,
            "Aucun site n'est affecté à ce compte agent terrain.",
        )
    if requested_site != assigned_site:
        raise HTTPException(
            403,
            "Un agent terrain ne peut signaler un incident que sur son site.",
        )


# Les alertes des outils sont en LECTURE SEULE dans le NOC : plus
# d'acquittement, d'affectation, de résolution ni de note. Le traitement et
# les affectations sont tenus dans iTop (écran Incidents iTop) ; le NOC montre
# les caractéristiques techniques des alertes, il ne double pas l'ITSM.


# ---------------------------------------------------------------------------
# Incidents signalés à la main
# ---------------------------------------------------------------------------
@router.post("/manual-incidents", status_code=201)
def create_manual_incident(
    body: ManualIncidentIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    # Ouvert aux agents de terrain : ce sont eux qui constatent les pannes
    # qu'aucune sonde ne voit.
    current_user: User = Depends(require_role(*WRITERS, "agent_terrain")),
):
    from app.models import ManualIncident

    _validate_manual_incident_site(
        current_user.role, current_user.site, body.site
    )

    incident = ManualIncident(
        title=body.title,
        severity=body.severity,
        description=body.description,
        node_key=body.node_key,
        node_name=body.node_name,
        site=body.site,
        created_by=current_user.id,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    # Aucune sonde ne verra jamais cet incident : sans cet appel, une panne
    # grave signalée du terrain n'arriverait dans aucune boîte. Le filtre de
    # gravité (NOTIFY_SEVERITIES) est appliqué par le service.
    background.add_task(
        notification_service.notify_manual_incident,
        incident_id=incident.id,
        title=incident.title,
        severity=incident.severity,
        description=incident.description,
        node_name=incident.node_name,
        site=incident.site,
        reported_by=current_user.full_name or current_user.username,
    )
    return {
        "id": incident.id,
        "alert_key": incident.alert_key(),
        "title": incident.title,
        "severity": incident.severity,
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
    }


@router.post("/manual-incidents/{incident_id}/resolve")
def resolve_manual_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*WRITERS, "agent_terrain")),
):
    from datetime import timezone

    from app.models import ManualIncident

    incident = db.get(ManualIncident, incident_id)
    if incident is None:
        raise HTTPException(404, "Incident manuel introuvable.")
    if current_user.role == "agent_terrain" and incident.created_by != current_user.id:
        raise HTTPException(404, "Incident manuel introuvable.")
    incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": incident.id, "resolved_at": incident.resolved_at.isoformat()}


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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("directeur", "chef_noc")),
):
    if severity not in SEVERITIES:
        raise HTTPException(400, f"Gravité inconnue : {severity}")
    return sla_service.update_target(
        db,
        severity,
        body.tta_target_minutes,
        body.ttr_target_minutes,
    )


@router.get("/sla/compliance")
def sla_compliance(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return sla_service.compliance(db, days)


@router.get("/sla/breaches")
def sla_breaches(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return sla_service.breaches(db, days, limit)


@router.get("/sla/at-risk")
async def sla_at_risk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alertes en cours qui vont manquer leur objectif.

    Le plus utile des trois indicateurs SLA : les deux autres racontent le
    passé, celui-ci laisse encore le temps d'agir.
    """
    return await sla_service.at_risk(db)


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


@router.get("/kpi/causes")
def kpi_causes(
    days: int = Query(90, ge=1, le=730),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Causes retenues par les exploitants.

    La seule donnée d'analyse dont le NOC est propriétaire : aucun outil de
    supervision ne la connaît.
    """
    return kpi_service.causes(db, days)


@router.get("/kpi/resolution-times")
def kpi_resolution_times(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return kpi_service.resolution_times(db, days)
