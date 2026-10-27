"""Territoire (région > province > site > nœud), incidents iTop et leurs SLA."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services import geo_service, incident_service, live_service, sla_service
from collector.merge import merge_nodes
from integrations.models import Node
from integrations.normalize import locality_from_groups, locality_key, sql_to_dt

NODES = [
    {
        "id": "n1",
        "name": "RT-OUAGA",
        "hostname": "rt-ouaga",
        "state": "up",
        "site": "Ouaga DGI",
        "province": "Kadiogo",
        "region": "Kadiogo",
        "sources": {"netxms": "1"},
        "latitude": 12.3,
        "longitude": -1.5,
    },
    {
        "id": "n2",
        "name": "SW-OUAGA",
        "hostname": "sw-ouaga",
        "state": "down",
        "site": "Ouaga DGI",
        "province": "Kadiogo",
        "region": "Kadiogo",
        "sources": {"netxms": "2"},
        "latitude": 12.4,
        "longitude": -1.5,
    },
    {
        "id": "n3",
        "name": "RT-BOBO",
        "hostname": "rt-bobo",
        "state": "up",
        "site": "Bobo Mairie",
        "province": "Houet",
        "region": "Guiriko",
        "sources": {"zabbix": "10"},
    },
    {
        "id": "n4",
        "name": "AP-X",
        "hostname": "ap-x",
        "state": "unknown",
        "site": None,
        "province": None,
        "region": None,
        "sources": {"netxms": "4"},
    },
    {
        "id": "itop:7",
        "name": "rt-bobo",
        "hostname": "rt-bobo",
        "state": "unknown",
        "site": "Bobo Mairie",
        "province": None,
        "region": None,
        "sources": {"itop": "7"},
    },
]

RECORDS = [
    {
        "tool": "netxms",
        "ref": "a1",
        "node_ref": "2",
        "severity": "critical",
        "kind": "technical",
        "message": "down",
        "since": "2026-10-01T08:00:00+00:00",
    },
    {
        "tool": "zabbix",
        "ref": "a2",
        "node_ref": "10",
        "severity": "high",
        "kind": "technical",
        "message": "loss",
        "since": "2026-10-01T08:00:00+00:00",
    },
    {
        "tool": "itop",
        "ref": "1",
        "node_ref": "7",
        "node_name": "rt-bobo",
        "severity": "critical",
        "kind": "itsm_ticket",
        "message": "Coupure Bobo",
        "since": "2026-10-01T07:00:00+00:00",
        "ticket_ref": "I-000001",
        "details": {"status": "new", "agent": None, "cis": []},
    },
]


def _patch_snapshot(monkeypatch, nodes=NODES, records=RECORDS):
    async def get_nodes():
        return [dict(node) for node in nodes]

    async def get_alerts():
        return [dict(record) for record in records]

    async def zero():
        return 0

    async def fresh():
        return False

    monkeypatch.setattr(live_service, "get_nodes", get_nodes)
    monkeypatch.setattr(live_service, "get_alerts", get_alerts)
    monkeypatch.setattr(geo_service.node_service, "_active_windows", lambda _db, _at: [])
    monkeypatch.setattr(live_service, "snapshot_age_s", zero)
    monkeypatch.setattr(live_service, "is_stale", fresh)


def test_locality_helpers_ignore_accents_and_read_group_conventions():
    assert locality_key("KUILSÉ") == locality_key("Kuilse")
    assert locality_from_groups(["Site/Ouaga", "Province/Kadiogo", "Région/Kadiogo"]) == {
        "site": "Ouaga",
        "province": "Kadiogo",
        "region": "Kadiogo",
    }


def test_scope_filters_by_level_unknown_and_search():
    assert {n["id"] for n in geo_service.scope_nodes(NODES, region="kadiogo")} == {"n1", "n2"}
    assert {
        n["id"] for n in geo_service.scope_nodes(NODES, region=geo_service.UNKNOWN["region"])
    } == {
        "n4",
        "itop:7",
    }
    assert [n["id"] for n in geo_service.scope_nodes(NODES, search="bobo")] == ["n3", "itop:7"]


def test_breakdown_descends_one_level_and_counts_alerts_and_incidents(monkeypatch):
    _patch_snapshot(monkeypatch)
    national = asyncio.run(geo_service.breakdown(None))
    assert national["level"] == "region"
    rows = {row["name"]: row for row in national["rows"]}
    assert rows["Kadiogo"]["nodes"] == 2
    assert rows["Kadiogo"]["availability_pct"] == 50.0
    assert rows["Kadiogo"]["alerts_critical"] == 1
    # Le ticket iTop porte sur un CI non localisé : il compte dans
    # « Région non renseignée », jamais dans une région au hasard.
    assert rows[geo_service.UNKNOWN["region"]]["incidents"] == 1
    # Les « non renseignés » sont classés en dernier.
    assert national["rows"][-1]["unlocated"] is True

    site = asyncio.run(
        geo_service.breakdown(None, region="Kadiogo", province="Kadiogo", site="Ouaga DGI")
    )
    assert site["level"] == "node"
    assert [row["key"] for row in site["rows"]] == ["n2", "n1"]  # en panne d'abord


def test_incident_shows_alerts_of_supervised_namesake(monkeypatch):
    _patch_snapshot(monkeypatch)
    monkeypatch.setattr(sla_service, "targets", lambda _db: {})
    detail = asyncio.run(incident_service.get_incident(None, "itop:1"))
    # Le CI iTop « rt-bobo » n'est pas fusionné avec l'hôte Zabbix (pas d'IP
    # commune) : ses alertes sont retrouvées par le nom.
    assert [alert["key"] for alert in detail["alerts"]] == ["zabbix:a2"]
    assert {view["node_key"] for view in detail["tool_views"]} == {"itop:7", "n3"}


def test_incident_list_excludes_tool_alerts(monkeypatch):
    _patch_snapshot(monkeypatch)
    monkeypatch.setattr(sla_service, "targets", lambda _db: {})
    listing = asyncio.run(incident_service.list_incidents(None))
    assert [row["key"] for row in listing["incidents"]] == ["itop:1"]
    assert listing["unassigned"] == 1


def test_sla_state_counts_open_overdue_incident_as_breached():
    goals = {"critical": SimpleNamespace(tta_target_minutes=15, ttr_target_minutes=240)}
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    opened = now - timedelta(hours=5)
    assert (
        incident_service._sla_state("critical", opened, None, None, goals, now)["ttr_status"]
        == "breached"
    )
    assert (
        incident_service._sla_state("critical", now - timedelta(hours=1), None, None, goals, now)[
            "ttr_status"
        ]
        == "running"
    )
    assert (
        incident_service._sla_state(
            "critical", opened, None, opened + timedelta(hours=3), goals, now
        )["ttr_status"]
        == "met"
    )
    assert (
        incident_service._sla_state("low", opened, None, None, goals, now)["ttr_status"]
        == "no_target"
    )


def test_sla_grouped_by_region(monkeypatch):
    _patch_snapshot(monkeypatch)
    now = datetime.now(timezone.utc)

    async def history(_start, _end):
        opened = (now - timedelta(hours=10)).isoformat()
        return [
            {
                "severity": "critical",
                "start_date": opened,
                "resolution_date": (now - timedelta(hours=9)).isoformat(),
                "assignment_date": None,
                "cis": [{"ref": None, "name": "rt-ouaga"}],
            },
            {
                "severity": "critical",
                "start_date": opened,
                "resolution_date": None,
                "assignment_date": None,
                "cis": [{"ref": None, "name": "sw-ouaga"}],
            },
        ]

    monkeypatch.setattr(incident_service, "_history", history)
    monkeypatch.setattr(
        sla_service,
        "targets",
        lambda _db: {"critical": SimpleNamespace(tta_target_minutes=15, ttr_target_minutes=240)},
    )
    result = asyncio.run(incident_service.sla_by_group(None, "region"))
    (kadiogo,) = [row for row in result["rows"] if row["name"] == "Kadiogo"]
    assert kadiogo["evaluated"] == 2
    assert kadiogo["breached"] == 1
    assert kadiogo["compliance_pct"] == 50.0


def test_itop_dates_are_read_in_itop_timezone():
    paris = ZoneInfo("Europe/Paris")
    assert sql_to_dt("2026-10-26 19:14:16", paris) == datetime(
        2026, 10, 26, 18, 14, 16, tzinfo=timezone.utc
    )
    assert sql_to_dt("2026-10-26 19:14:16") == datetime(
        2026, 10, 26, 19, 14, 16, tzinfo=timezone.utc
    )


def test_site_locality_is_inherited_only_when_unambiguous():
    netxms = Node(
        tool="netxms",
        ref="1",
        name="RT",
        hostname="rt",
        site="Bobo Mairie",
        province="Houet",
        region="Guiriko",
    )
    zabbix = Node(tool="zabbix", ref="9", name="SRV", hostname="srv", site="BOBO MAIRIE")
    merged, _ = merge_nodes([netxms, zabbix])
    by_tool = {next(iter(node.sources)): node for node in merged}
    assert (by_tool["zabbix"].province, by_tool["zabbix"].region) == ("Houet", "Guiriko")
