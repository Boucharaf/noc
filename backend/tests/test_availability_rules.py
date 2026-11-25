"""Règles de disponibilité de l'agence (feuille « KPI NOC référence ») :
KPI-01 répond ÷ mesuré, horizon des sources figées, pondération, cœur/accès."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from collector import config as collector_config
from collector import cycle, downtime, rollup
from collector.history import daily_rows
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import _threshold
from app.models import HistDowntime, HistSourceObject, HistSourceSync, HistState, KpiDaily
from app.services import availability_service as av
from app.services import kpi_service, live_service
from integrations.netxms import node_state

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)
M = timedelta(minutes=1)


class Row(dict):
    __getattr__ = dict.get


def _row(state, start, end, **extra):
    return Row({
        "subject_kind": "node", "subject_id": "n1", "node_id": "n1", "name": "RT01",
        "site": "Pâ", "province": None, "region": None, "tools": "netxms",
        "state": state, "measured_state": state, "started_at": start, "ended_at": end,
        "last_seen_at": end or start, **extra,
    })


def _end(row):
    return row["ended_at"] or row["last_seen_at"]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (HistState, HistDowntime, HistSourceObject, HistSourceSync, KpiDaily):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# -- KPI-01 : dégradé = répond ------------------------------------------------------
def test_degraded_time_is_available():
    rows = [_row("up", T0, T0 + 6 * H), _row("degraded", T0 + 6 * H, T0 + 8 * H),
            _row("down", T0 + 8 * H, T0 + 10 * H), _row("unknown", T0 + 10 * H, T0 + 24 * H)]
    result = av.summarise(rows, T0, T0 + 24 * H, T0 + 24 * H)
    assert result["availability_pct"] == 80.0      # 8 h ÷ 10 h, l'inconnu exclu
    daily = daily_rows(T0.date(), rows, [], T0 + 24 * H)
    total = next(r for r in daily if r["site"] is None)
    assert total["fleet_availability_pct"] == 80.0
    assert (total["responding_s"], total["supervised_s"]) == (8 * 3600, 10 * 3600)


def test_rollup_counts_degraded_as_responding():
    class N:
        def __init__(self, state):
            self.state, self.id, self.site = state, state, None

    rollup._ACCUMULATOR.clear()
    rollup.observe(date(2026, 11, 1), None, [N("up"), N("degraded"), N("down"), N("unknown")], [])
    row = rollup.rows_for(date(2026, 11, 1))[0]
    rollup._ACCUMULATOR.clear()
    assert row["fleet_availability_pct"] == 66.67
    assert row["supervised_s"] == 3 * collector_config.COLLECT_INTERVAL_S


def test_rollup_restores_counters_saved_before_durations():
    rollup._ACCUMULATOR.clear()
    rollup.restore_accumulator([{
        "day": "2026-11-01", "site": None, "samples": 1, "up": 2, "degraded": 1, "down": 1,
    }])
    row = rollup.rows_for(date(2026, 11, 1))[0]
    rollup._ACCUMULATOR.clear()
    assert row["fleet_availability_pct"] == 75.0


def test_netxms_severe_alarm_is_not_an_outage():
    assert node_state(4, False) == "degraded"
    assert node_state(3, False) == "degraded"
    assert node_state(4, True) == "down"
    assert node_state(4, None) == "down"       # la source ne publie pas l'injoignabilité
    assert node_state(0, False) == "up"


# -- Horizon de la source -----------------------------------------------------------
def test_source_is_ignored_after_its_horizon():
    """Panne ouverte dans un dump figé, mais le NOC voit l'équipement répondre."""
    rows = [_row("up", T0 + 10 * H, T0 + 12 * H), _row("down", T0 + 12 * H, T0 + 13 * H)]
    periods, report = downtime.overlay(
        rows, [(T0, None)], T0 + 20 * H, _end, horizon=T0 + 2 * H
    )
    assert [p["state"] for p in periods] == ["up", "down"]
    assert report["noc_only_down_s"] == report["source_only_down_s"] == 0


