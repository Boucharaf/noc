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

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models import User
from app.services import (
    alerts_service,
    kpi_service,
    maintenance_service,
    notification_service,
    sla_service,
)

router = APIRouter(prefix="/api", tags=["exploitation"])

# Rôles autorisés à écrire. `agent_terrain` en est exclu pour les décisions
# d'exploitation, mais reste autorisé sur les routes de terrain (field.py).
WRITERS = ("directeur", "chef_noc", "technicien")


# ---------------------------------------------------------------------------
# Corps de requête
# ---------------------------------------------------------------------------
class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=2000)


class AssignIn(BaseModel):
    assignee_id: int
    note: str | None = Field(None, max_length=2000)


class ResolveIn(BaseModel):
    # La cause est ce que le NOC apporte de plus précieux : aucun outil de
    # supervision ne sait qu'une coupure venait d'un groupe électrogène à
    # sec. Elle n'est pas obligatoire — forcer une saisie produirait des
    # « autre » à la chaîne, ce qui est pire que rien.
    cause: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=2000)


class ManualIncidentIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    severity: str = Field("medium", pattern="|".join(SEVERITIES))
    description: str | None = Field(None, max_length=4000)
    node_key: str | None = None
    node_name: str | None = None
    site: str | None = None


class MaintenanceIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    starts_at: datetime
    ends_at: datetime
    node_key: str | None = None
    site: str | None = None
    suppress_alerts: bool = True


class SlaTargetIn(BaseModel):
    tta_target_minutes: int | None = Field(None, ge=1, le=10080)
    ttr_target_minutes: int | None = Field(None, ge=1, le=43200)
    availability_target_pct: float | None = Field(None, ge=0, le=100)


# ---------------------------------------------------------------------------
# Travail sur une alerte
# ---------------------------------------------------------------------------
@router.post("/alerts/{alert_key:path}/acknowledge")
async def acknowledge(
    alert_key: str,
    body: NoteIn = Body(default=NoteIn()),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*WRITERS)),
):
    return await alerts_service.acknowledge(db, alert_key, current_user.id, body.note)


@router.post("/alerts/{alert_key:path}/assign")
async def assign(
    alert_key: str,
    body: AssignIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*WRITERS)),
):
    assignee = db.get(User, body.assignee_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(404, "Utilisateur destinataire inconnu ou désactivé.")
    return await alerts_service.assign(
        db, alert_key, current_user.id, body.assignee_id, body.note
    )


@router.post("/alerts/{alert_key:path}/resolve")
async def resolve(
    alert_key: str,
    body: ResolveIn = Body(default=ResolveIn()),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*WRITERS)),
):
    """Clôture CÔTÉ NOC.

    Ne ferme rien chez l'outil source : le NOC n'a pas à décider qu'un
    déclencheur Zabbix doit se taire. Si l'alerte reste active à la source,
    elle reste visible, marquée comme traitée — masquer une alerte encore
    active serait dangereux.
    """
    return await alerts_service.resolve(
        db, alert_key, current_user.id, body.cause, body.note
    )


@router.post("/alerts/{alert_key:path}/note")
async def add_note(
    alert_key: str,
    body: NoteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*WRITERS, "agent_terrain")),
):
    if not body.note:
        raise HTTPException(400, "Une note vide n'apporte rien au journal.")
    return await alerts_service.add_note(db, alert_key, current_user.id, body.note)


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
    incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": incident.id, "resolved_at": incident.resolved_at.isoformat()}


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
@router.get("/maintenance")
def list_maintenance(
    scope: str = Query("all", pattern="all|active|upcoming|past"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return maintenance_service.list_windows(db, scope)


@router.post("/maintenance", status_code=201)
async def create_maintenance(
    body: MaintenanceIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("directeur", "chef_noc")),
):
    return await maintenance_service.create_window(
        db,
        user_id=current_user.id,
        reason=body.reason,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        node_key=body.node_key,
        site=body.site,
        suppress_alerts=body.suppress_alerts,
    )


@router.delete("/maintenance/{window_id}", status_code=204)
def delete_maintenance(
    window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("directeur", "chef_noc")),
):
    maintenance_service.delete_window(db, window_id)


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
        body.availability_target_pct,
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
    site: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return kpi_service.trend(db, days, site)


@router.get("/kpi/monthly")
def kpi_monthly(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    site: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return kpi_service.monthly_summary(db, year, month, site)


@router.get("/kpi/sites")
def kpi_sites(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return kpi_service.sites_ranking(db, days, limit)


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
