import asyncio

from integrations import netxms
from integrations import itop, zabbix
from integrations.itop import ITopClient
from integrations.netxms import NetXMSClient
from integrations.zabbix import ZabbixClient


def test_netxms_fetch_nodes_reads_all_pages(monkeypatch):
    monkeypatch.setattr(netxms, "_PAGE_SIZE", 2)
    client = NetXMSClient("http://netxms")
    requests = []
    pages = {
        0: [{"objectId": 1, "objectName": "node-1"}, {"objectId": 2, "objectName": "node-2"}],
        2: [{"objectId": 3, "objectName": "node-3"}],
    }

    async def get_page(path, params=None):
        requests.append((path, params))
        return {"objects": pages.get(params["offset"], [])}

    monkeypatch.setattr(client, "_get", get_page)
    nodes = asyncio.run(client.fetch_nodes())

    assert [node.ref for node in nodes] == ["1", "2", "3"]
    assert [params["offset"] for _, params in requests] == [0, 2]
    assert all(params["limit"] == 2 for _, params in requests)


def test_zabbix_problem_get_uses_eventid_cursor(monkeypatch):
    monkeypatch.setattr(zabbix, "_PROBLEM_PAGE_SIZE", 2)
    client = ZabbixClient("http://zabbix")
    requests = []
    pages = [
        [{"eventid": "10"}, {"eventid": "20"}],
        [{"eventid": "21"}],
    ]

    async def call(method, params):
        requests.append((method, params))
        if method == "problem.get":
            return pages.pop(0)
        return []

    monkeypatch.setattr(client, "_call", call)
    alerts = asyncio.run(client.fetch_alerts())

    assert [alert.ref for alert in alerts] == ["10", "20", "21"]
    problem_requests = [params for method, params in requests if method == "problem.get"]
    assert [params.get("eventid_from") for params in problem_requests] == [None, "21"]
    assert all(params["sortorder"] == "ASC" for params in problem_requests)


def test_itop_cmdb_fetch_nodes_reads_all_pages(monkeypatch):
    monkeypatch.setattr(itop, "_PAGE_SIZE", 2)
    client = ITopClient("http://itop")
    requests = []

    async def call(operation, payload):
        assert operation == "core/get"
        requests.append(payload)
        if payload["class"] != "NetworkDevice":
            return {"objects": {}}
        if payload["page"] == 1:
            return {
                "objects": {
                    "NetworkDevice::1": {"key": 1, "fields": {"name": "router-1"}},
                    "NetworkDevice::2": {"key": 2, "fields": {"name": "router-2"}},
                }
            }
        return {
            "objects": {
                "NetworkDevice::3": {"key": 3, "fields": {"name": "router-3"}},
            }
        }

    monkeypatch.setattr(client, "_call", call)
    nodes = asyncio.run(client.fetch_nodes())

    assert [node.ref for node in nodes] == ["1", "2", "3"]
    assert [(request["class"], request["page"]) for request in requests[:2]] == [
        ("NetworkDevice", 1),
        ("NetworkDevice", 2),
    ]
    assert all(request["limit"] == 2 for request in requests)