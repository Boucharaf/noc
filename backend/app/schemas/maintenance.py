"""Schémas des fenêtres de maintenance."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MaintenanceWindowCreate(BaseModel):
    node_id: int | None = None
    locality_id: int | None = None
    reason: str = Field(min_length=1, max_length=1000)
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool = True


class MaintenanceWindowOut(BaseModel):
    id: int
    node_id: int | None = None
    node_name: str | None = None
    locality_id: int | None = None
    locality_name: str | None = None
    reason: str
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool
    created_by_user_id: int | None = None
    created_by_full_name: str | None = None
    source_tool: str | None = None
    external_id: str | None = None
    created_at: datetime | None = None
    is_active: bool = False


class MaintenanceWindowImport(BaseModel):
    """Import depuis l'ETL (mode maintenance Zabbix, downtime Centreon…).

    `node_code` est rapproché du NOM de l'équipement : dim_node n'a pas de
    colonne code.
    """

    node_code: str
    source_tool: str
    external_id: str
    reason: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class MaintenanceWindowBulkImport(BaseModel):
    windows: list[MaintenanceWindowImport] = Field(default_factory=list, max_length=5000)


class MaintenanceWindowBulkImportResponse(BaseModel):
    received: int
    created: int
    updated: int
    unknown_node: int
