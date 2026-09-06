from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AssetSyncPayload(BaseModel):
    itop_ci_id: str
    name: str
    asset_type: Optional[str] = None
    org_name: Optional[str] = None
    location_name: Optional[str] = None


class AssetBulkSyncPayload(BaseModel):
    assets: list[AssetSyncPayload] = Field(..., max_length=20000)


class AssetBulkSyncResponse(BaseModel):
    received: int
    created: int
    updated: int
    matched_to_node: int


class CoverageOut(BaseModel):
    locality_id: int
    locality: str
    region_id: int
    region: str
    total_assets: int
    monitored_assets: int
    unmonitored_assets: int
    coverage_pct: Optional[float] = None


class CoverageSummaryOut(BaseModel):
    total_assets: int
    monitored_assets: int
    unmonitored_assets: int
    coverage_pct: Optional[float] = None
    by_locality: list[CoverageOut]
    last_synced_at: Optional[datetime] = None
