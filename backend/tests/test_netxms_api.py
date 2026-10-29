"""Connecteur NetXMS par l'API Web — le chemin de production.

La forme exacte des réponses de l'instance de l'agence n'est pas connue : ces
tests fixent ce que le connecteur doit accepter (codes numériques ou noms,
dates en secondes, millisecondes ou ISO) et ce qu'il doit en tirer, en
particulier la localité, que l'API ne donne pas comme la base.
"""
import asyncio

from integrations.localities import locate, region_at
from integrations.netxms import NetXMSClient


def _client(responses: dict, site_attribute: str = "") -> NetXMSClient:
    client = NetXMSClient("https://netxms.example", site_attribute=site_attribute)
    calls = []

    async def get(path, params=None):
        calls.append(path)
        key = f"{path}?{params['class']}" if params and "class" in params else path
        return responses[key]

    client._get = get
    client.calls = calls
    return client


def _run(coro_factory, client):
    async def run():
        try:
            return await coro_factory()
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_city_gives_province_and_region():
    assert locate("Dédougou") == ("MOUHOUN", "BANKUI")
    assert locate("  ouagadougou ") == ("KADIOGO", "KADIOGO")


def test_coordinates_give_region_when_city_is_unknown():
    # Bobo-Dioulasso, sans ville renseignée.
    assert locate(None, 11.18, -4.29) == (None, "GUIRIKO")
    assert region_at(48.85, 2.35) is None  # hors du pays : rien de deviné
    assert locate("Ville inconnue") == (None, None)


def test_nodes_accept_names_and_carry_their_locality():
    client = _client({
        "/objects?Node": {"objects": [
            {
                "objectId": 10, "objectClass": "Node", "objectName": "DDG-RT01",
                "status": "MAJOR", "primaryIP": "10.0.0.1", "primaryName": "10.0.0.1",
                "postalAddress": {"city": "DEDOUGOU"},
                "geolocation": {"latitude": 12.46, "longitude": -3.46},
                "parents": [5],
            },
            {
                "objectId": 11, "objectClass": 2, "objectName": "BOBO-SW01",
                "status": 0, "primaryIP": "0.0.0.0",
                "geolocation": {"latitude": 11.18, "longitude": -4.29},
            },
            {"objectId": 12, "objectClass": "Subnet", "objectName": "10.0.0.0/24"},
        ], "totalCount": 3},
        "/objects?Container": {"objects": [{"objectId": 5, "objectName": "Core"}]},
        "/objects?Interface": {"objects": []},
    })
    nodes = _run(client.fetch_nodes, client)

    assert [node.ref for node in nodes] == ["10", "11"]
    ddg, bobo = nodes
    assert ddg.state == "down"
    assert ddg.hostname == "DDG-RT01"  # l'IP ne fait pas un nom technique
    assert (ddg.site, ddg.province, ddg.region) == ("Dedougou", "Mouhoun", "Bankui")
    assert ddg.groups == ("Core",)
    assert bobo.ip is None  # 0.0.0.0 ne doit pas fusionner les nœuds sans IP
    assert (bobo.site, bobo.province, bobo.region) == (None, None, "Guiriko")


def test_site_attribute_takes_precedence_over_city():
    client = _client({
        "/objects?Node": {"objects": [{
            "objectId": 1, "objectClass": "Node", "objectName": "n", "status": 0,
            "postalAddress": {"city": "DEDOUGOU"},
            "customAttributes": {"site": {"value": "Gouvernorat de Dédougou"}},
        }]},
        "/objects?Container": {"objects": []},
        "/objects?Interface": {"objects": []},
    }, site_attribute="site")
    [node] = _run(client.fetch_nodes, client)

    assert node.site == "Gouvernorat de Dédougou"
    assert node.region == "Bankui"


def test_interface_alarm_is_attached_to_its_node_once():
    client = _client({
        "/alarms": {"alarms": [
            {"id": 1, "state": "OUTSTANDING", "currentSeverity": "CRITICAL",
             "sourceObjectId": 300, "message": "GigabitEthernet2 down",
             "creationTime": 1786000000000},
            {"id": 2, "state": 1, "currentSeverity": 2, "sourceObjectId": 10,
             "sourceObjectName": "DDG-RT01", "message": "CPU",
             "creationTime": "2026-08-07T10:00:00Z", "ackTime": 1786000600},
            {"id": 3, "state": 3, "currentSeverity": 4, "sourceObjectId": 10,
             "message": "terminée", "creationTime": 1786000000},
        ]},
        "/objects/300": {"objectId": 300, "objectClass": "Interface", "parents": [10]},
        "/objects/10": {"objectId": 10, "objectClass": "Node", "objectName": "DDG-RT01"},
    })
    async def two_cycles():
        first = await client.fetch_alerts()
        client.calls.clear()
        await client.fetch_alerts()
        return first

    alerts = _run(two_cycles, client)

    assert [alert.ref for alert in alerts] == ["1", "2"]  # la terminée est écartée
    interface, cpu = alerts
    assert interface.node_ref == "10" and interface.severity == "critical"
    assert interface.since.year == 2026  # millisecondes reconnues
    assert cpu.acknowledged and cpu.acknowledged_at is not None
    assert cpu.node_name == "DDG-RT01"
    # Au cycle suivant, l'interface est connue : pas de nouvelle requête.
    assert client.calls == ["/alarms"]


def test_node_facts_inventory_availability_and_interfaces():
    client = _client({
        "/objects?Node": {"objects": [{
            "objectId": 7, "objectClass": "Node", "objectName": "RT07", "status": 3,
            "vendor": "Cisco", "productName": "ISR4331", "serialNumber": "FDO123",
            "bootTime": 1786000000, "downSince": "2026-08-07T08:00:00Z",
            "customAttributes": {
                "perAvailability": "95.897665", "mttr": "0.886466", "mtbf": "20.72",
                "NumFailures": "453", "TotalDowntime": "1445648", "TimeStamp": "1786101798",
            },
        }]},
        "/objects?Container": {"objects": []},
        "/objects?Interface": {"objects": [
            # Lien surveillé actif (1 Gb/s), lien surveillé coupé, port libre
            # activé mais inactif, port désactivé.
            {"objectId": 70, "parents": [7], "adminState": 1, "operState": 1,
             "expectedState": 0, "speed": 1_000_000_000},
            {"objectId": 71, "parents": [7], "adminState": "UP", "operState": "DOWN",
             "expectedState": "UP", "speed": 100_000_000},
            {"objectId": 72, "parentNodeId": 7, "adminState": 1, "operState": 2,
             "expectedState": 2},
            {"objectId": 73, "parents": [7], "adminState": 2, "operState": 2},
        ]},
    })
    [node] = _run(client.fetch_nodes, client)
    facts = node.details

    assert facts["inventory"] == {"vendor": "Cisco", "model": "ISR4331", "serial": "FDO123"}
    assert facts["boot_time"].year == 2026 and facts["down_since"].hour == 8
    assert facts["availability"]["pct"] == 95.898
    assert facts["availability"]["failures"] == 453
    assert facts["interfaces"] == {
        "total": 4, "enabled": 3, "enabled_up": 1, "enabled_down": 2,
        "watched": 2, "watched_down": 1, "capacity_bps": 1_000_000_000,
    }


def test_interfaces_can_be_turned_off():
    client = NetXMSClient("https://netxms.example", collect_interfaces=False)
    asked = []

    async def get(path, params=None):
        asked.append(params["class"])
        return {"objects": []}

    client._get = get
    _run(client.fetch_nodes, client)
    assert "Interface" not in asked
