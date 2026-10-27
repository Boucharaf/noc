"""Correspondances outil source -> vocabulaire du NOC.

Chaque test fige une erreur de lecture constatée en revue : un code d'état
lu dans la mauvaise table, une clé d'item mal interprétée, une série
entrelacée. Ce sont des erreurs silencieuses — l'écran affiche un chiffre
plausible et faux — d'où des tests dédiés.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from collector.merge import merge_nodes
from integrations.models import Node
from integrations.nagios import NagiosClient
from integrations.normalize import combine_series
from integrations.nsp import NSPClient
from integrations.zabbix import _acknowledged_at, _host_state, _metric_for_item, _to_noc_unit

NOW_MS = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _nagios(monkeypatch, mode="statusjson"):
    monkeypatch.setenv("NAGIOS_MODE", mode)
    return NagiosClient("http://nagios/nagios", "nagiosadmin", "secret")


def test_nagios_statusjson_uses_cgi_bitmask_states(monkeypatch):
    client = _nagios(monkeypatch)
    responses = {
        ("statusjson.cgi", "hostlist"): {
            "hostlist": {
                "web-01": {"status": 2, "last_state_change": NOW_MS},
                "rt-02": {
                    "status": 4,
                    "last_state_change": NOW_MS,
                    "plugin_output": "CRITICAL - 100% packet loss",
                },
                "sw-03": {"status": 8, "last_state_change": NOW_MS},
                "new-04": {"status": 1},
                "maint-05": {
                    "status": 4,
                    "scheduled_downtime_depth": 1,
                    "last_state_change": NOW_MS,
                },
            }
        },
        ("objectjson.cgi", "hostlist"): {
            "hostlist": {"web-01": {"address": "10.0.0.1", "alias": "Serveur web"}}
        },
        ("objectjson.cgi", "hostgrouplist"): {
            "hostgrouplist": {"Site/Ouaga": {"members": ["web-01"]}}
        },
        ("statusjson.cgi", "servicelist"): {
            "servicelist": {
                "web-01": {
                    "HTTP": {"status": 2, "last_state_change": NOW_MS},
                    "Disk": {"status": 4, "last_state_change": NOW_MS},
                    "Load": {
                        "status": 16,
                        "last_state_change": NOW_MS,
                        "problem_has_been_acknowledged": True,
                    },
                    "Pending": {"status": 1},
                }
            }
        },
    }

    async def fake_cgi(cgi, query, extra=None):
        return responses[(cgi, query)]

    monkeypatch.setattr(client, "_cgi", fake_cgi)
    nodes = {node.ref: node for node in asyncio.run(client.fetch_nodes())}
    alerts = {alert.ref: alert for alert in asyncio.run(client.fetch_alerts())}

    # 2 = UP en masque de bits : l'ancienne table le lisait « down ».
    assert nodes["web-01"].state == "up"
    assert nodes["web-01"].ip == "10.0.0.1"
    assert nodes["web-01"].site == "Ouaga"
    assert nodes["rt-02"].state == "down"
    assert nodes["sw-03"].state == "degraded"
    assert nodes["new-04"].state == "silent"
    assert nodes["maint-05"].state == "maintenance"

    # Un service OK (2) n'est PAS une alerte ; 4 = WARNING, 16 = CRITICAL.
    assert "web-01/HTTP" not in alerts
    assert "web-01/Pending" not in alerts
    assert alerts["web-01/Disk"].severity == "medium"
    assert alerts["web-01/Load"].severity == "critical"
    assert alerts["web-01/Load"].acknowledged is True
    # Les hôtes en panne remontent aussi.
    assert alerts["rt-02"].severity == "critical"
    assert alerts["sw-03"].severity == "high"


def test_nagios_livestatus_port_comes_from_url(monkeypatch):
    client = _nagios(monkeypatch, "livestatus")
    client_with_port = NagiosClient("tcp://nagios.example:7000")
    assert (client.livestatus_host, client.livestatus_port) == ("nagios", 6557)
    assert (client_with_port.livestatus_host, client_with_port.livestatus_port) == (
        "nagios.example",
        7000,
    )


def test_nsp_restconf_alarm_container_and_fdn_identifier(monkeypatch):
    monkeypatch.setenv("NSP_FM_MODE", "yang")
    client = NSPClient("https://nsp.example")

    async def fake_get(path, params=None):
        return {
            "nsp-fault:alarm-list": {
                "alarm": [
                    {
                        "alarm-fdn": "fdn:model:fm:Alarm:1",
                        "severity": "major",
                        "additional-text": "Port down",
                        "first-time-detected": "2026-10-01T08:00:00Z",
                        "ne-id": "10.1.1.1",
                        "ne-name": "PE-OUAGA",
                        "acknowledged": False,
                    },
                    {
                        "alarm-fdn": "fdn:model:fm:Alarm:2",
                        "severity": "cleared",
                        "first-time-detected": "2026-10-01T08:00:00Z",
                    },
                ]
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    alerts = asyncio.run(client.fetch_alerts())
    assert len(alerts) == 1
    assert alerts[0].ref == "fdn:model:fm:Alarm:1"
    assert alerts[0].severity == "high"
    assert alerts[0].node_ref == "10.1.1.1"


def test_nsp_classic_camel_case_and_epoch_milliseconds(monkeypatch):
    monkeypatch.setenv("NSP_FM_MODE", "classic")
    client = NSPClient("https://nsp.example")

    async def fake_get(path, params=None):
        return {
            "response": {
                "data": [
                    {
                        "alarmFdn": "A1",
                        "severity": "critical",
                        "firstTimeDetected": NOW_MS,
                        "neId": "N1",
                        "isAcknowledged": "true",
                    },
                ]
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    (alert,) = asyncio.run(client.fetch_alerts())
    assert alert.since == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert alert.acknowledged is True


def test_zabbix_item_parameters_decide_the_metric():
    def metric(key):
        return _metric_for_item({"key_": key})

    assert metric("system.cpu.util") == "cpu_pct"
    assert metric("system.cpu.util[,idle]") == "cpu_pct"
    assert metric("system.cpu.util[,iowait]") is None
    assert metric("system.cpu.util[,user]") is None
    assert metric("net.if.in[eth0]") == "bandwidth_in_mbps"
    assert metric("net.if.in[eth0,errors]") == "if_errors"
    assert metric("net.if.in[eth0,packets]") is None
    assert metric("proc.num[]") == "proc_count"
    assert metric("proc.num[nginx]") is None
    assert metric("system.cpu.load[all,avg5]") is None
    assert metric("vfs.fs.dependent.size[/,pused]") == "disk_pct"
    assert metric("icmpping") == "availability_pct"

    idle = {"key_": "system.cpu.util[,idle]"}
    assert _to_noc_unit(idle, "cpu_pct", 85.0) == 15.0
    available = {"key_": "vm.memory.size[pavailable]"}
    assert _to_noc_unit(available, "ram_pct", 40.0) == 60.0


def test_zabbix_snmp_template_items():
    """Clés des gabarits « … by SNMP » (relevées sur Zabbix 7.0.23)."""
    def metric(key):
        return _metric_for_item({"key_": key})

    assert metric("system.cpu.util[snmp,0]") == "cpu_pct"
    assert metric("vm.memory.util[snmp]") == "ram_pct"
    assert metric("net.if.in[ifHCInOctets.2]") == "bandwidth_in_mbps"
    assert metric("net.if.out[ifHCOutOctets.2]") == "bandwidth_out_mbps"
    assert metric("net.if.in.errors[ifInErrors.2]") is None
    assert metric("system.cpu.idle[ssCpuRawIdle.0]") is None


def test_zabbix_bandwidth_unit_follows_item_units():
    """Les gabarits rendent déjà des bits/s (unité « bps ») : ne pas
    remultiplier par 8. L'item brut, sans unité, rend des octets/s."""
    snmp = {"key_": "net.if.in[ifHCInOctets.2]", "units": "bps"}
    assert _to_noc_unit(snmp, "bandwidth_in_mbps", 2_000_000) == 2.0
    raw = {"key_": "net.if.in[eth0]", "units": ""}
    assert _to_noc_unit(raw, "bandwidth_in_mbps", 250_000) == 2.0


