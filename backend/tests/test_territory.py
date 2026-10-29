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
    async def no_windows(_at=None):
        return []

    monkeypatch.setattr(geo_service.node_service, "active_windows", no_windows)
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


def test_at_risk_keeps_open_incidents_near_or_past_their_target(monkeypatch):
    now = datetime.now(timezone.utc)
    records = [
        {**RECORDS[2], "ref": "1", "since": (now - timedelta(hours=5)).isoformat()},
        {**RECORDS[2], "ref": "2", "since": (now - timedelta(minutes=200)).isoformat()},
        {**RECORDS[2], "ref": "3", "since": (now - timedelta(minutes=30)).isoformat()},
    ]
    _patch_snapshot(monkeypatch, records=records)
    monkeypatch.setattr(
        sla_service,
        "targets",
        lambda _db: {"critical": SimpleNamespace(tta_target_minutes=15, ttr_target_minutes=240)},
    )
    rows = asyncio.run(incident_service.at_risk(None))
    # Dépassé d'abord, puis celui à qui il reste 40 min ; le ticket récent
    # (210 min de marge) n'est pas encore à risque.
    assert [row["key"] for row in rows] == ["itop:1", "itop:2"]
    assert rows[0]["breached"] is True
    assert rows[1]["breached"] is False


def test_incident_kpis_count_recurrence_causes_and_reopening(monkeypatch):
    _patch_snapshot(monkeypatch)
    now = datetime.now(timezone.utc)
    opened = (now - timedelta(hours=10)).isoformat()
    resolved = (now - timedelta(hours=9)).isoformat()

    def ticket(name, status, resolution, code, org="DGI"):
        return {
            "severity": "critical",
            "status": status,
            "organisation": org,
            "start_date": opened,
            "resolution_date": resolution,
            "assignment_date": None,
            "resolution_code": code,
            "cis": [{"ref": None, "name": name}],
        }

    async def history(_start, _end):
        return [
            ticket("sw-ouaga", "resolved", resolved, "hardware repair"),
            ticket("sw-ouaga", "closed", resolved, ""),
            ticket("sw-ouaga", "assigned", resolved, ""),  # rouvert
            ticket("rt-ouaga", "new", None, None, org=None),
        ]

    monkeypatch.setattr(incident_service, "_history", history)
    monkeypatch.setattr(sla_service, "targets", lambda _db: {})
    kpis = asyncio.run(incident_service.incident_kpis(None))

    assert kpis["total"] == 4
    assert kpis["resolved"] == 2
    assert kpis["resolution_rate_pct"] == 50.0
    assert kpis["reopened"] == 1
    assert kpis["recurrent_nodes"] == 1
    assert kpis["recurrent"][0]["node_key"] == "n2"
    assert kpis["recurrent"][0]["incidents"] == 3
    assert kpis["cause_available"] is True
    assert kpis["without_cause"] == 1
    assert kpis["without_cause_pct"] == 50.0
    assert kpis["causes"] == [{"cause": "hardware repair", "count": 1, "share_pct": 100.0}]
    assert kpis["top_sites"][0]["site"] == "Ouaga DGI"
    assert {row["organisation"] for row in kpis["by_organisation"]} == {
        "DGI",
        "Organisation non renseignée",
    }


def test_incident_kpis_do_not_report_missing_cause_field_as_zero(monkeypatch):
    _patch_snapshot(monkeypatch)
    now = datetime.now(timezone.utc)

    async def history(_start, _end):
        return [
            {
                "severity": "high",
                "status": "resolved",
                "start_date": (now - timedelta(hours=3)).isoformat(),
                "resolution_date": (now - timedelta(hours=2)).isoformat(),
                "resolution_code": None,
                "cis": [],
            }
        ]

    monkeypatch.setattr(incident_service, "_history", history)
    monkeypatch.setattr(sla_service, "targets", lambda _db: {})
    kpis = asyncio.run(incident_service.incident_kpis(None))
    assert kpis["cause_available"] is False
    assert kpis["without_cause_pct"] is None
