# ---------------------------------------------------------------------------
# maintenance.py (nouveau)
# ---------------------------------------------------------------------------

import datetime
from typing import Optional

from pydantic import BaseModel


class MaintenanceWindowCreate(BaseModel):
    node_id: Optional[int] = None
    locality_id: Optional[int] = None
    reason: str
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool = True


class MaintenanceWindowOut(MaintenanceWindowCreate):
    id: int
    created_by_user_id: int

    class Config:
        from_attributes = True