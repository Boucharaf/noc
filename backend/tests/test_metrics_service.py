import asyncio

from app.services import geo_service, history_service, metrics_service


def test_network_snapshot_scopes_live_metrics_and_alerts_to_site(monkeypatch):
    nodes = [
        {
            "id": "node-a",
            "name": "RT-A",
            "site": "Ouagadougou",
            "state": "up",
            "sources": {"zabbix": "101"},
        },
        {
            "id": "node-b",
            "name": "RT-B",
            "site": "Bobo-Dioulasso",
            "state": "down",
            "sources": {"zabbix": "102"},
        },
        {
            "id": "node-c",
            "name": "SW-C",
            "site": "Ouagadougou",
            "state": "silent",
            "sources": {"centreon": "103"},
        },
    ]
    alerts = [
        {"tool": tool, "ref": ref, "node_ref": node_ref, "severity": severity}
        for tool, ref, node_ref, severity in (
            ("zabbix", "1", "101", "medium"),
            ("zabbix", "2", "102", "critical"),
            ("centreon", "3", "103", "critical"),
        )
    ]
    latest = {
        "zabbix:101": {"latency_ms": 20.0},
        "zabbix:102": {"latency_ms": 400.0},
        "centreon:103": {"latency_ms": 40.0},
    }

    async def get_nodes():
        return [dict(node) for node in nodes]

    async def get_alerts():
        return [dict(alert) for alert in alerts]

    async def get_latest():
        return latest

    async def snapshot_age_s():
        return 1

    async def is_stale():
        return False

    async def no_windows(_at=None):
        return []

    live = metrics_service.live_service
    monkeypatch.setattr(live, "get_nodes", get_nodes)
    monkeypatch.setattr(live, "get_alerts", get_alerts)
    monkeypatch.setattr(live, "get_latest", get_latest)
    monkeypatch.setattr(live, "snapshot_age_s", snapshot_age_s)
    monkeypatch.setattr(live, "is_stale", is_stale)
    monkeypatch.setattr(geo_service.node_service, "active_windows", no_windows)

    # Même chemin que GET /network/snapshot : périmètre, puis indicateurs.
    async def snapshot():
        scoped_nodes, scoped_alerts, _incidents = await geo_service.scoped(
            None, site="Ouagadougou"
        )
        return await metrics_service.network_snapshot(None, scoped_nodes, scoped_alerts)

    result = asyncio.run(snapshot())

    assert result["nodes_total"] == 2
    assert result["nodes_up"] == 1
    assert result["nodes_down"] == 0
    assert result["nodes_silent"] == 1
    # Un équipement muet n'est pas disponible.
    assert result["fleet_availability_pct"] == 50.0
    assert result["alerts_total"] == 2
    assert result["alerts_critical"] == 1
    assert result["tools_covering"] == 2
    # Bobo-Dioulasso (400 ms) est hors périmètre.
    assert result["avg_latency_ms"] == 30.0


def test_three_day_history_window_is_exactly_three_days():
    start, end = history_service.resolve_window("3d", None, None)

    assert (end - start).total_seconds() == 3 * 24 * 60 * 60
