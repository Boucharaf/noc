"""Pannes Zabbix et Nagios : même règle que l'état affiché par le NOC.

Zabbix : événements des déclencheurs de DISPONIBILITÉ (icmpping en
priorité, sinon disponibilité de l'agent) ; pertes et latence ne sont pas des
pannes. Nagios : changements d'état HARD ; UNREACHABLE n'est pas une panne.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from collector import downtime
from integrations.nagios import NagiosClient
from integrations.zabbix import ZabbixClient, _availability_family

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)


def _ts(at):
    return str(int(at.timestamp()))


def test_availability_triggers_only():
    assert _availability_family("icmpping") == "icmp"
    assert _availability_family("icmpping[,3]") == "icmp"
    assert _availability_family("icmppingloss") is None
    assert _availability_family("icmppingsec") is None
    assert _availability_family("zabbix[host,agent,available]") == "agent"
    assert _availability_family("agent.ping") == "agent"
    assert _availability_family("system.cpu.util") is None


def test_zabbix_outages_from_trigger_events_icmp_first():
    client = ZabbixClient("http://zabbix", token="t")
    calls = []

    async def fake_call(method, params, authenticated=True):
        calls.append((method, params))
        if method == "item.get":
            return [
                # Hôte 10 : ICMP ET agent — seul l'ICMP compte.
                {"itemid": "1", "hostid": "10", "key_": "icmpping",
                 "triggers": [{"triggerid": "100"}]},
                {"itemid": "2", "hostid": "10", "key_": "zabbix[host,agent,available]",
                 "triggers": [{"triggerid": "101"}]},
                {"itemid": "3", "hostid": "10", "key_": "icmppingloss",
                 "triggers": [{"triggerid": "102"}]},
                # Hôte 20 : agent seul.
                {"itemid": "4", "hostid": "20", "key_": "agent.ping",
                 "triggers": [{"triggerid": "200"}]},
            ]
        return [
            {"eventid": "1", "clock": _ts(T0 + H), "value": "1", "objectid": "100"},
            {"eventid": "2", "clock": _ts(T0 + 2 * H), "value": "0", "objectid": "100"},
            {"eventid": "3", "clock": _ts(T0 + 3 * H), "value": "0", "objectid": "200"},
            {"eventid": "4", "clock": _ts(T0 + 4 * H), "value": "1", "objectid": "200"},
        ]

    client._call = fake_call
    records = asyncio.run(client.fetch_downtimes(T0))

    event_call = next(params for method, params in calls if method == "event.get")
    assert sorted(event_call["objectids"]) == ["100", "200"]   # ni 101 ni 102
    assert records == [
        {"object_id": "10", "start": T0 + H, "end": T0 + 2 * H, "tag": "icmp:100"},
        # Hôte 20 : un rétablissement d'abord (panne commencée plus tôt), puis
        # une panne en cours.
        {"object_id": "20", "start": None, "end": T0 + 3 * H, "tag": "agent:200"},
        {"object_id": "20", "start": T0 + 4 * H, "end": None, "tag": "agent:200"},
    ]
    assert downtime.closures(records) == [("20", "agent:200", T0 + 3 * H)]


def test_nagios_livestatus_log_hard_down_only(monkeypatch):
    monkeypatch.setenv("NAGIOS_MODE", "livestatus")
    client = NagiosClient("tcp://nagios:6557")
    queries = []

    async def fake_livestatus(query):
        queries.append(query)
        return [
            [int((T0 + H).timestamp()), "rt07", 1, "HARD"],
            [int((T0 + H).timestamp()) + 30, "rt07", 1, "SOFT"],
            [int((T0 + 2 * H).timestamp()), "rt07", 2, "HARD"],   # UNREACHABLE
            [int((T0 + 3 * H).timestamp()), "rt07", 1, "HARD"],
        ]

    client._livestatus = fake_livestatus
    records = asyncio.run(client.fetch_downtimes(T0))

    assert "GET log" in queries[0] and f"Filter: time > {int(T0.timestamp())}" in queries[0]
    assert records == [
        {"object_id": "rt07", "start": T0 + H, "end": T0 + 2 * H, "tag": "DOWN"},
        {"object_id": "rt07", "start": T0 + 3 * H, "end": None, "tag": "DOWN"},
    ]


def test_nagios_archivejson_statechangelist(monkeypatch):
    monkeypatch.setenv("NAGIOS_MODE", "statusjson")
    client = NagiosClient("http://nagios/nagios")

    async def fake_cgi(cgi, query, extra=None):
        if cgi == "statusjson.cgi":
            return {"hostlist": {"rt07": 2}}
        assert (cgi, query, extra["hostname"]) == ("archivejson.cgi", "statechangelist", "rt07")
        ms = lambda at: int(at.timestamp()) * 1000  # noqa: E731
        return {"statechangelist": [
            {"timestamp": ms(T0), "state": "down", "state_type": "hard"},   # état initial
            {"timestamp": ms(T0 + H), "state": "up", "state_type": "hard"},
            {"timestamp": ms(T0 + 2 * H), "state": "down", "state_type": "soft"},
            {"timestamp": ms(T0 + 3 * H), "state": "down", "state_type": "hard"},
            {"timestamp": ms(T0 + 4 * H), "state": "up", "state_type": "hard"},
        ]}

    client._cgi = fake_cgi
    records = asyncio.run(client.fetch_downtimes(T0))

    assert records == [
        {"object_id": "rt07", "start": None, "end": T0 + H, "tag": "DOWN"},
        {"object_id": "rt07", "start": T0 + 3 * H, "end": T0 + 4 * H, "tag": "DOWN"},
    ]


def test_priority_order_of_master_sources():
    rows = [{"tools": "nagios,zabbix"}]
    assert downtime.master_source(rows, {"zabbix", "nagios"}) == "zabbix"
    assert downtime.master_source(rows, {"nagios"}) == "nagios"
    assert downtime.master_source([{"tools": "centreon,zabbix"}], set(downtime.SOURCES)) == \
        "centreon"
