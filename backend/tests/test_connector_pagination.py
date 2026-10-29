"""Pagination des connecteurs.

Zabbix (curseur eventid) et iTop (core/get par tranches) sont couverts dans
test_data_quality.py, au plus près de leur protocole actuel.
"""
import asyncio

from integrations import netxms
from integrations.netxms import NetXMSClient


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

    node_requests = [params for _, params in requests if params["class"] == "Node"]
    assert [node.ref for node in nodes] == ["1", "2", "3"]
    assert [params["offset"] for params in node_requests] == [0, 2]
    assert all(params["limit"] == 2 for _, params in requests)
