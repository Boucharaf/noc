from datetime import UTC, datetime

from collector import cycle, rollup


def test_incomplete_cycle_is_excluded_from_daily_kpis(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})

    cycle._observe_rollup([], [], datetime.now(UTC), complete=False)

    assert rollup._ACCUMULATOR == {}


def test_complete_cycle_contributes_to_daily_kpis(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})

    cycle._observe_rollup([], [], datetime.now(UTC), complete=True)

    assert len(rollup._ACCUMULATOR) == 1
    assert next(iter(rollup._ACCUMULATOR.values()))["samples"] == 1