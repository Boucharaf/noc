"""Tests ciblés des transformations pouvant fausser les indicateurs NOC."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.services import alerts_service, kpi_service, live_service, metrics_service  # noqa: E402
from collector.cycle import (  # noqa: E402
    _cached_alerts,
    _cached_nodes,
    poll_tool,
    run_cycle,
)
from collector.merge import attach_alerts, merge_nodes  # noqa: E402
from collector.state import SnapshotStore  # noqa: E402
from integrations.base import ToolUnavailable  # noqa: E402
from integrations.itop import ITopClient  # noqa: E402
from integrations.models import Alert, NetworkInterface, Node, ToolHealth, to_jsonable  # noqa: E402
from integrations.netxms import NetXMSClient  # noqa: E402
from integrations.normalize import severity  # noqa: E402
from integrations.zabbix import _host_state, _metric_for_item, _to_noc_unit  # noqa: E402
from backend.tests.database_safety import validate_test_database_url  # noqa: E402
from backend.tests.fakes import FakeSource, MemoryStore  # noqa: E402
from app.core import rate_limit as rate_limit_module  # noqa: E402
from app.core.rate_limit import client_ip  # noqa: E402
from starlette.requests import Request  # noqa: E402


def test_warning_and_disk_percentage_units_are_normalized():
    assert severity("zabbix", 2) == "medium"
    assert severity("netxms", 1) == "medium"
    assert severity("centreon_service", 1) == "medium"
    pused = {"key_": "vfs.fs.size[/,pused]"}
    pfree = {"key_": "vfs.fs.size[/,pfree]"}
    assert _metric_for_item(pused) == "disk_pct"
    assert _metric_for_item(pfree) == "disk_pct"
    # `used` est en octets : ce n'est pas un pourcentage.
    assert _metric_for_item({"key_": "vfs.fs.size[/,used]"}) is None
    assert _to_noc_unit(pused, "disk_pct", 30.0) == 30.0
    assert _to_noc_unit(pfree, "disk_pct", 30.0) == 70.0


def test_alert_kind_filter_separates_technical_alerts_from_itsm_tickets(monkeypatch):
    records = [
        {"tool": "zabbix", "ref": "1", "severity": "high", "message": "Host down"},
        {
            "tool": "itop",
            "ref": "INC1",
            "kind": "itsm_ticket",
            "severity": "high",
            "message": "User request",
        },
    ]

    async def get_alerts():
        return records

    async def get_nodes():
        return []

    async def zero_age():
        return 0

    async def not_stale():
        return False

    monkeypatch.setattr(live_service, "get_alerts", get_alerts)
    monkeypatch.setattr(live_service, "get_nodes", get_nodes)
    monkeypatch.setattr(live_service, "snapshot_age_s", zero_age)
    monkeypatch.setattr(live_service, "is_stale", not_stale)

    async def no_windows(_at=None):
        return []

    monkeypatch.setattr(alerts_service.node_service, "active_windows", no_windows)

    technical = asyncio.run(
        alerts_service.list_alerts(kind="technical")
    )
    tickets = asyncio.run(
        alerts_service.list_alerts(kind="itsm_ticket")
    )

    assert [alert["kind"] for alert in technical["alerts"]] == ["technical"]
    assert [alert["kind"] for alert in tickets["alerts"]] == ["itsm_ticket"]


def _node(tool, ref, hostname, ip, state="unknown"):
    return Node(
        tool=tool,
        ref=ref,
        name=hostname,
        hostname=hostname,
        ip=ip,
        state=state,
    )


def test_inventory_merge_requires_unique_hostname_and_ip_agreement():
    merged, report = merge_nodes(
        [
            _node("zabbix", "1", "router-a.example.net", "192.0.2.10"),
            _node("centreon", "2", "router-b.example.net", "192.0.2.10"),
        ]
    )

    assert len(merged) == 2
    assert report.matched_by_verified_identity == 0
    assert report.ambiguous_total == 1
    assert report.ambiguities[0]["reason"] == "shared_ip_with_different_hostnames"


def test_inventory_merge_does_not_strip_hostname_domains():
    merged, report = merge_nodes(
        [
            _node("zabbix", "1", "router-a", "192.0.2.10"),
            _node("centreon", "2", "router-a.example.net", "192.0.2.10"),
        ]
    )

    assert len(merged) == 2
    assert report.matched_by_verified_identity == 0
    assert report.ambiguous_total == 1


def test_inventory_merge_uses_unique_joint_identity_and_reports_state_conflicts():
    merged, report = merge_nodes(
        [
            _node("zabbix", "1", "router-a.example.net", "192.0.2.10", "up"),
            _node("centreon", "2", "router-a.example.net.", "192.0.2.10", "down"),
        ]
    )

    assert len(merged) == 1
    assert merged[0].state == "unknown"
    assert merged[0].state_conflict == {"centreon": "down", "zabbix": "up"}
    assert report.matched_by_verified_identity == 1
    assert len(report.state_conflicts) == 1


def test_inventory_merge_rejects_duplicate_identity_within_one_source():
    merged, report = merge_nodes(
        [
            _node("zabbix", "1", "router-a.example.net", "192.0.2.10"),
            _node("zabbix", "2", "router-a.example.net", "192.0.2.10"),
            _node("centreon", "3", "router-a.example.net", "192.0.2.10"),
        ]
    )

    assert len(merged) == 3
    assert report.matched_by_verified_identity == 0
    assert any(
        item["reason"] == "duplicate_identity_within_source"
        for item in report.ambiguities
    )


def test_alert_name_fallback_does_not_attach_to_ambiguous_equipment():
    merged, _ = merge_nodes(
        [
            _node("zabbix", "1", "router-a.example.net", "192.0.2.10"),
            _node("centreon", "2", "router-a.example.net", "192.0.2.11"),
        ]
    )
    alert = Alert(
        tool="nagios",
        ref="alert-1",
        severity="high",
        message="Host down",
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        node_name="router-a.example.net",
    )

    merged, orphans = attach_alerts(merged, [alert])

    assert len(orphans) == 1
    assert all(node.alerts == 0 for node in merged)


def test_itop_sla_fetch_propagates_source_failure():
    import pytest

    client = ITopClient("https://itop.example")

    async def fail(_operation, _payload):
        raise ToolUnavailable("itop", "HTTP 503")

    client._call = fail

    async def fetch():
        try:
            with pytest.raises(ToolUnavailable, match="HTTP 503"):
                await client.fetch_sla_targets()
        finally:
            await client.aclose()

    asyncio.run(fetch())


def test_itop_rejects_invalid_json_and_unexpected_object_shapes(monkeypatch):
    client = ITopClient("https://itop.example")
    assertions = TestCase()

    class Response:
        def __init__(self, value):
            self.value = value

        def json(self):
            if isinstance(self.value, Exception):
                raise self.value
            return self.value

    async def run():
        async def request_invalid_json(*_args, **_kwargs):
            return Response(ValueError("invalid JSON"))

        monkeypatch.setattr(client, "_request", request_invalid_json)
        with assertions.assertRaisesRegex(ToolUnavailable, "non-JSON"):
            await client._call("core/get", {})

        async def request_non_object(*_args, **_kwargs):
            return Response([])

        monkeypatch.setattr(client, "_request", request_non_object)
        with assertions.assertRaisesRegex(ToolUnavailable, "objet attendu"):
            await client._call("core/get", {})

    asyncio.run(run())

    assert client._objects(
        {"code": 0, "message": "Found: 0", "objects": None}, "core/get"
    ) == {}
    with assertions.assertRaisesRegex(
        ToolUnavailable, "objets avec champs structurés"
    ):
        client._objects({"objects": {"Incident::1": {"fields": []}}}, "core/get")


def test_malformed_cached_source_is_rejected_as_a_whole():
    node = _node("zabbix", "host-1", "router-a.example.net", "192.0.2.10")
    node_payload = {
        "collected_at": "2025-01-01T00:00:00+00:00",
        "records": [to_jsonable(node), {"tool": "zabbix"}],
    }
    alert = Alert(
        tool="zabbix",
        ref="problem-1",
        severity="critical",
        message="Host down",
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    alert_payload = {
        "collected_at": "2025-01-01T00:00:00+00:00",
        "records": [to_jsonable(alert), {"tool": "zabbix"}],
    }

    assert _cached_nodes(node_payload) == ([], None)
    assert _cached_alerts(alert_payload) == ([], None)


def test_source_store_rejects_malformed_cache_metadata():
    class Redis:
        value = None

        async def get(self, _key):
            return self.value

    redis = Redis()
    store = SnapshotStore(redis)
    invalid_payloads = [
        {"records": []},
        {"collected_at": "not-a-timestamp", "records": []},
        {"collected_at": "2025-01-01T00:00:00", "records": []},
        {
            "collected_at": "2025-01-01T00:00:00+00:00",
            "records": [None],
        },
    ]

    async def read_invalid_payloads():
        for payload in invalid_payloads:
            redis.value = json.dumps(payload)
            assert await store.read_source_data("zabbix", "nodes") is None

    asyncio.run(read_invalid_payloads())


def test_collector_counts_and_broadcasts_only_technical_alerts(monkeypatch):
    from collector import cycle

    technical = Alert(
        tool="zabbix",
        ref="event-1",
        severity="critical",
        message="Host down",
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    ticket = Alert(
        tool="itop",
        ref="incident-1",
        severity="critical",
        message="Ticket ouvert",
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        kind="itsm_ticket",
    )

    class Store(MemoryStore):
        # Toute alerte est « nouvelle » : on vérifie ce qui est diffusé, pas
        # la règle du premier cycle.
        async def diff_new_alerts(self, alerts):
            self.diffed = list(alerts)
            return list(alerts)

    store = Store()
    monkeypatch.setattr(cycle.config, "ROLLUP_ENABLED", False)
    meta = asyncio.run(
        run_cycle(
            {
                "zabbix": FakeSource("zabbix", alerts=[technical]),
                "itop": FakeSource("itop", alerts=[ticket]),
            },
            store,
            timeout_s=1,
        )
    )

    assert len(store.alerts) == 2
    assert meta["alerts"] == 1
    assert meta["itsm_tickets"] == 1
    assert store.diffed == [technical]
    assert store.published == [technical]


def test_live_kpis_separate_itop_tickets_from_technical_alerts(monkeypatch):
    records = [
        {"tool": "zabbix", "kind": "technical", "severity": "critical"},
        {"tool": "itop", "kind": "itsm_ticket", "severity": "critical"},
    ]

    async def get_alerts():
        return records

    monkeypatch.setattr(kpi_service.live_service, "get_alerts", get_alerts)
    monkeypatch.setattr(live_service, "get_alerts", get_alerts)

    summary = asyncio.run(live_service.fleet_summary([]))
    by_tool = asyncio.run(kpi_service.alerts_by_tool())
    by_severity = asyncio.run(kpi_service.alerts_by_severity())

    assert summary["alerts_total"] == 1
    assert summary["itsm_tickets_total"] == 1
    assert by_tool == [{"tool": "zabbix", "count": 1}]
    assert next(row for row in by_severity if row["severity"] == "critical")["count"] == 1


def test_fleet_availability_counts_silent_and_unknown_as_unavailable(monkeypatch):
    async def no_alerts():
        return []

    monkeypatch.setattr(live_service, "get_alerts", no_alerts)
    summary = asyncio.run(
        live_service.fleet_summary(
            [
                {"state": "up"},
                {"state": "down"},
                {"state": "silent"},
                {"state": "unknown"},
                {"state": "maintenance"},
            ]
        )
    )

    assert summary["fleet_health_pct"] == 20
    assert summary["fleet_availability_pct"] == 25


def test_collector_retains_last_source_data_and_marks_it_stale(monkeypatch):
    from collector import cycle

    node = _node("zabbix", "host-1", "router-a.example.net", "192.0.2.10", "down")
    alert = Alert(
        tool="zabbix",
        ref="problem-1",
        severity="critical",
        message="Host down",
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        node_ref="host-1",
    )

    def client(available):
        return FakeSource("zabbix", nodes=[node], alerts=[alert], reachable=available)

    store = MemoryStore()
    monkeypatch.setattr(cycle.config, "ROLLUP_ENABLED", False)

    async def run():
        await run_cycle({"zabbix": client(True)}, store, timeout_s=1)
        await run_cycle({"zabbix": client(False)}, store, timeout_s=1)

    asyncio.run(run())

    # Une alerte resservie depuis le cache n'est pas une nouvelle alerte.
    assert store.published == []
    assert len(store.nodes) == 1
    # La fusion dit « muet » ; le cycle publie un seul état « inconnu ».
    assert store.nodes[0].state == "unknown"
    assert store.nodes[0].last_known_states == {"zabbix": "down"}
    assert store.nodes[0].stale_sources == ["zabbix"]
    assert len(store.alerts) == 1
    assert store.alerts[0].stale is True
    assert store.meta["source_data"]["zabbix"]["alerts"]["stale"] is True
    assert store.meta["source_data"]["zabbix"]["alerts"]["collected_at"]


def test_itop_ticket_attaches_by_numeric_functional_ci_id():
    client = ITopClient("https://itop.example")

    async def check():
        return ToolHealth(tool="itop", reachable=True)

    async def call(_operation, payload):
        cls = payload["class"]
        if cls == "NetworkDevice":
            return {
                "objects": {
                    "NetworkDevice::42": {
                        "key": "NetworkDevice::42",
                        "fields": {
                            "id": "42",
                            "name": "router-42",
                            "status": "production",
                        },
                    }
                }
            }
        if cls == "Server":
            return {"objects": {}}
        if cls == "VirtualMachine":
            raise ToolUnavailable("itop", "Unknown class VirtualMachine")
        if cls == "Incident":
            return {
                "objects": {
                    "Incident::99": {
                        "key": "Incident::99",
                        "fields": {
                            "id": "99",
                            "title": "Incident test",
                            "priority": "1",
                            "start_date": "2025-01-01 00:00:00",
                            "functionalcis_list": [
                                {
                                    "functionalci_id": "42",
                                    "functionalci_name": "router-42",
                                }
                            ],
                        },
                    }
                }
            }
        if cls == "UserRequest":
            raise ToolUnavailable("itop", "class does not exist: UserRequest")
        raise AssertionError(f"Unexpected iTop class: {cls}")

    client.check = check
    client._call = call

    async def collect_and_match():
        snapshot = await poll_tool("itop", client)
        merged, _ = merge_nodes(list(snapshot.nodes))
        merged, orphans = attach_alerts(merged, list(snapshot.alerts))
        await client.aclose()
        return snapshot, merged, orphans

    snapshot, merged, orphans = asyncio.run(collect_and_match())

    assert len(snapshot.nodes) == 1
    assert snapshot.nodes[0].ref == "42"
    assert snapshot.alerts[0].kind == "itsm_ticket"
    assert not snapshot.health.reachable
    assert "classe iTop VirtualMachine non disponible" in snapshot.health.error
    assert "classe de tickets iTop UserRequest non disponible" in snapshot.health.error
    assert not orphans
    assert merged[0].alerts == 0


def test_network_series_averages_each_node_before_population(monkeypatch):
    nodes = [
        {"id": "router-a", "name": "A", "sources": {"zabbix": "1"}},
        {"id": "router-b", "name": "B", "sources": {"zabbix": "2"}},
    ]
    series = {
        "router-a": [
            {"at": "2025-01-01T10:00:05+02:00", "value": 4.0},
            {"at": "2025-01-01T10:00:40+02:00", "value": 4.0},
        ],
        "router-b": [{"at": "2025-01-01T08:00:20+00:00", "value": 10.0}],
    }

    async def get_nodes():
        return nodes

    def resolve_window(_period, _start, _end):
        return (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

    async def fetch_node_series(node, _metric, _start, _end):
        return {"points": series[node["id"]], "errors": []}

    monkeypatch.setattr(metrics_service.live_service, "get_nodes", get_nodes)
    monkeypatch.setattr(metrics_service.history_service, "resolve_window", resolve_window)
    monkeypatch.setattr(
        metrics_service.history_service, "fetch_node_series", fetch_node_series
    )
    monkeypatch.setattr(metrics_service.history_service, "serves_history", lambda _tool: True)

    result = asyncio.run(metrics_service.network_series("cpu_pct", sample=2))

    assert result["sampling_method"] == "stable_hash_sample"
    assert result["population_nodes"] == result["sampled_nodes"] == 2
    assert result["contributing_nodes"] == 2
    assert result["points"] == [
        {
            "at": "2025-01-01T08:00:00+00:00",
            "contributing_nodes": 2,
            "value": 7.0,
        }
    ]


def test_site_availability_excludes_maintenance_and_counts_unknown(monkeypatch):
    nodes = [
        {"id": "up", "site": "A", "state": "up"},
        {"id": "down", "site": "A", "state": "down"},
        {"id": "silent", "site": "A", "state": "silent"},
        {"id": "unknown", "site": "A", "state": "unknown"},
        {"id": "maintenance", "site": "A", "state": "maintenance"},
    ]

    async def get_nodes():
        return nodes

    async def get_alerts():
        return []

    monkeypatch.setattr(live_service, "get_nodes", get_nodes)
    monkeypatch.setattr(live_service, "get_alerts", get_alerts)

    result = asyncio.run(live_service.sites_summary())[0]

    assert result["availability_pct"] == 25.0
    assert result["maintenance"] == 1
    assert result["silent"] == 1
    assert result["unknown"] == 1


def test_site_maintenance_window_overrides_measured_state(monkeypatch):
    from app.services.node_service import apply_maintenance_windows

    window = {
        "kind": "change",
        "ref": "C-000042",
        "title": "Travaux planifiés",
        "start": "2025-01-01T00:00:00+00:00",
        "end": "2025-01-01T12:00:00+00:00",
        "node_keys": ["router-a"],
    }

    nodes = [
        {"id": "router-a", "site": "A", "state": "down"},
        {"id": "router-a2", "site": "A", "state": "up"},
        {"id": "router-b", "site": "B", "state": "up"},
    ]

    result = apply_maintenance_windows(nodes, [window])

    assert result[0]["state"] == "maintenance"
    assert result[0]["measured_state"] == "down"
    assert result[0]["maintenance_reason"] == "Changement iTop C-000042 — Travaux planifiés"
    assert result[0]["maintenance_until"] == "2025-01-01T12:00:00+00:00"
    assert result[1]["state"] == "up"

    async def get_alerts():
        return []

    monkeypatch.setattr(live_service, "get_alerts", get_alerts)
    by_site = asyncio.run(live_service.sites_summary(result))
    assert by_site[0]["availability_pct"] == 100.0
    assert by_site[0]["maintenance"] == 1


def test_planned_maintenance_is_excluded_from_daily_availability():
    from collector import rollup
    from collector.merge import MergedNode

    day = datetime(2025, 1, 1, tzinfo=timezone.utc).date()
    rollup._ACCUMULATOR.clear()
    nodes = [
        MergedNode(
            id="up", name="up", hostname="up", ip=None, state="up", site="A",
            latitude=None, longitude=None, organisation=None, node_type=None,
        ),
        MergedNode(
            id="z", name="down", hostname="down", ip=None, state="down", site="A",
            latitude=None, longitude=None, organisation=None, node_type=None,
        ),
    ]

    rollup.observe(day, "A", nodes, [], {"z"}, set())
    rows = rollup._drain(day)

    assert rows[0]["fleet_availability_pct"] == 100.0
    assert rows[0]["avg_down"] == 0.0


def test_rollup_keeps_all_sites_total_including_nodes_without_a_site():
    from collector import cycle, rollup
    from collector.merge import MergedNode

    day = datetime(2025, 1, 1, tzinfo=timezone.utc)
    nodes = [
        MergedNode(
            id="located",
            name="located",
            hostname="located",
            ip=None,
            state="up",
            site="A",
            latitude=None,
            longitude=None,
            organisation=None,
            node_type=None,
        ),
        MergedNode(
            id="unlocated",
            name="unlocated",
            hostname="unlocated",
            ip=None,
            state="down",
            site=None,
            latitude=None,
            longitude=None,
            organisation=None,
            node_type=None,
        ),
    ]

    rollup._ACCUMULATOR.clear()
    try:
        cycle._observe_rollup(nodes, [], day, set(), set())
        rows = rollup._drain(day.date())
    finally:
        rollup._ACCUMULATOR.clear()

    by_site = {row["site"]: row for row in rows}
    assert set(by_site) == {None, "A"}
    assert by_site[None]["avg_nodes"] == 2
    assert by_site[None]["fleet_availability_pct"] == 50
    assert by_site["A"]["avg_nodes"] == 1
    assert by_site["A"]["fleet_availability_pct"] == 100


def test_integration_database_guard_rejects_production_database():
    import pytest

    with pytest.raises(ValueError, match="se terminer par _test"):
        validate_test_database_url("postgresql://noc:secret@localhost:5432/noc")


def test_integration_database_guard_accepts_explicit_test_database():
    parsed = validate_test_database_url(
        "postgresql://noc:secret@localhost:5432/noc_test"
    )
    assert parsed.database == "noc_test"


def test_refresh_rotation_reports_success_duplicate_and_replay(monkeypatch):
    from datetime import timedelta
    from app.core import session_store

    outcomes = iter((2, 1, 0))
    monkeypatch.setattr(
        session_store.redis_client,
        "eval",
        lambda *_args: next(outcomes),
    )
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)

    assert (
        session_store.rotate_refresh_session("old", 7, "new-1", expires)
        == "rotated"
    )
    assert (
        session_store.rotate_refresh_session("old", 7, "new-2", expires)
        == "recently_rotated"
    )
    assert (
        session_store.rotate_refresh_session("old", 7, "new-3", expires)
        == "invalid"
    )


def test_sla_target_contract_only_exposes_measured_response_times():
    from app.routes.operations import SlaTargetIn

    assert "tta_target_minutes" in SlaTargetIn.model_fields
    assert "ttr_target_minutes" in SlaTargetIn.model_fields
    assert "availability_target_pct" not in SlaTargetIn.model_fields


def test_rate_limit_trusts_forwarded_ip_only_from_nginx_proxy():
    def make_request(peer_ip):
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [(b"x-real-ip", b"198.51.100.20")],
                "client": (peer_ip, 1234),
                "server": ("backend", 8000),
            }
        )

    assert client_ip(make_request("172.31.250.4")) == "198.51.100.20"
    assert client_ip(make_request("172.31.250.3")) == "172.31.250.3"


def test_icmp_only_zabbix_host_is_not_marked_silent():
    host = {
        "status": "0",
        "items": [{"key_": "icmpping", "lastvalue": "1", "status": "0"}],
    }
    assert _host_state(host, [NetworkInterface(available=0)]) == "up"


def test_zabbix_latest_metrics_are_fetched_once_and_averaged(monkeypatch):
    from integrations.zabbix import ZabbixClient

    client = ZabbixClient("https://zabbix.example")
    clock = str(int(datetime.now(timezone.utc).timestamp()))
    calls = []

    async def items(node_ref, metric_type):
        calls.append((node_ref, metric_type))
        return [
            # Utilisation totale et temps d'inactivité : deux lectures de la
            # même grandeur (30 % = 100 - 70 %). Les variantes user/system,
            # partielles, ne sont plus moyennées dans cpu_pct.
            {
                "itemid": "1",
                "key_": "system.cpu.util",
                "lastclock": clock,
                "lastvalue": "30",
            },
            {
                "itemid": "2",
                "key_": "system.cpu.util[,idle]",
                "lastclock": clock,
                "lastvalue": "70",
            },
            {
                "itemid": "3",
                "key_": "system.cpu.util[,system]",
                "lastclock": clock,
                "lastvalue": "40",
            },
        ]

    monkeypatch.setattr(client, "_items_for", items)

    async def fetch():
        try:
            return await client.fetch_latest("host-1")
        finally:
            await client.aclose()

    latest = asyncio.run(fetch())

    assert calls == [("host-1", None)]
    assert latest["cpu_pct"].value == 30


def test_zabbix_interface_traffic_is_summed_per_interval(monkeypatch):
    from integrations.zabbix import ZabbixClient

    client = ZabbixClient("https://zabbix.example")
    clock = str(int(datetime.now(timezone.utc).timestamp()))

    async def items(_node_ref, _metric):
        return [
            {"itemid": "1", "key_": "net.if.in[eth0]", "value_type": 0},
            {"itemid": "2", "key_": "net.if.in[eth1]", "value_type": 0},
        ]

    async def history(_method, params, start_ts, end_ts):
        return [
            {
                "itemid": params["itemids"][0],
                "clock": clock,
                "value": "1000000" if params["itemids"][0] == "1" else "3000000",
            }
        ]

    monkeypatch.setattr(client, "_items_for", items)
    monkeypatch.setattr(client, "_fetch_history_window", history)
    start = datetime.fromtimestamp(int(clock) - 10, timezone.utc)
    end = datetime.fromtimestamp(int(clock) + 10, timezone.utc)
    try:
        points = asyncio.run(
            client.fetch_history("42", "bandwidth_in_mbps", start, end)
        )
    finally:
        asyncio.run(client.aclose())

    # Trafic de l'équipement = somme des interfaces (8 + 24 Mbit/s).
    assert len(points) == 1
    assert points[0].value == 32.0


def test_zabbix_history_paginates_saturated_time_windows(monkeypatch):
    from integrations import zabbix

    client = zabbix.ZabbixClient("https://zabbix.example")
    monkeypatch.setattr(zabbix, "_PAGE_SIZE", 2)

    async def call(_method, params):
        return [
            {"clock": str(clock)}
            for clock in range(params["time_from"], params["time_till"] + 1)
        ][: params["limit"]]

    monkeypatch.setattr(client, "_call", call)
    try:
        rows = asyncio.run(
            client._fetch_history_window("trend.get", {}, 0, 3)
        )
    finally:
        asyncio.run(client.aclose())

    assert [row["clock"] for row in rows] == ["0", "1", "2", "3"]


def test_zabbix_problem_get_uses_eventid_cursor(monkeypatch):
    from integrations import zabbix

    client = zabbix.ZabbixClient("https://zabbix.example")
    monkeypatch.setattr(zabbix, "_PROBLEM_PAGE_SIZE", 2)
    calls = []
    clock = str(int(datetime.now(timezone.utc).timestamp()))

    async def call(method, params):
        calls.append((method, params))
        if method != "problem.get":
            raise AssertionError(method)
        if "eventid_from" not in params:
            ids = ("1", "2")
        elif params["eventid_from"] == "3":
            ids = ("3",)
        else:
            raise AssertionError(params)
        return [
            {
                "eventid": event_id,
                "objectid": "trigger",
                "clock": clock,
                "severity": "2",
                "name": f"problem-{event_id}",
                "acknowledged": "0",
            }
            for event_id in ids
        ]

    async def hosts(_trigger_ids):
        return {}

    monkeypatch.setattr(client, "_call", call)
    monkeypatch.setattr(client, "_hosts_by_trigger", hosts)
    try:
        alerts = asyncio.run(client.fetch_alerts())
    finally:
        asyncio.run(client.aclose())

    assert [alert.ref for alert in alerts] == ["1", "2", "3"]
    assert calls[1][1]["eventid_from"] == "3"


def test_itop_core_get_is_paged(monkeypatch):
    from integrations import itop

    client = ITopClient("https://itop.example")
    monkeypatch.setattr(itop, "_PAGE_SIZE", 2)
    calls = []

    async def call(operation, payload):
        calls.append(payload["limit"])
        offset = int(payload["limit"].split(",", 1)[0])
        rows = {
            str(index): {"fields": {"id": index}}
            for index in range(offset, min(offset + 2, 5))
        }
        return {"objects": rows, "message": "Found: 5"}

    monkeypatch.setattr(client, "_call", call)
    try:
        result = asyncio.run(client._get_all("core/get", {"class": "Node"}))
    finally:
        asyncio.run(client.aclose())

    assert calls == ["0,2", "2,2", "4,2"]
    assert len(result["objects"]) == 5


def test_netxms_objects_are_paged(monkeypatch):
    from integrations import netxms

    client = NetXMSClient("https://netxms.example")
    monkeypatch.setattr(netxms, "_PAGE_SIZE", 2)
    calls = []

    async def get(_path, params=None):
        if params["class"] != "Node":
            return {"objects": [], "totalCount": 0}
        calls.append(params["offset"])
        start = params["offset"]
        page = [
            {
                "objectId": str(index),
                "objectClass": "Node",
                "objectName": f"node-{index}",
                "status": 0,
            }
            for index in range(start, min(start + 2, 3))
        ]
        return {"objects": page, "totalCount": 3}

    monkeypatch.setattr(client, "_get", get)
    try:
        nodes = asyncio.run(client.fetch_nodes())
    finally:
        asyncio.run(client.aclose())

    assert calls == [0, 2]
    assert [node.ref for node in nodes] == ["0", "1", "2"]


def test_rate_limit_middleware_enforces_ip_quota(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_READ_PER_MIN", 1)
    monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_USER_READ_PER_MIN", 10)
    counts = {}

    def increment(key):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    class FakeRedis:
        async def eval(self, _script, _num_keys, key, _ttl):
            return increment(key)

    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: FakeRedis())

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/overview",
            "raw_path": b"/api/overview",
            "query_string": b"",
            "headers": [],
            "client": ("198.51.100.20", 1234),
            "server": ("backend", 8000),
        }
    )

    async def call_next(_request):
        from starlette.responses import Response

        return Response(status_code=200)

    first = asyncio.run(rate_limit_module.rate_limit_middleware(request, call_next))
    second = asyncio.run(rate_limit_module.rate_limit_middleware(request, call_next))

    assert first.status_code == 200
    assert second.status_code == 429


def test_collector_excludes_disabled_nodes():
    client = FakeSource(
        "zabbix",
        nodes=[
            Node(tool="zabbix", ref="enabled", name="enabled"),
            Node(tool="zabbix", ref="disabled", name="disabled", enabled=False),
        ],
    )

    result = asyncio.run(poll_tool("zabbix", client))

    assert [node.ref for node in result.nodes] == ["enabled"]
    assert result.health.reachable


def test_netxms_history_errors_do_not_turn_into_empty_measurements():
    client = NetXMSClient("https://netxms.example")

    async def fail(_path, _params=None):
        raise ToolUnavailable("netxms", "HTTP 503")

    client._get = fail
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 2, tzinfo=timezone.utc)

    async def fetch():
        try:
            await client.fetch_history("42", "rssi", start, end)
        finally:
            await client.aclose()

    try:
        asyncio.run(fetch())
    except ToolUnavailable as error:
        assert "HTTP 503" in str(error)
    else:
        raise AssertionError("NetXMS source errors must not become empty series")


def test_collector_does_not_publish_empty_snapshot_when_sources_are_unavailable(
    monkeypatch,
):
    from collector import config

    class Client:
        async def check(self):
            return ToolHealth(
                tool="zabbix",
                reachable=False,
                error="DNS resolution failed",
            )

    class Store:
        snapshot_written = False

        async def write_tool_health(self, _health):
            pass

        async def read_source_data(self, _tool, _collection):
            return None

        async def write_snapshot(self, *_args):
            self.snapshot_written = True

    store = Store()
    monkeypatch.setattr(config, "ROLLUP_ENABLED", False)

    result = asyncio.run(
        run_cycle({"zabbix": Client()}, store, timeout_s=1)
    )

    assert result["snapshot_published"] is False
    assert result["tools_failed"] == ["zabbix"]
    assert not store.snapshot_written


def test_collector_publishes_empty_result_from_a_healthy_source(monkeypatch):
    from collector import config

    store = MemoryStore()
    monkeypatch.setattr(config, "ROLLUP_ENABLED", False)

    result = asyncio.run(
        run_cycle({"zabbix": FakeSource("zabbix")}, store, timeout_s=1)
    )

    assert result["nodes"] == 0
    assert result["alerts"] == 0
    assert store.snapshot_written
    assert store.nodes == []
    assert store.alerts == []
