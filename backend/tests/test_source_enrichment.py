from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.cycle import poll_tool, run_cycle  # noqa: E402
from collector.merge import merge_nodes  # noqa: E402
from integrations.centreon import CentreonClient  # noqa: E402
from integrations.itop import ITopClient  # noqa: E402
from integrations.models import NetworkInterface, Node, ToolHealth  # noqa: E402
from integrations.base import ToolUnavailable  # noqa: E402
from integrations.netxms_db import NetXMSDatabaseClient  # noqa: E402
from integrations.zabbix import ZabbixClient  # noqa: E402


def test_merge_preserves_ci_context_interfaces_and_impact_links():
    ci = Node(
        tool="itop",
        ref="ci-1",
        name="Routeur central",
        hostname="core-rtr",
        owner="Equipe réseau",
        business_service="WAN national",
        criticality="high",
        interfaces=(
            NetworkInterface(
                tool="netxms",
                ref="if-1",
                name="GigabitEthernet1/0/1",
                state="up",
                speed_mbps=1000,
            ),
        ),
    )
    router = Node(
        tool="centreon",
        ref="host-1",
        name="core-rtr",
        hostname="core-rtr",
        depends_on=("centreon:host-2", "centreon:host-1"),
        source_status="UP",
    )
    dependent = Node(
        tool="centreon",
        ref="host-2",
        name="Agence-01",
        hostname="agence-01",
    )

    merged, _ = merge_nodes([ci, router, dependent])
    by_name = {node.name: node for node in merged}

    assert by_name["Routeur central"].owner == "Equipe réseau"
    assert by_name["Routeur central"].business_service == "WAN national"
    assert by_name["Routeur central"].criticality == "high"
    assert by_name["Routeur central"].interfaces[0].speed_mbps == 1000
    assert by_name["Routeur central"].source_status == "UP"
    assert by_name["Routeur central"].depends_on == [by_name["Agence-01"].id]
    assert by_name["Agence-01"].impacted_by == [by_name["Routeur central"].id]


def test_disabled_source_node_is_preserved_as_inactive():
    node = Node(
        tool="zabbix",
        ref="host-disabled",
        name="Switch désactivé",
        enabled=False,
        state="up",
    )

    merged, _ = merge_nodes([node])

    assert merged[0].enabled is False


def test_poll_tool_collects_optional_sla_targets_without_external_services():
    class FakeClient:
        async def check(self):
            return ToolHealth(tool="itop", reachable=True)

        async def fetch_nodes(self):
            return []

        async def fetch_alerts(self):
            return []

        async def fetch_sla_targets(self):
            return [{"ref": "slt-1", "name": "WAN", "value": "4"}]

    snapshot = asyncio.run(poll_tool("itop", FakeClient()))
    assert snapshot.health.reachable
    assert snapshot.sla_targets == ({"ref": "slt-1", "name": "WAN", "value": "4"},)


def test_itop_ticket_fields_and_sla_targets_are_normalized():
    client = ITopClient("http://itop", ticket_classes=("Incident",))

    async def fake_call(operation, payload):
        if payload.get("class") == "SLT":
            return {
                "objects": {
                    "slt-1": {
                        "key": "slt-1",
                        "fields": {"name": "WAN critique", "metric": "TTO", "value": "4", "unit": "hours"},
                    }
                }
            }
        return {
            "objects": {
                "ticket-1": {
                    "key": "ticket-1",
                    "fields": {
                        "ref": "INC-1",
                        "title": "Lien indisponible",
                        "status": "assigned",
                        "start_date": "2026-09-30 10:00:00",
                        "last_update": "2026-09-30 10:05:00",
                        "priority": "2",
                        "agent_id_friendlyname": "A. Traoré",
                        "team_id_friendlyname": "Réseau",
                        "service_id_friendlyname": "WAN",
                        "functionalcis_list": [
                            {"functionalci_id": "ci-1", "functionalci_name": "RTR-01"}
                        ],
                    },
                }
            }
        }

    client._call = fake_call
    alerts = asyncio.run(client.fetch_alerts())
    targets = asyncio.run(client.fetch_sla_targets())

    assert alerts[0].source_assignee == "A. Traoré"
    assert alerts[0].source_team == "Réseau"
    assert alerts[0].business_service == "WAN"
    assert alerts[0].ticket_ref == "INC-1"
    assert targets[0]["name"] == "WAN critique"
    assert targets[0]["unit"] == "hours"


