"""Service-level contracts for the current Redis + PostgreSQL architecture."""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.routes import report as report_routes  # noqa: E402
from app.services import kpi_service, live_service  # noqa: E402
from app.dependencies.auth import require_internal_key  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402


def test_monthly_trend_has_exclusive_next_month_bound(monkeypatch):
    received = {}

    def capture(_db, **kwargs):
        received.update(kwargs)
        return []

    monkeypatch.setattr(kpi_service, "trend", capture)
    assert kpi_service.monthly_trend(object(), 2024, 2) == []
    assert received == {
        "site": None,
        "start_at": date(2024, 2, 1),
        "end_at": date(2024, 3, 1),
    }


def test_organisation_summary_counts_unknown_and_maintenance_nodes():
    nodes = [
        {"organisation": "Ministry A", "state": "up", "alerts": 1},
        {"organisation": "Ministry A", "state": "unknown", "alerts": 2},
        {"organisation": "Ministry A", "state": "maintenance", "alerts": 0},
    ]

    result = asyncio.run(live_service.summarise_organisations(nodes))

    assert result[0]["nodes"] == 3
    assert result[0]["up"] == result[0]["unknown"] == result[0]["maintenance"] == 1
    assert result[0]["availability_pct"] == 50.0
    assert result[0]["alerts"] == 3


def test_internal_monthly_report_route_requires_internal_api_key():
    route = next(
        route
        for route in report_routes.internal_router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/internal/reports/monthly"
    )

    assert any(dependency.call is require_internal_key for dependency in route.dependant.dependencies)


def test_internal_api_key_rejects_missing_or_invalid_credentials(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from app.dependencies import auth

    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "")
    with pytest.raises(HTTPException) as not_configured:
        auth.require_internal_key()
    assert not_configured.value.status_code == 503

    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "test-internal-key")
    with pytest.raises(HTTPException) as missing:
        auth.require_internal_key(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as invalid:
        auth.require_internal_key(
            HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="incorrect-key"
            )
        )
    assert invalid.value.status_code == 401

    assert (
        auth.require_internal_key(
            HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="test-internal-key"
            )
        )
        is None
    )
