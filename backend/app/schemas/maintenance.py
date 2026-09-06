# ---------------------------------------------------------------------------
# maintenance.py (nouveau)
# ---------------------------------------------------------------------------

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MaintenanceWindowCreate(BaseModel):
    node_id: Optional[int] = None
    locality_id: Optional[int] = None
    reason: str
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool = True


class MaintenanceWindowOut(MaintenanceWindowCreate):
    id: int
    created_by_user_id: Optional[int] = None
    source_tool: Optional[str] = None
    external_id: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Import automatique depuis l'ETL (Zabbix/Centreon/NetXMS maintenance mode) —
# distinct de MaintenanceWindowCreate qui suppose un opérateur humain
# (created_by_user_id). Voir models/dimension.py::MaintenanceWindow et le
# CHECK chk_maintenance_origin en base.
# ---------------------------------------------------------------------------


class MaintenanceWindowImportPayload(BaseModel):
    node_code: str
    source_tool: str
    external_id: str
    reason: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class MaintenanceWindowBulkImportPayload(BaseModel):
    windows: list[MaintenanceWindowImportPayload] = Field(default_factory=list, max_length=5000)


class MaintenanceWindowBulkImportResponse(BaseModel):
    received: int
    created: int
    updated: int
    unknown_node: int