"""Source arrêtée (dump, export) : ses états et ses alertes ne sont pas actuels."""
import asyncio
from datetime import datetime, timedelta, timezone

from collector import cycle, history
from collector.merge import attach_alerts, merge_nodes
from integrations.models import Alert, Node, ToolHealth

NOW = datetime.now(timezone.utc)


class Source:
    def __init__(self, horizon):
        self.horizon = horizon

    async def check(self):
        return ToolHealth(tool="netxms", reachable=True)

    async def fetch_nodes(self):
        return [Node(tool="netxms", ref="1", name="R1", state="down")]

    async def fetch_alerts(self):
        return [Alert(tool="netxms", ref="9", severity="critical", message="Node down",
                      since=NOW - timedelta(days=200), node_ref="1")]

    async def data_horizon(self):
        if isinstance(self.horizon, Exception):
            raise self.horizon
        return self.horizon

    # Méthodes facultatives de SourceClient, non fournies.
    from integrations.base import SourceClient as _Base

    fetch_fleet_latest = _Base.fetch_fleet_latest
    fetch_maintenance = _Base.fetch_maintenance
    fetch_work_orders = _Base.fetch_work_orders


def poll(horizon):
    return asyncio.run(cycle.poll_tool("netxms", Source(horizon)))


def test_old_horizon_freezes_states_and_alerts():
    horizon = NOW - timedelta(days=100)
    snap = poll(horizon)
    assert snap.data_until == horizon
    assert snap.alerts[0].frozen and snap.alerts[0].last_observed_at == horizon

    merged, _report = merge_nodes(list(snap.nodes))
    assert merged[0].state == "silent"           # puis « inconnu » dans le cycle
    assert merged[0].last_known_states == {"netxms": "down"}
    assert not merged[0].observed
    attach_alerts(merged, list(snap.alerts))
    assert merged[0].alerts == 0                 # non corrigée, mais non comptée
    assert history.subjects(merged, set()) == {} # temps non observé
    row = history.alert_rows(snap.alerts, merged)["netxms:9"]
    _closes, _inserts, touches = history.plan_alerts(
        [{"id": 4, "alert_key": "netxms:9", "tool": "netxms"}], {"netxms:9": row},
        {"netxms"}, NOW,
    )
    assert touches == [(4, "critical", horizon)]


def test_live_source_is_untouched():
    for horizon in (None, NOW - timedelta(hours=1), RuntimeError("illisible")):
        snap = poll(horizon)
        assert snap.data_until is None
        assert not snap.nodes[0].stale and not snap.alerts[0].frozen