def test_itop_ci_maps_business_criticality():
    client = ITopClient("http://itop")

    async def fake_get_class(cls, fields, optional_fields=(), page=1):
        if cls != "NetworkDevice":
            return None
        return {
            "objects": {
                "ci-1": {
                    "key": "ci-1",
                    "fields": {
                        "name": "RTR-01",
                        "status": "implementation",
                        "org_id_friendlyname": "Ministère",
                        "location_id_friendlyname": "Ouagadougou",
                        "managementip": "10.0.0.1",
                        "business_criticity": "high",
                        "support_team_id_friendlyname": "Equipe réseau",
                        "service_id_friendlyname": "WAN national",
                    },
                }
            }
        }

    client._get_class = fake_get_class
    nodes = asyncio.run(client.fetch_nodes())

    assert nodes[0].criticality == "high"
    assert nodes[0].owner == "Equipe réseau"
    assert nodes[0].business_service == "WAN national"
    assert nodes[0].organisation == "Ministère"
    assert nodes[0].site == "Ouagadougou"


def test_netxms_database_maps_read_only_interface_inventory():
    client = NetXMSDatabaseClient("postgresql://netxms-db:5432/netxms")

    async def no_site_referential():
        return False

    async def fake_query(sql):
        assert "json_agg" in sql
        assert "WITH active_nodes AS" in sql
        assert "JOIN active_nodes n ON n.id = cm.object_id" in sql
        assert "JOIN active_nodes n ON n.id = i.node_id" in sql
        return [
            (
                10,
                "RTR-01",
                "rtr-01.example.org",
                "10.0.0.1",
                0,
                "Ouagadougou",
                None,
                None,
                None,
                ["Core"],
                [{"id": 20, "name": "GigabitEthernet1/0/1", "status": 0}],
            )
        ]

    client._uses_site_referential = no_site_referential
    client._query = fake_query
    nodes = asyncio.run(client.fetch_nodes())

    assert nodes[0].interfaces == (
        NetworkInterface(
            tool="netxms",
            ref="20",
            name="GigabitEthernet1/0/1",
            state="up",
        ),
    )


def test_itop_ticket_enrichment_falls_back_when_optional_fields_are_unknown():
    client = ITopClient("http://itop", ticket_classes=("Incident",))
    calls = 0

    async def fake_call(operation, payload):
        nonlocal calls
        calls += 1
        if "agent_id_friendlyname" in payload.get("output_fields", ""):
            raise ToolUnavailable("itop", "invalid attribute code")
        return {
            "objects": {
                "ticket-1": {
                    "key": "ticket-1",
                    "fields": {
                        "ref": "INC-1",
                        "title": "Incident",
                        "status": "new",
                        "priority": "3",
                        "functionalcis_list": [],
                    },
                }
            }
        }

    client._call = fake_call
    alerts = asyncio.run(client.fetch_alerts())

    assert calls == 2
    assert len(alerts) == 1
    assert alerts[0].source_assignee is None
    assert alerts[0].business_service is None


def test_zabbix_maps_interfaces_acknowledger_and_suppression():
    client = ZabbixClient("http://zabbix")

    async def fake_call(method, params, authenticated=True):
        if method == "host.get":
            return [
                {
                    "hostid": "10",
                    "host": "rtr-01",
                    "name": "Routeur 01",
                    "status": "0",
                    "interfaces": [
                        {
                            "interfaceid": "20",
                            "type": "2",
                            "main": "1",
                            "useip": "1",
                            "ip": "10.0.0.1",
                            "port": "161",
                            "available": "1",
                        }
                    ],
                    "hostgroups": [],
                }
            ]
        if method == "problem.get":
            return [
                {
                    "eventid": "900",
                    "objectid": "30",
                    "severity": "5",
                    "name": "Lien indisponible",
                    "clock": "100",
                    "acknowledged": "1",
                    "suppressed": "1",
                    "suppression_data": [{"maintenanceid": "7", "suppress_until": "200"}],
                    "acknowledges": [
                        {"clock": "150", "userid": "42", "message": "Pris en charge"}
                    ],
                }
            ]
        if method == "trigger.get":
            return [{"triggerid": "30", "hosts": [{"hostid": "10", "name": "Routeur 01"}]}]
        if method == "user.get":
            return [{"userid": "42", "username": "a.traore"}]
        raise AssertionError(method)

    client._call = fake_call
    nodes = asyncio.run(client.fetch_nodes())
    alerts = asyncio.run(client.fetch_alerts())

    assert nodes[0].interfaces[0].name == "SNMP 10.0.0.1"
    assert nodes[0].interfaces[0].state == "up"
    assert alerts[0].acknowledged_by == "a.traore"
    assert alerts[0].acknowledgement_note == "Pris en charge"
    assert alerts[0].is_maintenance
    assert alerts[0].maintenance_until is not None


