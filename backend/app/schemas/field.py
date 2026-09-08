"""Schémas des interventions terrain."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FieldInterventionCreate(BaseModel):
    node_id: int
    incident_id: int | None = None
    scheduled_at: datetime | None = None


class FieldInterventionStatusUpdate(BaseModel):
    status: str = Field(pattern="^(scheduled|en_route|on_site|done|cancelled)$")


class FieldInterventionReport(BaseModel):
    report_text: str = Field(min_length=1, max_length=4000)
    checkin_latitude: float | None = None
    checkin_longitude: float | None = None
    photo_urls: list[str] = Field(default_factory=list, max_length=20)


class FieldInterventionOut(BaseModel):
    id: int
    incident_id: int | None = None
    node_id: int
    node_name: str
    locality: str
    agent_user_id: int
    agent_full_name: str | None = None
    status: str
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    checkin_latitude: float | None = None
    checkin_longitude: float | None = None
    report_text: str | None = None
    photo_urls: list[str] = []
    created_at: datetime | None = None
