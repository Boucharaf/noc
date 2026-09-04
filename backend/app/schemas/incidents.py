from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schémas de base (ingestion ETL / webhooks) — reconstitués : le fichier collé
# ici ne contenait que l'extension "assignation / escalade" ci-dessous, avec
# un commentaire indiquant explicitement que les schémas de base existaient
# déjà ailleurs et ne devaient pas être touchés. Ils manquaient en réalité :
# app/routes/incidents.py et app/services/incident_service.py les importent
# tous les deux, donc leur absence empêchait le backend de démarrer. Recréés
# à partir de l'usage réel qu'en font routes/incidents.py et
# services/incident_service.py.
# ---------------------------------------------------------------------------


class IncidentIngestPayload(BaseModel):
    node_code: str
    # Outils sources connus (voir etl/extract/*.py) + "manual" pour les
    # signalements humains créés depuis /api/incidents/manual. Toute autre
    # valeur (ex. un outil non intégré) doit être rejetée à l'entrée plutôt
    # que de polluer discrètement les KPI par source_tool.
    source_tool: str = Field(
        ..., pattern="^(zabbix|nagios|centreon|netxms|nsp|itop|manual)$"
    )
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    status: str = Field("open", pattern="^(open|acknowledged|resolved|closed)$")
    detected_at: datetime
    description: Optional[str] = None
    external_id: Optional[str] = None
    itop_ticket_id: Optional[str] = None
    cause_category: Optional[str] = None
    cause_label: Optional[str] = None

    # Champs supplémentaires envoyés par certains collecteurs (voir
    # etl/transform/normalize.py) mais pas encore exploités par
    # incident_service.ingest_incident — acceptés ici pour ne pas rejeter le
    # payload, sans effet tant que le service ne les persiste pas.
    acknowledged_at: Optional[datetime] = None
    workflow_status: Optional[str] = None
    origin_source_tool: Optional[str] = None
    origin_external_id: Optional[str] = None
    sla_ttr_deadline: Optional[datetime] = None
    sla_breached: Optional[bool] = None


class IncidentIngestResponse(BaseModel):
    incident_id: int
    node_id: int
    itop_ticket_id: Optional[str] = None
    shift: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IncidentBulkIngestPayload(BaseModel):
    # Le plus gros lot réel est NetXMS (~1500 alarmes actives, voir
    # etl/extract/netxms.py) ; 5000 laisse de la marge sans permettre à un
    # appelant mal configuré d'envoyer un payload arbitrairement lourd.
    incidents: list[IncidentIngestPayload] = Field(..., max_length=5000)


class IncidentBulkIngestResponse(BaseModel):
    received: int
    created: int
    duplicates: int
    unknown_node: int
    resolved: int


class AcknowledgePayload(BaseModel):
    acknowledged_at: Optional[datetime] = None


class ResolvePayload(BaseModel):
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# incidents.py (extension — flux d'assignation / escalade)
# ---------------------------------------------------------------------------

class IncidentAssignPayload(BaseModel):
    assigned_to_user_id: int
    note: Optional[str] = None


class IncidentEscalatePayload(BaseModel):
    escalated_to_user_id: int
    reason: str


class IncidentTimelineEntryOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_full_name: Optional[str] = None
    action: str
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IncidentOutExtended(BaseModel):
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
    # --- ajouts ---
    assigned_to_user_id: Optional[int] = None
    assigned_to_full_name: Optional[str] = None
    escalation_level: int = 0
    sla_breached: bool = False
    impact_scope: int = 1
    incident_type: Optional[str] = None
    reopened_count: int = 0

    class Config:
        from_attributes = True

# --- À ajouter dans app/schemas/incidents.py, à côté des schémas existants ---
# (IncidentIngestPayload, IncidentBulkIngestPayload, etc. dont je n'ai pas le
# contenu exact — n'y touchez pas, ajoutez seulement ce qui suit.)


class ManualIncidentPayload(BaseModel):
    node_code: str
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    description: str = Field(..., min_length=1, max_length=2000)
    cause_category: str | None = None
    cause_label: str | None = None


class IncidentListItem(BaseModel):
    id: int
    node_id: int
    node_code: str
    node_name: str
    locality_id: int
    severity: str
    status: str
    source_tool: str
    description: str | None
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    itop_ticket_id: str | None
    external_id: str | None


class IncidentListResponse(BaseModel):
    items: list[IncidentListItem]
    total: int
    page: int
    page_size: int
    pages: int
