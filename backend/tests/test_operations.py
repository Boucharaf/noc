"""Maintenances et ordres de travail lus dans les outils (iTop, Zabbix)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from collector.operations import active_maintenance_keys, link_operations  # noqa: E402


def _node(node_id, name, sources):
    return SimpleNamespace(id=node_id, name=name, hostname=name, sources=sources)


def test_link_by_reference_then_by_name():
    merged = [
        _node("zabbix:10", "LAB-BOBO-RT01", {"zabbix": "10"}),
        _node("netxms:5", "MANGA-DREP-CPEK01", {"netxms": "5", "itop": "77"}),
    ]
    change = {"tool": "itop", "cis": [{"ref": "77", "name": "autre"}, {"ref": None, "name": "lab-bobo-rt01"}]}
    zabbix = {"tool": "zabbix", "cis": [{"ref": "10", "name": "x"}, {"ref": "999", "name": "inconnu"}]}
    link_operations(merged, [change, zabbix])
    assert change["node_keys"] == ["netxms:5", "zabbix:10"]
    assert zabbix["node_keys"] == ["zabbix:10"]


def test_active_window_excludes_closed_and_future_changes():
    now = datetime.now(timezone.utc)
    iso = lambda delta: (now + delta).isoformat()  # noqa: E731
    windows = [
        {"status": "implemented", "start": iso(timedelta(hours=-1)), "end": iso(timedelta(hours=1)), "node_keys": ["a"]},
        {"status": "closed", "start": iso(timedelta(hours=-1)), "end": iso(timedelta(hours=1)), "node_keys": ["b"]},
        {"status": "approved", "start": iso(timedelta(hours=2)), "end": iso(timedelta(hours=3)), "node_keys": ["c"]},
        {"status": "rejected", "start": iso(timedelta(hours=-1)), "end": None, "node_keys": ["d"]},
        {"status": None, "start": iso(timedelta(days=-1)), "end": None, "node_keys": ["e"]},
    ]
    assert active_maintenance_keys(windows, now) == {"a", "e"}


def test_itop_changes_and_work_orders_parsing():
    """Changements et ordres de travail au format de l'API REST iTop 3.x."""
    import asyncio

    from integrations.itop import ITopClient

    client = ITopClient("https://itop.example/webservices/rest.php", "u", "p",
                        timezone_name="Africa/Ouagadougou")
    responses = {
        "Change": {"code": 0, "objects": {
            "NormalChange::12": {"key": "12", "fields": {
                "ref": "C-000012", "title": "Remplacement onduleur", "status": "approved",
                "finalclass": "NormalChange", "start_date": "2026-10-27 08:00:00",
                "end_date": "2026-10-27 12:00:00", "outage": "yes",
                "org_id_friendlyname": "ANPTIC", "agent_id_friendlyname": "A. Ouédraogo",
                "team_id_friendlyname": "Énergie",
                "functionalcis_list": [{"functionalci_id": "77", "functionalci_name": "BOBO-RT01"}],
            }},
            "RoutineChange::13": {"key": "13", "fields": {
                "ref": "C-000013", "title": "Refusé", "status": "rejected",
                "start_date": "2026-10-28 08:00:00", "end_date": "", "functionalcis_list": [],
            }},
        }},
        "WorkOrder": {"code": 0, "objects": {
            "WorkOrder::3": {"key": "3", "fields": {
                "name": "Déplacement site Bobo", "status": "open", "ticket_id": "40",
                "ticket_id_friendlyname": "I-000040", "team_id_friendlyname": "Terrain Ouest",
                "agent_id_friendlyname": "", "start_date": "2026-10-27 09:00:00",
                "end_date": "", "description": "Vérifier l'onduleur",
            }},
        }},
        "Ticket": {"code": 0, "objects": {
            "Incident::40": {"key": "40", "fields": {
                "ref": "I-000040", "title": "Panne sur 'BOBO-RT01'", "finalclass": "Incident",
                "functionalcis_list": [],
            }},
        }},
    }

    async def fake_get_all(_operation, payload):
        return responses[payload["class"]]

    client._get_all = fake_get_all
    windows = asyncio.run(client.fetch_maintenance())
    assert [w["ref"] for w in windows] == ["C-000012"]  # le refusé est écarté
    window = windows[0]
    assert window["start"] == "2026-10-27T08:00:00+00:00"  # Ouagadougou = UTC
    assert window["outage"] is True and window["agent"] == "A. Ouédraogo"
    assert window["cis"] == [{"ref": "77", "name": "BOBO-RT01"}]

    orders = asyncio.run(client.fetch_work_orders())
    assert len(orders) == 1
    order = orders[0]
    assert order["ticket"]["ref"] == "I-000040" and order["agent"] is None
    # CI du ticket : cité dans le titre faute de CI lié.
    assert order["cis"] == [{"ref": None, "name": "BOBO-RT01", "from_title": True}]
