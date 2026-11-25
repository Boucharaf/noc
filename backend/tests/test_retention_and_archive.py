"""Santé des outils, rapports figés, conservation."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from collector import retention, tool_health
from integrations.models import ToolHealth
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import HistToolHealth, ReportSnapshot
from app.services import availability_service as av
from app.services import report_archive_service as archive

T0 = datetime(2026, 10, 1, tzinfo=UTC)
CYCLE = tool_health.INTERVAL
FRESH = {"collected_at": "x", "stale": False}
STALE = {"collected_at": "x", "stale": True}


# -- Santé des outils ---------------------------------------------------------
@pytest.mark.parametrize("reachable, nodes, alerts, expected", [
    (True, FRESH, FRESH, "up"), (False, FRESH, STALE, "partial"),
    (False, STALE, STALE, "down"), (False, {"collected_at": None}, {}, "down"),
])
def test_tool_state(reachable, nodes, alerts, expected):
    health = {"zabbix": ToolHealth(tool="zabbix", reachable=reachable, error="boum")}
    row = tool_health.observed(health, {"zabbix": {"nodes": nodes, "alerts": alerts}})["zabbix"]
    assert row["state"] == expected
    assert (row["error"] is None) == (expected == "up")


def test_tool_periods_only_change_when_state_changes():
    now = T0 + CYCLE
    row = {"id": 1, "tool": "zabbix", "state": "up", "last_seen_at": T0}
    up, down = {"tool": "zabbix", "state": "up"}, {"tool": "zabbix", "state": "down"}
    assert tool_health.plan([row], {"zabbix": up}, now) == ([], [], [1])
    assert tool_health.plan([row], {"zabbix": down}, now) == ([(1, now)], [down], [])
    assert tool_health.plan([row], {}, now) == ([(1, now)], [], [])
    # Collecteur arrêté : la période s'arrête à sa dernière observation.
    late = T0 + timedelta(hours=5)
    assert tool_health.plan([row], {"zabbix": up}, late) == ([(1, T0 + CYCLE)], [up], [])


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (HistToolHealth, ReportSnapshot):
        model.__table__.create(engine)
    with sessionmaker(engine)() as session:
        yield session


def test_tool_availability_ignores_unobserved_time(db):
    def period(i, state, start_h, end_h):
        return HistToolHealth(id=i, tool="zabbix", state=state, error="e",
                              started_at=T0 + timedelta(hours=start_h),
                              ended_at=T0 + timedelta(hours=end_h),
                              last_seen_at=T0 + timedelta(hours=end_h))
    db.add_all([period(1, "up", 0, 9), period(2, "down", 9, 10), period(3, "up", 20, 30)])
    db.commit()
    tool = av.tools_health(db, start=T0, end=T0 + timedelta(hours=30))["tools"][0]
    assert tool["availability_pct"] == 95.0 and tool["observed_hours"] == 20.0
    assert tool["interruptions"] == 1 and tool["outages"][0]["minutes"] == 60.0


# -- Rapports figés -----------------------------------------------------------
NOW = datetime(2026, 11, 4, tzinfo=UTC)


@pytest.fixture
def collected(monkeypatch):
    data = {"month": 10, "year": 2026, "itop_error": None, "generated_at": T0,
            "monthly": {"current": {"days_with_data": 31, "availability_pct": 98.0}}}

    async def collect(_db, _month, _year):
        return dict(data)

    monkeypatch.setattr(archive.report_service, "collect_report_data", collect)
    monkeypatch.setattr(archive, "_pdf_bytes", lambda _data: b"%PDF-1")
    return data


def freeze(db, **kwargs):
    return asyncio.run(archive.freeze(db, 2026, 10, by="chef", **{"now": NOW, **kwargs}))


def test_frozen_report_keeps_its_numbers(db, collected):
    first = freeze(db)
    collected["monthly"] = {"current": {"days_with_data": 31, "availability_pct": 50.0}}
    _row, content = archive.read(db, first["id"], "json")
    assert json.loads(content)["monthly"]["current"]["availability_pct"] == 98.0
    assert archive.read(db, first["id"], "pdf")[1] == b"%PDF-1"
    assert archive.read(db, 999, "pdf") is None


def test_second_freeze_needs_a_reason_and_keeps_the_first(db, collected):
    freeze(db)
    with pytest.raises(archive.NotFreezable, match="motif"):
        freeze(db, reason="  ")
    assert freeze(db, reason="ticket corrigé")["revision"] == 2
    assert [r["revision"] for r in archive.list_snapshots(db)] == [2, 1]


def test_open_or_empty_month_is_refused(db, collected):
    with pytest.raises(archive.NotFreezable, match="clos"):
        freeze(db, now=datetime(2026, 10, 31, tzinfo=UTC))
    collected["monthly"] = {"current": {"days_with_data": 0}}
    with pytest.raises(archive.NotFreezable, match="Aucune"):
        freeze(db)


def test_altered_content_is_detected(db, collected):
    snapshot = freeze(db)
    db.query(ReportSnapshot).update({"pdf": b"%PDF-faux"})
    db.commit()
    db.expire_all()
    with pytest.raises(archive.Corrupted):
        archive.read(db, snapshot["id"], "pdf")


@pytest.mark.parametrize("day, itop_error, frozen, complete", [
    (2, None, False, None), (3, None, True, True), (5, "muet", False, None),
    (10, "muet", True, False), (15, None, False, None),
])
def test_automatic_freeze(monkeypatch, db, collected, day, itop_error, frozen, complete):
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: db)
    collected["itop_error"] = itop_error
    now = datetime(2026, 11, day, tzinfo=UTC)
    assert asyncio.run(archive.freeze_if_due(now)) is frozen
    rows = archive.list_snapshots(db)
    assert [(r["complete"], r["generated_by"]) for r in rows] == (
        [(complete, "automatique")] if frozen else []
    )
    assert asyncio.run(archive.freeze_if_due(now)) is False   # une seule fois


# -- Conservation -------------------------------------------------------------
def test_retention_is_off_by_default_and_refuses_short_durations(monkeypatch):
    assert retention.config.RETENTION_ENABLED is False
    assert retention.limits(T0) == {}
    assert asyncio.run(retention.run(T0)) == {}
    monkeypatch.setattr(retention.config, "RETENTION_DAYS", {
        "RETENTION_AUDIT_DAYS": 10, "RETENTION_KPI_DAYS": 3650,
    })
    assert retention.limits(T0) == {"kpi_daily": T0 - timedelta(days=3650)}
    assert not {"report_snapshot", "hist_downtime", "noc_asset"} & set(retention.RULES)
