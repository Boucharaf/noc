"""Schémas transverses."""
from __future__ import annotations

from pydantic import BaseModel


class Period(BaseModel):
    month: int
    year: int
    label: str


class Paginated[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
