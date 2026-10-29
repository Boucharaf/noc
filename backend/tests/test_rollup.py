from datetime import UTC, date, datetime

from collector import cycle, rollup
from collector.merge import MergedNode
from integrations.models import Alert


def _node(node_id, state, site=None, province=None, region=None):
    return MergedNode(
        id=node_id, name=node_id, hostname=node_id, ip=None, state=state, site=site,
        latitude=None, longitude=None, organisation=None, node_type=None,
        province=province, region=region, sources={"zabbix": node_id},
    )


def test_cycle_observation_feeds_total_site_province_and_region(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})
    at = datetime(2026, 10, 1, 8, tzinfo=UTC)
    nodes = [
        _node("a", "up", site="Ouaga DGI", province="Kadiogo", region="Centre"),
        _node("b", "down", site="Ouaga DGI", province="Kadiogo", region="Centre"),
        _node("c", "up"),  # sans localité : compté dans le seul total
    ]
    alert = Alert(
        tool="zabbix", ref="1", severity="critical", message="down", since=at, node_ref="b"
    )

    cycle._observe_rollup(nodes, [alert], at, set(), set())

    day = at.date()
    assert set(rollup._ACCUMULATOR) == {
        (day, None),
        (day, "Ouaga DGI"),
        (day, rollup.rollup_key("province", "Kadiogo")),
        (day, rollup.rollup_key("region", "Centre")),
    }
    assert rollup._ACCUMULATOR[(day, None)]["nodes"] == 3
    site = rollup._ACCUMULATOR[(day, "Ouaga DGI")]
    assert (site["nodes"], site["down"], site["alerts"], site["critical"]) == (2, 1, 1, 1)


def test_drain_averages_over_real_samples_and_clears_only_that_day(monkeypatch):
    day = date(2026, 10, 1)
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})
    # Deux cycles le 1er, dont un équipement en maintenance ; un cycle le 2.
    rollup.observe(day, None, [_node("a", "up"), _node("b", "down")], [])
    rollup.observe(day, None, [_node("a", "up"), _node("b", "maintenance")], [])
    rollup.observe(date(2026, 10, 2), None, [_node("a", "up")], [])

    (row,) = rollup._drain(day)

    assert row["samples"] == 2
    assert row["avg_nodes"] == 2.0
    # 2 « up » sur 3 observations mesurées : la maintenance sort du dénominateur.
    assert row["fleet_availability_pct"] == 66.67
    assert list(rollup._ACCUMULATOR) == [(date(2026, 10, 2), None)]
