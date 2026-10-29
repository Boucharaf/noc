import asyncio

from collector.cycle import run_cycle

from tests.fakes import FakeSource, MemoryStore


def test_cycle_with_no_healthy_source_keeps_existing_snapshot():
    store = MemoryStore()

    meta = asyncio.run(
        run_cycle({"source": FakeSource(reachable=False, error="offline")}, store, timeout_s=1)
    )

    assert store.health[0].reachable is False
    assert store.snapshot_written is False
    assert store.diffed is None
    assert meta["snapshot_published"] is False
    assert meta["tools_failed"] == ["source"]
