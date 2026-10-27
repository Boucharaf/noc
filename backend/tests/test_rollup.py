from datetime import UTC, datetime
import asyncio

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


def test_failed_kpi_write_keeps_batch_for_idempotent_retry(monkeypatch):
    day = datetime.now(UTC).date()
    rows = [{"day": day, "site": None, "samples": 2}]
    monkeypatch.setattr(rollup, "_PENDING_ROWS", {day: rows.copy()})
    attempts = 0

    async def flaky_write(received):
        nonlocal attempts
        attempts += 1
        assert received == rows
        if attempts == 1:
            raise OSError("temporary database outage")

    monkeypatch.setattr(rollup, "write_rows", flaky_write)

    try:
        asyncio.run(rollup.flush_pending())
    except OSError:
        pass
    else:
        raise AssertionError("the simulated SQL failure should propagate")

    assert rollup._PENDING_ROWS[day] == rows
    asyncio.run(rollup.flush_pending())
    assert day not in rollup._PENDING_ROWS
    assert attempts == 2
