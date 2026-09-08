"""Schémas de la page Interopérabilité."""
from __future__ import annotations

from pydantic import BaseModel


class ToolStatusOut(BaseModel):
    tool: str
    # ok | error | stale | not_configured | unknown
    state: str
    detail: str
    ok: bool | None = None
    last_run_at: str | None = None
    nb_nodes: int | None = None
    nb_incidents: int | None = None
    nb_metrics: int | None = None
    nodes_supervised: int = 0
    incidents_this_month: int = 0


class InteropStatusResponse(BaseModel):
    generated_at: str
    interval_seconds: int
    tools_total: int
    tools_healthy: int
    tools: list[ToolStatusOut]
