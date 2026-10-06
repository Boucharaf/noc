import asyncio

from integrations.models import ToolHealth

from collector.cycle import run_cycle


class _UnavailableClient:
    async def check(self):
        return ToolHealth(tool="source", reachable=False, error="offline")


class _Store:
    def __init__(self):
        self.health = []
        self.snapshot_written = False
        self.alerts_diffed = False

    async def write_tool_health(self, health):
        self.health.append(health)

    async def write_snapshot(self, *_args):
        self.snapshot_written = True

    async def diff_new_alerts(self, _alerts):
        self.alerts_diffed = True
        return []


def test_cycle_with_no_healthy_source_keeps_existing_snapshot():
    store = _Store()

    meta = asyncio.run(run_cycle({"source": _UnavailableClient()}, store, timeout_s=1))

    assert store.health[0].reachable is False
    assert store.snapshot_written is False
    assert store.alerts_diffed is False
    assert meta["tools_failed"] == ["source"]