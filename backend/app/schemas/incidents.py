from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IncidentIngestPayload(BaseModel):
    external_id: str
    source_tool: str = Field(pattern="^(zabbix|nagios|netxms|centreon)$")
    node_code: str
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    status: str = Field(default="open", pattern="^(open|acknowledged|resolved|closed)$")
    detected_at: datetime
    description: Optional[str] = None
    cause_category: Optional[str] = None
    cause_label: Optional[str] = None


class IncidentIngestResponse(BaseModel):
    incident_id: int
    node_id: int
    itop_ticket_id: Optional[str] = None
    shift: Optional[str] = None
    created_at: datetime


class ResolvePayload(BaseModel):
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None


class AcknowledgePayload(BaseModel):
    acknowledged_at: Optional[datetime] = None


class IncidentOut(BaseModel):
    id: int
    node_code: str
    node_name: str
    locality: str
    severity: str
    status: str
    description: Optional[str] = None
    detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    mttr_minutes: Optional[int] = None
    shift: Optional[str] = None
    source_tool: str
    itop_ticket_id: Optional[str] = None
    age_minutes: Optional[int] = None

    class Config:
        from_attributes = True