def test_zabbix_inventory_coordinates():
    from integrations.zabbix import _coordinates

    assert _coordinates({"location_lat": "11.6636", "location_lon": "-1.0731"}) == {
        "latitude": 11.6636,
        "longitude": -1.0731,
    }
    assert _coordinates({"location_lat": "12,37", "location_lon": "-1,52"}) == {
        "latitude": 12.37,
        "longitude": -1.52,
    }
    assert _coordinates([]) == {}  # inventaire désactivé
    assert _coordinates({"location_lat": "", "location_lon": ""}) == {}
    assert _coordinates({"location_lat": "0", "location_lon": "0"}) == {}
    assert _coordinates({"location_lat": "123", "location_lon": "5"}) == {}


def test_zabbix_partial_loss_is_degraded_not_up():
    host = {
        "status": "0",
        "items": [
            {"key_": "icmpping", "lastvalue": "1"},
            {"key_": "icmppingloss", "lastvalue": "40"},
        ],
    }
    assert _host_state(host, []) == "degraded"


def test_zabbix_acknowledgement_time_ignores_comment_only_actions():
    acknowledges = [
        {"clock": "200", "action": "4"},  # message seul
        {"clock": "300", "action": "6"},  # acquittement + message
    ]
    assert _acknowledged_at(acknowledges) == datetime.fromtimestamp(300, tz=timezone.utc)


