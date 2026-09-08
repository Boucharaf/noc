"""Schémas du mur d'alertes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: int
    node_id: int | None = None
    node_code: str
    node_name: str
    locality_id: int | None = None
    locality: str
    severity: str
    status: str
    source_tool: str
    description: str | None = None
    cause_category: str | None = None
    cause_label: str | None = None
    detected_at: datetime | None = None
    acknowledged_at: datetime | None = None
    assigned_to_user_id: int | None = None
    assigned_to_full_name: str | None = None
    age_minutes: int | None = None


class AlertSummaryOut(BaseModel):
    """Bandeau d'état permanent — voir alerts_service.get_summary."""

    total_open: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    unacknowledged: int = 0
    unassigned: int = 0
    escalated: int = 0
    ageing: int = 0
    nodes_affected: int = 0
    localities_affected: int = 0
    opened_last_hour: int = 0
    resolved_last_hour: int = 0
    oldest_unacknowledged_at: datetime | None = None


class RecentAlertOut(BaseModel):
    id: int
    node_code: str
    node_name: str
    locality: str
    severity: str
    status: str
    source_tool: str
    description: str | None = None
    detected_at: datetime | None = None
    age_minutes: int | None = None
