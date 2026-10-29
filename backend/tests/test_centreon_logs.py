"""Rejeu d'un export du journal Centreon (visualisation locale).

Le journal ne donne que des événements : l'état de chaque hôte et de chaque
service se déduit en les rejouant dans l'ordre, sur les seuls états HARD.
"""
import asyncio

from integrations.centreon_logs import CentreonLogClient
from integrations.config import build_client

HEADER = (
    "log_id\tctime\thost_id\thost_name\tinstance_name\tissue_id\tmsg_type\t"
    "notification_cmd\tnotification_contact\toutput\tretry\tservice_description\t"
    "service_id\tstatus\ttype\n"
)


def _line(log_id, ctime, host_id, host, msg_type, output, service="", service_id="NULL",
          status=0, hard=1):
    return (
        f"{log_id}\t{ctime}\t{host_id}\t{host}\tpoller\tNULL\t{msg_type}\t\t\t{output}\t1\t"
        f"{service}\t{service_id}\t{status}\t{hard}\n"
    )


def _replay(tmp_path, lines):
    export = tmp_path / "alertes.sql"
    export.write_text(HEADER + "".join(lines), encoding="utf8")
    client = CentreonLogClient(export.as_uri())

    async def read():
        try:
            return await client.check(), await client.fetch_nodes(), await client.fetch_alerts()
        finally:
            await client.aclose()

    return asyncio.run(read())


def test_replay_gives_last_hard_state(tmp_path):
    health, nodes, alerts = _replay(tmp_path, [
        # Hôte 1 : contrôle d'hôte OK puis DOWN confirmé, acquitté.
        _line(1, 1000, 1, "rt-1", 1, "OK - 10.0.0.1 rta 1ms lost 0%"),
        _line(2, 2000, 1, "rt-1", 1, "CRITICAL - 10.0.0.1 rta nan lost 100%", status=1),
        _line(3, 2500, 1, "rt-1", 11, "acquitté", status=1),
        # Hôte 2 : un service CRITICAL d'abord SOFT (ignoré), puis HARD ;
        # un second service revenu à la normale.
        _line(4, 1000, 2, "srv-2", 0, "OK", "Disk-/", 10),
        _line(5, 1100, 2, "srv-2", 0, "CRITICAL soft", "Disk-/", 10, status=2, hard=0),
        _line(6, 1200, 2, "srv-2", 0, "CRITICAL: / 98%", "Disk-/", 10, status=2),
        _line(7, 1300, 2, "srv-2", 0, "CRITICAL: / 99%", "Disk-/", 10, status=2),
        _line(8, 1000, 2, "srv-2", 0, "WARNING", "Sys-Load", 11, status=1),
        _line(9, 1400, 2, "srv-2", 0, "OK", "Sys-Load", 11),
        _line(10, 1500, 2, "srv-2", 0, "OK - 10.0.0.2 rta 2ms", "Svc-Ping", 12),
        # Hôte 3 : tous ses services nominaux, aucune ligne d'hôte.
        _line(11, 1000, 3, "srv-3", 0, "OK", "Proc-sshd", 13),
        # Message du moteur, sans hôte.
        _line(12, 900, 0, "", 5, "Processing object config file"),
    ])

    assert health.reachable and "12 lignes" in health.version
    by_ref = {node.ref: node for node in nodes}
    assert set(by_ref) == {"host-1", "host-2", "host-3"}
    assert (by_ref["host-1"].state, by_ref["host-1"].ip) == ("down", "10.0.0.1")
    assert (by_ref["host-2"].state, by_ref["host-2"].ip) == ("degraded", "10.0.0.2")
    assert by_ref["host-3"].state == "up"

    host_alert, disk = sorted(alerts, key=lambda a: a.ref)
    assert host_alert.ref == "host-1" and host_alert.severity == "critical"
    assert host_alert.acknowledged and host_alert.node_ref == "host-1"
    assert disk.ref == "service-10" and disk.node_ref == "host-2"
    # Daté du PREMIER état HARD critique, pas du dernier contrôle.
    assert disk.since.timestamp() == 1200
    assert disk.message == "Disk-/ : CRITICAL: / 99%"
    assert not disk.acknowledged


def test_only_ok_export_gives_hosts_without_alerts(tmp_path):
    _health, nodes, alerts = _replay(tmp_path, [
        _line(1, 1000, 5, "pmg-1", 0, "Postfix Mailqueue OK", "Postfix-MailQueue", 50),
    ])
    assert [node.state for node in nodes] == ["up"]
    assert alerts == []


def test_wrong_file_is_reported_not_published_empty(tmp_path):
    export = tmp_path / "autre.sql"
    export.write_text("CREATE TABLE x (id int);\n", encoding="utf8")
    client = CentreonLogClient(export.as_uri())

    async def check():
        try:
            return await client.check()
        finally:
            await client.aclose()

    health = asyncio.run(check())
    assert not health.reachable
    assert "centreon_storage.logs" in health.error


def test_url_form_picks_the_connector(monkeypatch):
    monkeypatch.setenv("CENTREON_API_URL", "file:///srv/dumps/alertes.sql")
    assert type(build_client("centreon")).__name__ == "CentreonLogClient"
    monkeypatch.setenv("CENTREON_API_URL", "https://centreon.example/centreon")
    assert type(build_client("centreon")).__name__ == "CentreonClient"