def test_gaps_are_not_filled_after_the_horizon():
    rows = [_row("up", T0 + 10 * H, T0 + 12 * H), _row("up", T0 + 15 * H, T0 + 16 * H)]
    _periods, report = downtime.overlay(rows, [], T0 + 20 * H, _end, horizon=T0 + 2 * H)
    assert report["filled_s"] == 0
    # Horizon au milieu du trou : comblé jusque-là seulement.
    _periods, report = downtime.overlay(rows, [], T0 + 20 * H, _end, horizon=T0 + 13 * H)
    assert report["filled_s"] == 3600


def test_period_across_the_horizon_is_split():
    rows = [_row("up", T0, T0 + 10 * H)]
    periods, _ = downtime.overlay(
        rows, [(T0 + 4 * H, None)], T0 + 20 * H, _end, horizon=T0 + 5 * H
    )
    assert [(p["state"], p["started_at"]) for p in periods] == [
        ("up", T0), ("down", T0 + 4 * H), ("up", T0 + 5 * H)]


def test_outage_still_open_at_the_horizon_is_the_same_outage():
    rows = [_row("down", T0 + 10 * H, T0 + 12 * H), _row("up", T0 + 12 * H, T0 + 14 * H),
            _row("down", T0 + 14 * H, T0 + 15 * H)]
    periods, _ = downtime.overlay(
        rows, [(T0, None)], T0 + 20 * H, _end, horizon=T0 + 2 * H
    )
    assert periods[0]["down_since"] == T0
    assert periods[2]["down_since"] is None     # rétabli entre-temps : panne nouvelle
    episodes = av.down_episodes(periods, T0 + 20 * H)
    assert [start for start, _e, _c in episodes] == [T0, T0 + 14 * H]


def test_frozen_dump_does_not_invent_time(db):
    """Le cas réel : dump figé en août, observations trouées en novembre."""
    now = av._now()
    db.add(HistSourceSync(source="netxms", synced_at=now, rows_read=1,
                          horizon_at=now - timedelta(days=100),
                          complete_since=now - timedelta(days=190)))
    db.add(HistSourceObject(source="netxms", object_ref="1", node_id="n1", name="RT01",
                            tools="netxms", managed=True,
                            supervised_since=now - timedelta(days=300)))
    db.add(HistDowntime(id=1, source="netxms", object_ref="1", node_id="n1", tag="Node_Down",
                        started_at=now - timedelta(days=101), ended_at=None))
    for key, (state, start, end) in enumerate((("up", 20, 15), ("down", 10, 5)), 1):
        db.add(HistState(id=key, subject_kind="node", subject_id="n1", node_id="n1", name="RT01",
                         tools="netxms", state=state, measured_state=state,
                         started_at=now - start * H, ended_at=now - end * H,
                         last_seen_at=now - end * H))
    db.commit()
    original = downtime.enabled_sources
    downtime.enabled_sources = lambda: ("netxms",)
    try:
        result = av.ranking(db, days=30)
    finally:
        downtime.enabled_sources = original
    assert result["average_pct"] == 50.0
    assert result["basis"]["sources"] == {av.OBSERVATION: 1}


# -- Pannes : fusion indépendante de la cadence ---------------------------------------
def test_outages_less_than_15_minutes_apart_are_one():
    rows = [_row("down", T0, T0 + 10 * M), _row("up", T0 + 10 * M, T0 + 22 * M),
            _row("down", T0 + 22 * M, T0 + 30 * M), _row("degraded", T0 + 30 * M, T0 + 60 * M),
            _row("down", T0 + 60 * M, T0 + 70 * M)]
    assert len(av.down_episodes(rows, T0 + 2 * H)) == 2


def test_outage_across_an_unobserved_gap_is_one():
    rows = [_row("down", T0, T0 + H), _row("down", T0 + 10 * H, T0 + 11 * H),
            _row("unknown", T0 + 11 * H, T0 + 14 * H), _row("down", T0 + 14 * H, T0 + 15 * H)]
    assert len(av.down_episodes(rows, T0 + 20 * H)) == 1


