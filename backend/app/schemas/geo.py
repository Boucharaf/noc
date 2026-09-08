"""Schémas du référentiel géographique et des listes de valeurs."""
from __future__ import annotations

from pydantic import BaseModel


class RegionOut(BaseModel):
    id: int
    code: str | None = None
    name: str
    nb_localities: int = 0
    nb_nodes: int = 0


class LocalityOut(BaseModel):
    id: int
    code: str | None = None
    name: str
    region_id: int | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nb_nodes: int = 0


class MinistryOut(BaseModel):
    id: int
    name: str
    external_ref: str | None = None
    nb_nodes: int = 0


class CauseRefOut(BaseModel):
    category: str
    label: str | None = None


class ReferenceOut(BaseModel):
    regions: list[RegionOut] = []
    localities: list[LocalityOut] = []
    ministries: list[MinistryOut] = []
    node_types: list[str] = []
    source_tools: list[str] = []
    causes: list[CauseRefOut] = []
