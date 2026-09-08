"""Schémas de la couverture de supervision."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class CoverageLocalityOut(BaseModel):
    locality_id: int | None = None
    locality: str
    region_id: int | None = None
    region: str
    ministry_id: int | None = None
    ministry: str
    total_assets: int
    monitored_assets: int
    unmonitored_assets: int
    coverage_pct: float | None = None


class CoverageSummaryOut(BaseModel):
    as_of: date
    source: str
    # False tant qu'aucun inventaire théorique complet n'alimente dim_node :
    # le taux reflète alors le parc vu par les outils, pas le parc réel.
    is_complete_inventory: bool
    total_assets: int
    monitored_assets: int
    unmonitored_assets: int
    coverage_pct: float | None = None
    by_locality: list[CoverageLocalityOut]


class CoverageTrendPoint(BaseModel):
    date: date
    total_assets: int
    monitored_assets: int
    coverage_pct: float | None = None
