import asyncio

from app.services import history_service, metrics_service


def test_network_snapshot_scopes_live_metrics_and_alerts_to_site(monkeypatch):
    nodes = [
        {
            "id": "node-a",
            "site": "Ouagadougou",
            "organisation": "A",
            "node_type": "router",
            "state": "up",
            "sources": {"zabbix": "101"},
        },
        {
            "id": "node-b",
            "site": "Bobo-Dioulasso",
            "organisation": "A",
            "node_type": "router",
            "state": "down",
            "sources": {"zabbix": "102"},
        },
        {
            "id": "node-c",
            "site": "Ouagadougou",
            "organisation": "B",
            "node_type": "switch",
            "state": "silent",
            "sources": {"centreon": "103"},
        },
    ]
    alerts = [
        {"tool": "zabbix", "node_ref": "101", "severity": "warning"},
        {"tool": "zabbix", "node_ref": "102", "severity": "critical"},
        {"tool": "centreon", "node_ref": "103", "severity": "critical"},
    ]

    async def get_nodes():
        return nodes

    async def get_alerts():
        return alerts

    async def snapshot_age_s():
        return 1

    async def is_stale():
        return False

    monkeypatch.setattr(metrics_service.live_service, "get_nodes", get_nodes)
    monkeypatch.setattr(metrics_service.live_service, "get_alerts", get_alerts)
    monkeypatch.setattr(metrics_service.live_service, "snapshot_age_s", snapshot_age_s)
    monkeypatch.setattr(metrics_service.live_service, "is_stale", is_stale)

    result = asyncio.run(
        metrics_service.network_snapshot("Ouagadougou", "A", "router")
    )

    assert result["nodes_total"] == 1
    assert result["nodes_up"] == 1
    assert result["nodes_down"] == 0
    assert result["nodes_silent"] == 0
    assert result["fleet_health_pct"] == 100.0
    assert result["alerts_total"] == 1
    assert result["alerts_critical"] == 0
    assert result["tools_covering"] == 1


def test_three_day_history_window_is_exactly_three_days():
    start, end = history_service.resolve_window("3d", None, None)

    assert (end - start).total_seconds() == 3 * 24 * 60 * 60
