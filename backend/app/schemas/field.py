"""Schémas pour les interventions terrain."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FieldInterventionCreate(BaseModel):
    incident_id: Optional[int] = None
    node_id: int
    scheduled_at: Optional[datetime] = None


class FieldInterventionReport(BaseModel):
    checkin_latitude: float
    checkin_longitude: float
    report_text: str
    photo_urls: list[str] = Field(default_factory=list)


class FieldInterventionOut(BaseModel):
    id: int
    incident_id: Optional[int] = None
    node_id: int
    node_name: str
    status: str
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    report_text: Optional[str] = None

    class Config:
        from_attributes = True


class FieldInterventionStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(en_route|on_site|done|cancelled)$")


