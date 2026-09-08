"""
Schémas des incidents.

Les motifs de validation (`pattern`) reprennent le vocabulaire NORMALISÉ
produit par la vue v_incident, pas les valeurs brutes des outils : un
filtre `severity=critical` doit fonctionner quel que soit l'outil qui a
remonté l'incident.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

SEVERITY_PATTERN = "^(critical|high|medium|low|info|unknown)$"
STATUS_PATTERN = "^(open|acknowledged|resolved|closed)$"


class IncidentOut(BaseModel):
    id: int
    source_tool: str
    external_id: str | None = None
    node_id: int | None = None
    node_code: str
    node_name: str
    locality_id: int | None = None
    locality: str
    region: str | None = None
    ministry: str | None = None
    severity: str
    status: str
    description: str | None = None
    cause_category: str | None = None
    cause_label: str | None = None
    detected_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    mtta_minutes: float | None = None
    mttr_minutes: float | None = None
    downtime_minutes: float | None = None
    itop_ticket_ref: str | None = None
    is_maintenance: bool = False
    assigned_to_user_id: int | None = None
    assigned_to_full_name: str | None = None
    escalation_level: int = 0
    impact_scope: int = 1
    incident_type: str | None = None
    reopened_count: int = 0
    age_minutes: int | None = None


class IncidentTimelineEntry(BaseModel):
    id: int
    user_id: int | None = None
    user_full_name: str | None = None
    action: str
    note: str | None = None
    created_at: datetime


class IncidentDetail(IncidentOut):
    timeline: list[IncidentTimelineEntry] = Field(default_factory=list)


class IncidentWorkloadOut(BaseModel):
    """Charge d'un intervenant. `user_id` nul = incidents non assignés."""

    user_id: int | None = None
    full_name: str
    username: str | None = None
    role: str | None = None
    open_incidents: int
    critical: int
    high: int
    unacknowledged: int
    avg_age_minutes: float | None = None
    oldest_age_minutes: float | None = None


class IncidentListResponse(BaseModel):
    items: list[IncidentOut]
    total: int
    page: int
    page_size: int
    pages: int


class ManualIncidentPayload(BaseModel):
    """Signalement humain d'une panne non détectée par les outils.

    Écrit dans fact_incident avec source_tool='manual' — voir
    services/incident_service.create_manual pour l'explication de
    l'absence de collision avec l'ETL.
    """

    node_code: str = Field(min_length=1, max_length=200)
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    description: str = Field(min_length=1, max_length=2000)
    cause_category: str | None = None
    cause_label: str | None = None  # accepté pour compatibilité frontend, non persisté


class ResolvePayload(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


class AssignPayload(BaseModel):
    assigned_to_user_id: int
    note: str | None = Field(default=None, max_length=1000)


class EscalatePayload(BaseModel):
    escalated_to_user_id: int
    reason: str = Field(min_length=1, max_length=1000)


class CommentPayload(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
