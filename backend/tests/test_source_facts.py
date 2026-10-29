"""Données des API jusque-là ignorées : inventaire et contexte Zabbix, faits
de fiche dans la fusion, liens et disponibilité de l'agence, contrat iTop."""
import asyncio

from collector.merge import merge_nodes
from integrations.models import Node
from integrations.zabbix import _inventory_details, _problem_details

from app.services import incident_service, metrics_service


def test_zabbix_inventory_keeps_filled_fields_only():
    assert _inventory_details({"vendor": "Huawei", "model": " ", "serialno_a": "S1"}) == {
        "inventory": {"vendor": "Huawei", "serial": "S1"}
    }
    # Inventaire désactivé sur l'hôte : Zabbix renvoie une liste vide.
    assert _inventory_details([]) == {}


def test_zabbix_problem_context():
    details = _problem_details(
        {
            "tags": [{"tag": "service", "value": "RESINA"}, {"tag": "", "value": "x"}],
            "opdata": "Utilisation : 95 %",
            "suppressed": "1",
            "cause_eventid": "4242",
        },
        [
            {"clock": "1786000600", "message": "Équipe terrain prévenue",
             "name": "Awa", "surname": "Sawadogo", "action": "6"},
            {"clock": "1786000000", "message": "", "action": "2"},
            {"clock": "1786000300", "message": "Je regarde", "username": "tech1"},
        ],
    )
    assert details["tags"] == [{"tag": "service", "value": "RESINA"}]
    assert details["opdata"] == "Utilisation : 95 %"
    assert details["suppressed"] is True
    assert details["cause_ref"] == "4242"
    # Commentaires vides écartés, ordre chronologique.
    assert [(a["user"], a["message"]) for a in details["actions"]] == [
        ("tech1", "Je regarde"), ("Awa Sawadogo", "Équipe terrain prévenue"),
    ]
    # Un problème qui n'est le symptôme de rien.
    assert "cause_ref" not in _problem_details({"cause_eventid": "0"}, [])


def test_merge_keeps_facts_per_source_and_names_single_source_nodes():
    merged, report = merge_nodes([
        Node(tool="netxms", ref="7", name="RT07", hostname="rt07", ip="10.0.0.7",
             details={"inventory": {"vendor": "Cisco"}}),
        Node(tool="zabbix", ref="70", name="RT07", hostname="rt07", ip="10.0.0.7",
             details={"inventory": {"serial": "FDO1"}}),
        Node(tool="zabbix", ref="80", name="SW08", hostname="sw08", ip="10.0.0.8"),
    ])
    rt07 = next(node for node in merged if node.name == "RT07")
    assert rt07.details == {
        "netxms": {"inventory": {"vendor": "Cisco"}},
        "zabbix": {"inventory": {"serial": "FDO1"}},
    }
    assert report.single_source == [{"id": "zabbix:80", "name": "SW08", "tool": "zabbix"}]


def test_link_summary_and_agency_availability():
    nodes = [
        {"details": {"netxms": {
            "interfaces": {"total": 4, "enabled": 3, "enabled_up": 1, "enabled_down": 2,
                           "watched": 2, "watched_down": 1, "capacity_bps": 10**9},
            "availability": {"pct": 90.0, "mttr_h": 1.0, "mtbf_h": 10.0, "failures": 3},
        }}},
        {"details": {"netxms": {
            "interfaces": {"total": 2, "enabled": 2, "enabled_up": 2, "enabled_down": 0,
                           "watched": 2, "watched_down": 0, "capacity_bps": 10**8},
            "availability": {"pct": 100.0, "mttr_h": None, "mtbf_h": 20.0, "failures": 0},
        }}},
        {"details": {}},
    ]
    links = metrics_service.link_summary(nodes)
    assert links["nodes"] == 2
    assert links["watched_up_pct"] == 75.0     # 3 liens actifs sur 4 attendus
    assert links["enabled_up_pct"] == 60.0     # 3 sur 5, ports libres compris
    assert links["capacity_bps"] == 1_100_000_000

    agency = metrics_service.agency_availability(nodes)
    assert agency == {
        "nodes": 2, "avg_pct": 95.0, "avg_mttr_h": 1.0, "avg_mtbf_h": 15.0,
        "failures": 3, "computed_at": None,
    }
    assert metrics_service.link_summary([{"details": {}}]) is None
    assert metrics_service.agency_availability([]) is None


def test_itop_contract_targets_in_minutes_strictest_kept(monkeypatch):
    class Store:
        def __init__(self):
            self.saved = None

        async def get_history(self, _key):
            return None

        async def set_history(self, _key, value, _ttl):
            self.saved = value

    class Client:
        async def fetch_sla_targets(self):
            return [
                {"ref": "1", "name": "TTO P1", "metric": "tto", "value": "15",
                 "unit": "minutes", "priority": "1", "request_type": "incident"},
                {"ref": "2", "name": "TTR P1", "metric": "TTR", "value": "4",
                 "unit": "hours", "priority": "1", "request_type": "incident"},
                {"ref": "3", "name": "TTR P1 renforcé", "metric": "ttr", "value": "2",
                 "unit": "hours", "priority": "1", "request_type": ""},
                # Demande de service : hors comparaison avec les incidents.
                {"ref": "4", "name": "TTR demandes", "metric": "ttr", "value": "1",
                 "unit": "hours", "priority": "1", "request_type": "service_request"},
            ]

    store = Store()
    monkeypatch.setattr(incident_service, "get_store", lambda: store)
    monkeypatch.setattr(incident_service.history_service, "_client", lambda _tool: Client())
    result = asyncio.run(incident_service.contract_targets())

    assert result["available"] is True
    assert result["by_severity"] == {"critical": {"tto": 15.0, "ttr": 120.0}}
    assert len(result["targets"]) == 4
    assert store.saved == result


def test_netxms_database_reads_facts_only_when_granted():
    from integrations.netxms_db import NetXMSDatabaseClient

    def client_with(granted: bool):
        client = NetXMSDatabaseClient("postgresql://netxms-db/netxms")

        async def query(sql):
            if "information_schema.columns" in sql:
                # Nombre de colonnes accessibles : toutes, ou aucune. Chaînes
                # citées de la requête, moins le schéma et les noms de tables.
                wanted = sql.count("'") // 2 - 1 - sql.count("table_name =")
                return [(wanted if granted else 0,)]
            if "FROM nodes" in sql:
                return [(7, 1786000000, 0, "Cisco", "ISR4331", None, "", None)]
            if "noc_availability_attributes" in sql:
                return [(7, "perAvailability", "99.5"), (7, "NumFailures", "2")]
            if "FROM interfaces" in sql:
                return [(7, 1, 1, 0, 1_000_000_000), (7, 1, 2, 2, 0)]
            raise AssertionError(sql)

        client._query = query
        return client

    async def read(client):
        try:
            return await client._details()
        finally:
            await client.aclose()

    facts = asyncio.run(read(client_with(True)))["7"]
    assert facts["inventory"] == {"vendor": "Cisco", "model": "ISR4331"}
    assert "down_since" not in facts  # 0 : pas en panne
    assert facts["availability"]["pct"] == 99.5
    assert facts["interfaces"]["watched"] == 1 and facts["interfaces"]["enabled_down"] == 1

    # Base restaurée avec les droits d'avant : aucune lecture complémentaire.
    assert asyncio.run(read(client_with(False))) == {}
