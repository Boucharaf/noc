"""Identité stable : un équipement garde son identifiant quoi qu'il arrive à ses
outils, et deux équipements ne sont jamais confondus."""
import asyncio
from datetime import datetime, timedelta, timezone

from collector import identity
from collector.identity import Registry, resolve
from collector.merge import merge_nodes
from integrations.models import Node

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
TOOLS = {"zabbix", "centreon", "netxms"}


def node(key, name="rt01", ip="10.0.0.1"):
    tool, _, ref = key.partition(":")
    return Node(tool=tool, ref=ref, name=name, hostname=name, ip=ip, state="up")


class Fleet:
    """Cycles successifs sur un même registre."""

    def __init__(self):
        self.registry, self.now = Registry(), T0

    def cycle(self, *nodes, answered=TOOLS, known=TOOLS):
        self.now += timedelta(minutes=5)
        merged, report = merge_nodes(list(nodes))
        self.plan = resolve(merged, self.registry, set(answered), set(known), self.now)
        identity.rename(merged, report, self.plan.ids)
        ids = {f"{t}:{r}": n.id for n in merged for t, r in n.sources.items()}
        assert len({n.id for n in merged}) == len(merged), "identifiants uniques"
        return ids

    def events(self):
        return [e["event"] for e in self.plan.events]


def test_first_cycle_keeps_current_ids_and_second_is_silent():
    fleet = Fleet()
    nodes = [node("netxms:7"), node("zabbix:3", "sw", "10.0.0.2")]
    expected = {"netxms:7": "netxms:7", "zabbix:3": "zabbix:3"}
    assert fleet.cycle(*nodes) == expected
    assert fleet.cycle(*nodes) == expected
    assert not (fleet.plan.events or fleet.plan.bindings or fleet.plan.moved)


def test_id_survives_added_tool_that_sorts_first_then_its_removal():
    fleet = Fleet()
    fleet.cycle(node("netxms:7"))
    # Sans registre, la fusion dirait « centreon:5 ».
    assert set(fleet.cycle(node("netxms:7"), node("centreon:5")).values()) == {"netxms:7"}
    assert fleet.cycle(node("centreon:5"), known={"centreon"}) == {"centreon:5": "netxms:7"}


def test_rename_or_readdress_keeps_id():
    fleet = Fleet()
    fleet.cycle(node("netxms:7"))
    assert fleet.cycle(node("netxms:7", ip="10.9.9.9"))["netxms:7"] == "netxms:7"
    assert fleet.cycle(node("netxms:7", name="autre", ip="10.9.9.9"))["netxms:7"] == "netxms:7"
    assert fleet.events() == ["renamed"]


def test_recycled_reference_is_a_new_equipment():
    fleet = Fleet()
    fleet.cycle(node("zabbix:70"))
    assert fleet.cycle(node("zabbix:70", "autre", "10.9.9.9"))["zabbix:70"] == "zabbix:70~2"
    assert "zabbix:70" in fleet.plan.recycled
    assert fleet.cycle(node("zabbix:70", "autre", "10.9.9.9"))["zabbix:70"] == "zabbix:70~2"


def test_recreated_host_takes_its_history_back():
    fleet = Fleet()
    fleet.cycle(node("zabbix:70"))
    assert fleet.cycle(node("zabbix:99"))["zabbix:99"] == "zabbix:70"
    assert "rebound" in fleet.events()


def test_tool_replaced_by_another():
    fleet = Fleet()
    fleet.cycle(node("zabbix:70"))
    assert fleet.cycle(node("centreon:5"), known={"centreon"},
                       answered={"centreon"})["centreon:5"] == "zabbix:70"


def test_silent_tool_proves_no_disappearance():
    fleet = Fleet()
    fleet.cycle(node("zabbix:70"))
    assert fleet.cycle(node("centreon:5"), answered={"centreon"})["centreon:5"] == "centreon:5"


def test_ambiguous_return_is_never_guessed():
    fleet = Fleet()
    fleet.cycle(node("zabbix:70"))
    # Deux hôtes de mêmes nom et adresse : lequel serait l'ancien ?
    ids = fleet.cycle(node("zabbix:98"), node("zabbix:99"))
    assert ids == {"zabbix:98": "zabbix:98", "zabbix:99": "zabbix:99"}


def test_union_keeps_the_oldest_then_split_gives_back_each_id():
    fleet = Fleet()
    fleet.cycle(node("netxms:7", ip="10.0.0.1"))
    fleet.cycle(node("netxms:7", ip="10.0.0.1"), node("centreon:5", ip="10.0.0.8"))
    together = [node("netxms:7"), node("centreon:5")]
    assert set(fleet.cycle(*together).values()) == {"netxms:7"}
    assert fleet.plan.merged == {"centreon:5": "netxms:7"}
    assert set(fleet.cycle(*together).values()) == {"netxms:7"}
    assert fleet.events() == []
    apart = [node("netxms:7"), node("centreon:5", ip="10.0.0.8")]
    expected = {"netxms:7": "netxms:7", "centreon:5": "centreon:5"}
    assert fleet.cycle(*apart) == expected
    assert fleet.plan.merged == {"centreon:5": None}
    # Battement : jamais d'identifiant supplémentaire.
    for _ in range(3):
        fleet.cycle(*together)
        assert fleet.cycle(*apart) == expected
    assert set(fleet.registry.assets) == {"netxms:7", "centreon:5"}


def test_split_of_equipment_known_only_together():
    fleet = Fleet()
    fleet.cycle(node("netxms:7"), node("centreon:5"))   # identifiant : centreon:5
    ids = fleet.cycle(node("netxms:7", ip="10.0.0.8"), node("centreon:5"))
    assert ids == {"centreon:5": "centreon:5", "netxms:7": "netxms:7"}


def test_tool_outage_changes_nothing():
    fleet = Fleet()
    fleet.cycle(node("netxms:7"), node("centreon:5"))
    assert fleet.cycle(node("netxms:7"), answered={"netxms"})["netxms:7"] == "centreon:5"
    assert set(fleet.cycle(node("netxms:7"), node("centreon:5")).values()) == {"centreon:5"}


def test_report_ids_follow():
    merged, report = merge_nodes([node("netxms:7")])
    identity.rename(merged, report, {"netxms:7": "zabbix:1"})
    assert merged[0].id == report.single_source[0]["id"] == "zabbix:1"


def _apply(monkeypatch, error, cache):
    async def broken(*_args):
        raise error

    monkeypatch.setattr(identity, "_resolve_and_store", broken)
    monkeypatch.setattr(identity, "_cache", cache)
    merged, report = merge_nodes([node("netxms:7"), node("centreon:5")])
    status = {t: {"nodes": {"collected_at": "x", "stale": False}} for t in TOOLS}
    return asyncio.run(identity.apply(merged, report, status, T0)), merged[0].id


def test_database_down_uses_last_registry_or_refuses(monkeypatch):
    fleet = Fleet()
    fleet.cycle(node("netxms:7"))
    assert _apply(monkeypatch, OSError("base"), fleet.registry) == (True, "netxms:7")
    assert _apply(monkeypatch, OSError("base"), None) == (False, "centreon:5")


def test_schema_not_updated_keeps_previous_behaviour(monkeypatch):
    class UndefinedTable(Exception):
        pass

    assert _apply(monkeypatch, UndefinedTable(), None) == (True, "centreon:5")