def test_centreon_maps_service_parent_check_freshness_and_ack_details():
    client = CentreonClient("http://centreon")
    row = {
        "id": 55,
        "type": "service",
        "name": "Ping WAN",
        "information": "RRD loss 8%",
        "status": {"code": 2, "name": "CRITICAL"},
        "parent": {"id": 12, "name": "RTR-01"},
        "in_downtime": True,
        "acknowledged": True,
        "acknowledgement": {
            "entry_time": "2026-10-01T08:00:00Z",
            "author": {"name": "A. Traoré"},
            "comment": "Analyse en cours",
        },
        "last_status_change": "2026-10-01T07:55:00Z",
        "last_check": "2026-10-01T08:05:00Z",
        "next_check": "2026-10-01T08:10:00Z",
    }

    async def fake_resources(resource_types, extra=None):
        return [row]

    client._resources = fake_resources
    nodes = asyncio.run(client.fetch_nodes())
    alerts = asyncio.run(client.fetch_alerts())

    assert nodes[0].depends_on == ("centreon:host-12",)
    assert nodes[0].last_output == "RRD loss 8%"
    assert nodes[0].last_check_at is not None
    assert nodes[0].next_check_at is not None
    assert alerts[0].node_ref == "host-12"
    assert alerts[0].acknowledged_by == "A. Traoré"
    assert alerts[0].acknowledgement_note == "Analyse en cours"
    assert alerts[0].is_maintenance


def test_itop_progressively_drops_unsupported_ci_fields():
    client = ITopClient("http://itop")
    calls = []

    async def fake_call(operation, payload):
        fields = payload["output_fields"]
        calls.append(fields)
        if "support_team_id_friendlyname" in fields:
            raise ToolUnavailable("itop", "invalid attribute code")
        return {"objects": {"ci-1": {"key": "ci-1", "fields": {"name": "RTR-01"}}}}

    client._call = fake_call
    result = asyncio.run(
        client._get_class(
            "NetworkDevice",
            "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip,"
            "business_criticity,support_team_id_friendlyname,contact_id_friendlyname",
            ("business_criticity", "support_team_id_friendlyname", "contact_id_friendlyname"),
        )
    )

    assert len(calls) == 3
    assert "managementip" in calls[-1]
    assert "business_criticity" in calls[-1]
    assert "support_team_id_friendlyname" not in calls[-1]
    assert result["objects"]["ci-1"]["fields"]["name"] == "RTR-01"


def test_run_cycle_publishes_source_sla_targets_with_snapshot():
    class FakeClient:
        async def check(self):
            return ToolHealth(tool="itop", reachable=True)

        async def fetch_nodes(self):
            return []

        async def fetch_alerts(self):
            return []

        async def fetch_sla_targets(self):
            return [{"ref": "slt-1", "name": "WAN"}]

    class FakeStore:
        sla_targets = None

        async def write_tool_health(self, health):
            pass

        async def write_snapshot(self, nodes, alerts, meta, sla_targets=None):
            self.sla_targets = sla_targets

        async def diff_new_alerts(self, alerts):
            return []

        async def publish_new_alerts(self, alerts):
            raise AssertionError("no alert expected")

    store = FakeStore()
    asyncio.run(run_cycle({"itop": FakeClient()}, store, timeout_s=2))

    assert store.sla_targets == [{"tool": "itop", "ref": "slt-1", "name": "WAN"}]