def test_series_are_bucketed_not_interleaved():
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    eth0 = [(base + timedelta(seconds=5), 10.0), (base + timedelta(seconds=65), 12.0)]
    eth1 = [(base + timedelta(seconds=35), 1.0), (base + timedelta(seconds=95), 3.0)]
    points = combine_series([eth0, eth1], "bandwidth_in_mbps", 60)
    # Une valeur par minute, somme des interfaces — pas 4 points alternés.
    assert [p.value for p in points] == [11.0, 15.0]

    root = [(base, 20.0)]
    data = [(base, 95.0)]
    (disk,) = combine_series([root, data], "disk_pct", 60)
    assert disk.value == 95.0


def test_stale_state_does_not_conflict_with_fresh_observation():
    common = {"hostname": "rt-01", "ip": "10.0.0.1", "name": "rt-01"}
    nodes = [
        Node(tool="zabbix", ref="1", state="up", **common),
        Node(tool="centreon", ref="host-1", state="down", stale=True, **common),
    ]
    merged, _report = merge_nodes(nodes)
    assert len(merged) == 1
    assert merged[0].state == "up"
    assert merged[0].state_conflict == {}


def test_itop_ticket_without_ci_is_linked_by_device_cited_in_title():
    from integrations.itop import ITopClient

    client = ITopClient("https://itop.example")
    ticket = client._ticket(
        "Incident",
        {
            "key": "37238",
            "fields": {
                "id": "37238",
                "title": "Alerte NetXMS: '' sur 'MANGA-DREP-CPEK01'",
                "start_date": "2026-09-05 18:00:42",
                "functionalcis_list": [],
            },
        },
    )
    assert ticket["cis"] == [{"ref": None, "name": "MANGA-DREP-CPEK01", "from_title": True}]
    plain = client._ticket(
        "Incident",
        {"key": "1", "fields": {"id": "1", "title": "Incident de connexion", "start_date": "2026-09-05"}},
    )
    assert plain["cis"] == []


def test_zabbix_account_without_host_rights_is_reported():
    from integrations.zabbix import ZabbixClient

    client = ZabbixClient("https://zabbix.example", token="t")

    async def call(method, params, authenticated=True):
        return []

    client._call = call
    assert asyncio.run(client.fetch_nodes()) == []
    assert "aucun hôte visible" in client.collection_warnings[0]


def test_zabbix_zero_latency_means_no_reply():
    """icmppingsec = 0 : l'hôte n'a pas répondu, ce n'est pas une latence."""
    from integrations.zabbix import _no_reply

    assert _no_reply("latency_ms", 0.0)
    assert not _no_reply("latency_ms", 0.4)
    assert not _no_reply("packet_loss_pct", 0.0)


def test_source_severity_keeps_tool_vocabulary():
    """Gravité d'origine affichée en clair, sans perdre la gravité commune."""
    from integrations.normalize import severity, source_severity

    assert source_severity("zabbix", "5") == "Désastre"
    assert severity("zabbix", "5") == "critical"
    assert source_severity("netxms", 3) == "Majeure"
    assert source_severity("centreon_host", "2") == "Hôte injoignable"
    assert source_severity("nsp", "major") == "Majeure"
    assert source_severity("zabbix", None) is None