def test_daily_averages_use_the_observed_time():
    rows = [_row("down", T0, T0 + 2 * H), _row("down", T0 + 5 * H, T0 + 7 * H)]
    total = next(r for r in daily_rows(T0.date(), rows, [], T0 + 24 * H) if r["site"] is None)
    assert total["avg_down"] == 1.0
    assert total["samples"] == 4 * 3600 // collector_config.COLLECT_INTERVAL_S


# -- Moyennes pondérées ---------------------------------------------------------------
def test_monthly_availability_is_weighted_by_supervised_time(db):
    db.add(KpiDaily(day=date(2026, 11, 1), site=None, samples=1440,
                    fleet_availability_pct=100.0, supervised_s=90.0, responding_s=90.0))
    db.add(KpiDaily(day=date(2026, 11, 2), site=None, samples=100,
                    fleet_availability_pct=0.0, supervised_s=10.0, responding_s=0.0))
    # Bilan antérieur à la colonne : pondéré sur une journée pleine.
    db.add(KpiDaily(day=date(2026, 10, 2), site=None, samples=288, avg_up=1, avg_down=1,
                    fleet_availability_pct=50.0))
    db.commit()
    summary = kpi_service.monthly_summary(db, 2026, 11)
    assert summary["current"]["availability_pct"] == 90.0
    assert summary["previous"]["availability_pct"] == 50.0


# -- Cœur / accès, seuils, score -------------------------------------------------------
def test_core_is_read_from_groups():
    assert live_service.is_core({"groups": ["CORE"]})
    assert not live_service.is_core({"groups": ["Client", "Core-test"]})
    assert not live_service.is_core({})


def test_ranking_separates_core_and_access(db):
    now = av._now()
    for key, (node, state) in enumerate((("c", "up"), ("a", "down")), 1):
        db.add(HistState(id=key, subject_kind="node", subject_id=node, node_id=node, name=node,
                         tools="zabbix", state=state, measured_state=state,
                         started_at=now - 5 * H, ended_at=now - H, last_seen_at=now - H))
    db.commit()
    result = av.ranking(db, days=1, core_ids={"c"})
    assert result["classes"]["core"] == {"subjects": 1, "average_pct": 100.0}
    assert result["classes"]["access"] == {"subjects": 1, "average_pct": 0.0}
    assert av.ranking(db, days=1, node_ids={"c"})["average_pct"] == 100.0


def test_threshold_falls_back_on_the_agency_value(monkeypatch):
    monkeypatch.setenv("X", "90,95")           # inversés
    assert _threshold("X", "99,97") == (99.0, 97.0)
    monkeypatch.setenv("X", "98.5,90")
    assert _threshold("X", "99,97") == (98.5, 90.0)


def test_health_uses_period_availability_and_says_so(db):
    kpi_service._health_cache.clear()
    assert kpi_service._health_availability(db, ("vide",), None) == (None, "fleet")
    now = av._now()
    db.add(HistState(id=1, subject_kind="node", subject_id="n", node_id="n", name="n", tools="zabbix",
                     state="degraded", measured_state="degraded", started_at=now - 3 * H,
                     ended_at=now - H, last_seen_at=now - H))
    db.commit()
    assert kpi_service._health_availability(db, ("plein",), None) == (100.0, "period")


# -- Cadence --------------------------------------------------------------------------
def test_slow_tool_is_read_less_often(monkeypatch):
    calls = []

    async def poll(name, client):
        calls.append(name)
        return Row(health=Row(reachable=True))

    monkeypatch.setattr(cycle, "poll_tool", poll)
    monkeypatch.setattr(cycle, "_slow_reads", {})
    monkeypatch.setattr(collector_config, "COLLECT_INTERVAL_S", 60)
    monkeypatch.setattr(collector_config, "SLOW_INTERVAL_S", 300)

    async def run():
        for minute in range(6):
            await cycle._poll("itop", None, T0 + minute * M)
            await cycle._poll("zabbix", None, T0 + minute * M)

    asyncio.run(run())
    assert calls.count("itop") == 2
    assert calls.count("zabbix") == 6
