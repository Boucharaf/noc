"""Journal historique : périodes d'état, vie des alertes, disponibilité sur la
durée, recalcul des bilans journaliers.

Les règles testées ici sont celles qui rendent l'historique digne de
confiance : ne jamais conclure à une fin parce qu'un outil s'est tu, ne
jamais compter un temps non observé comme disponible.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from collector import cycle, history
from collector.merge import MergedNode
from integrations.models import Alert, Node
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import HistAlert, HistState
from app.services import availability_service as av
from tests.fakes import FakeSource, MemoryStore

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
CYCLE = history.INTERVAL


def _node(node_id="netxms:7", state="up", links=(), site="Dédougou", tools=("netxms",)):
    return MergedNode(
        id=node_id, name="RT07", hostname="rt07", ip=None, state=state, site=site,
        latitude=None, longitude=None, organisation=None, node_type=None,
        region="Bankui", province="Mouhoun",
        sources={tool: node_id.split(":")[1] for tool in tools},
        details={"netxms": {"links": list(links)}} if links else {},
    )


def _open(subject_id, state, last_seen, tools="netxms", row_id=1):
    return {"id": row_id, "subject_id": subject_id, "state": state,
            "last_seen_at": last_seen, "tools": tools}


# -- Ce qui est observé -------------------------------------------------------
def test_subjects_cover_nodes_links_and_maintenance():
    link = {"ref": "70", "name": "Gi0/1", "state": "down", "speed_bps": 10**9}
    rows = history.subjects([_node(links=[link])], maintenance_keys={"netxms:7"})

    node, wan = rows["netxms:7"], rows["netxms:7|netxms:70"]
    assert (node["state"], node["measured_state"]) == ("maintenance", "up")
    assert (wan["subject_kind"], wan["state"], wan["measured_state"]) == (
        "link", "maintenance", "down",
    )
    assert wan["name"] == "RT07 — Gi0/1" and wan["tools"] == "netxms"


async def _identified(*_args):
    return True


# -- Planification des périodes -------------------------------------------------
def test_state_change_closes_and_opens_contiguously():
    now = T0 + CYCLE
    current = history.subjects([_node(state="down")], set())
    closes, inserts, touches = history.plan_states(
        [_open("netxms:7", "up", T0)], current, {"netxms"}, now
    )
    assert closes == [(1, now)]
    assert [row["state"] for row in inserts] == ["down"]
    assert touches == []


def test_same_state_is_only_extended():
    current = history.subjects([_node()], set())
    assert history.plan_states(
        [_open("netxms:7", "up", T0)], current, {"netxms"}, T0 + CYCLE
    ) == ([], [], [1])


def test_silent_tool_never_closes_a_period():
    # netxms n'a pas répondu et n'a pas de dernier succès : on ne conclut rien.
    assert history.plan_states(
        [_open("netxms:7", "up", T0)], {}, known=set(), now=T0 + CYCLE
    ) == ([], [], [])
    # netxms a répondu, l'équipement n'y est plus : la période se clôt.
    assert history.plan_states(
        [_open("netxms:7", "up", T0)], {}, known={"netxms"}, now=T0 + CYCLE
    )[0] == [(1, T0 + CYCLE)]


def test_observation_gap_is_never_counted_as_available():
    # Collecteur arrêté deux heures : la période s'arrête à la dernière
    # observation, une nouvelle commence au retour.
    now = T0 + timedelta(hours=2)
    current = history.subjects([_node()], set())
    closes, inserts, _ = history.plan_states(
        [_open("netxms:7", "up", T0)], current, {"netxms"}, now
    )
    assert closes == [(1, T0 + CYCLE)]
    assert [row["state"] for row in inserts] == ["up"]


def test_alerts_open_close_and_survive_a_silent_tool():
    alert = Alert(tool="zabbix", ref="9", severity="critical", message="Ping",
                  since=T0, node_ref="70")
    current = history.alert_rows([alert], [_node("zabbix:70", tools=("zabbix",))])
    assert current["zabbix:9"]["node_id"] == "zabbix:70"

    closes, inserts, touches = history.plan_alerts([], current, {"zabbix"}, T0)
    assert [row["alert_key"] for row in inserts] == ["zabbix:9"]

    open_rows = [{"id": 5, "alert_key": "zabbix:9", "tool": "zabbix"}]
    assert history.plan_alerts(open_rows, current, {"zabbix"}, T0)[2] == [(5, "critical", T0)]
    # Zabbix n'a pas répondu : l'alerte reste ouverte.
    assert history.plan_alerts(open_rows, {}, set(), T0) == ([], [], [])
    # Zabbix a répondu sans elle : close.
    assert history.plan_alerts(open_rows, {}, {"zabbix"}, T0)[0] == [(5, T0)]


# -- Recalcul d'une journée -------------------------------------------------------
def _period(state, start_h, end_h, kind="node", site="Dédougou"):
    return {
        "subject_kind": kind, "state": state, "site": site, "region": "Bankui",
        "province": "Mouhoun", "started_at": T0 + timedelta(hours=start_h),
        "ended_at": T0 + timedelta(hours=end_h), "last_seen_at": T0 + timedelta(hours=end_h),
    }


def test_daily_rows_are_time_weighted_and_skip_maintenance():
    states = [
        _period("up", 0, 18), _period("down", 18, 20), _period("maintenance", 20, 24),
    ]
    alerts = [{
        "kind": "technical", "severity": "critical", "site": "Dédougou",
        "region": "Bankui", "province": "Mouhoun",
        "opened_at": T0 + timedelta(hours=18), "closed_at": T0 + timedelta(hours=20),
        "last_seen_at": T0 + timedelta(hours=20),
    }]
    rows = {row["site"]: row for row in history.daily_rows(T0.date(), states, alerts, T0)}
    assert set(rows) == {None, "Dédougou", "@region:Bankui", "@province:Mouhoun"}
    total = rows[None]
    assert total["fleet_availability_pct"] == 90.0     # 18 h sur 20 h mesurées
    assert total["avg_nodes"] == 1.0
    assert total["avg_alerts"] == round(2 / 24, 2)
    assert total["avg_critical"] == total["avg_alerts"]


def test_daily_rows_do_not_count_unknown_time_as_unavailable():
    """AM-29 / INC-41 : « non observé » n'est pas « hors service »."""
    states = [_period("up", 0, 12), _period("unknown", 12, 24)]
    rows = {row["site"]: row for row in history.daily_rows(T0.date(), states, [], T0)}
    assert rows[None]["fleet_availability_pct"] == 100.0
    only_unknown = [_period("unknown", 0, 24, site="Pâ")]
    rows = {row["site"]: row for row in history.daily_rows(T0.date(), only_unknown, [], T0)}
    assert rows["Pâ"]["fleet_availability_pct"] is None


# -- Le cycle ne casse pas --------------------------------------------------------
def test_history_failure_never_breaks_the_cycle(monkeypatch):
    async def broken(*_args, **_kwargs):
        raise ConnectionError("base du NOC injoignable")

    monkeypatch.setattr(cycle.config, "HISTORY_ENABLED", True)
    monkeypatch.setattr(cycle.identity, "apply", _identified)
    monkeypatch.setattr(cycle.tool_health, "record", _identified)
    monkeypatch.setattr(history, "record", broken)
    store = MemoryStore()
    source = FakeSource("zabbix", nodes=[Node(tool="zabbix", ref="1", name="n1", state="up")])
    asyncio.run(cycle.run_cycle({"zabbix": source}, store, timeout_s=1))
    # L'erreur est journalisée ; l'instantané est publié quand même.
    assert store.snapshot_written
    assert [node.id for node in store.nodes] == ["zabbix:1"]


# -- Lecture : disponibilité sur la durée ------------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    HistState.__table__.create(engine)
    HistAlert.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _state(db, row_id, subject, state, start, end, kind="node", name="RT07"):
    db.add(HistState(
        id=row_id, subject_kind=kind, subject_id=subject, node_id="netxms:7", name=name,
        site="Dédougou", region="Bankui", tools="netxms", state=state,
        started_at=start, ended_at=end, last_seen_at=end or start,
    ))


def test_node_history_availability_downs_links_and_alerts(db, monkeypatch):
    now = T0 + timedelta(days=10)
    monkeypatch.setattr(av, "_now", lambda: now)
    day = timedelta(days=1)
    # Équipement : 9 jours en service, une panne de 12 h, puis 12 h non observées.
    _state(db, 1, "netxms:7", "up", T0, T0 + 4 * day)
    _state(db, 2, "netxms:7", "down", T0 + 4 * day, T0 + 4.5 * day)
    _state(db, 3, "netxms:7", "up", T0 + 4.5 * day, T0 + 9.5 * day)
    # Lien : toujours coupé.
    _state(db, 4, "netxms:7|netxms:70", "down", T0, None, kind="link", name="RT07 — Gi0/1")
    db.get(HistState, 4).last_seen_at = now
    db.add(HistAlert(
        id=1, alert_key="zabbix:9", tool="zabbix", kind="technical", node_id="netxms:7",
        severity="critical", message="Ping", opened_at=T0 + 4 * day,
        first_seen_at=T0 + 4 * day, last_seen_at=T0 + 4.5 * day,
        closed_at=T0 + 4 * day + timedelta(hours=3),
    ))
    db.commit()

    result = av.node_history(db, "netxms:7", days=10)
    node = result["node"]
    assert node["availability_pct"] == round(100 * 9 / 9.5, 3)
    assert node["unobserved_minutes"] == 12 * 60      # ni pour, ni contre
    assert (node["down_count"], node["mttr_minutes"]) == (1, 12 * 60)
    assert [s["state"] for s in node["segments"]] == ["up", "down", "up"]
    (link,) = result["links"]
    assert (link["name"], link["availability_pct"]) == ("RT07 — Gi0/1", 0.0)
    assert result["alerts"]["mttr_minutes"] == 180
    assert result["alerts"]["by_severity"] == {"critical": 1}

    ranking = av.ranking(db, "link", days=10)
    assert ranking["rows"][0]["subject_id"] == "netxms:7|netxms:70"


def test_missing_journal_is_reported_not_raised(monkeypatch):
    engine = create_engine("sqlite://")
    session = sessionmaker(bind=engine)()  # aucune table
    with pytest.raises(av.HistoryUnavailable):
        av.node_history(session, "netxms:7")
    from app.routes import history as routes

    assert routes.history_node("netxms:7", 30, session, None)["available"] is False


def test_ranking_average_is_time_weighted_and_skips_unsupervised(db, monkeypatch):
    """INC-01 / INC-42 : une seule disponibilité, pondérée par le temps
    supervisé ; un équipement jamais observé n'entre pas dans la moyenne."""
    now = T0 + timedelta(days=10)
    monkeypatch.setattr(av, "_now", lambda: now)
    day = timedelta(days=1)
    # A : 9 jours en service, 1 jour en panne → 90 % sur 10 j supervisés.
    _state(db, 11, "a", "up", T0, T0 + 9 * day)
    _state(db, 12, "a", "down", T0 + 9 * day, T0 + 10 * day)
    # B : 1 jour supervisé, en service, puis 9 jours inconnus.
    _state(db, 13, "b", "up", T0, T0 + day)
    _state(db, 14, "b", "unknown", T0 + day, T0 + 10 * day)
    # C : jamais observé.
    _state(db, 15, "c", "unknown", T0, T0 + 10 * day)
    db.commit()

    ranking = av.ranking(db, "node", days=10)

    # (9 + 1) jours en service ÷ (10 + 1) jours supervisés, et non (90+100)/2.
    assert ranking["average_pct"] == round(100 * 10 / 11, 3)
    assert ranking["subjects"] == 2
    assert ranking["basis"]["unsupervised"] == 1
    # A : une panne d'un jour, close ; MTBF = 10 j en service ÷ 1 panne.
    assert ranking["failures"] == 1
    assert ranking["mttr_minutes"] == 24 * 60
    assert ranking["mtbf_hours"] == 10 * 24
    b = next(row for row in ranking["rows"] if row["subject_id"] == "b")
    assert b["availability_pct"] == 100.0
    assert b["unsupervised_minutes"] == 9 * 24 * 60


def test_flapping_down_periods_count_as_one_failure_episode(db, monkeypatch):
    """INC-39 : un équipement qui oscille n'a qu'UNE panne, pas une par alerte."""
    now = T0 + timedelta(days=2)
    monkeypatch.setattr(av, "_now", lambda: now)
    minute = timedelta(minutes=1)
    hour = timedelta(hours=1)
    # 1 h en service, puis 3 coupures séparées de 5 min de reprise (< 3 cycles),
    # puis 10 h en service, puis une 2e panne franche de 30 min.
    rows = [("up", T0, T0 + hour)]
    t = T0 + hour
    for _ in range(3):
        rows.append(("down", t, t + 10 * minute))
        rows.append(("up", t + 10 * minute, t + 15 * minute))
        t += 15 * minute
    rows.append(("up", t, t + 10 * hour))
    t += 10 * hour
    rows.append(("down", t, t + 30 * minute))
    rows.append(("up", t + 30 * minute, now))
    for index, (state, start, end) in enumerate(rows, start=100):
        _state(db, index, "netxms:7", state, start, end)
    db.commit()

    node = av.node_history(db, "netxms:7", days=2)["node"]

    assert node["down_count"] == 2
    # 1er épisode : de la 1re coupure à la fin de la 3e (40 min) ; 2e : 30 min.
    assert node["mttr_minutes"] == 35.0



def test_flapping_lists_nodes_changing_state_at_least_five_times_an_hour(db, monkeypatch):
    """AM-08 / KPI-14 : 6 bascules en 1 h = instable ; 2 bascules, non."""
    now = T0 + timedelta(hours=5)
    monkeypatch.setattr(av, "_now", lambda: now)
    minute = timedelta(minutes=1)
    states = ["up", "down"] * 3
    for index, state in enumerate(states):
        start = now - timedelta(minutes=50) + index * 8 * minute
        _state(db, 300 + index, "netxms:7", state, start, start + 8 * minute)
    _state(db, 400, "zabbix:8", "up", now - 30 * minute, None)
    _state(db, 401, "zabbix:8", "down", now - 20 * minute, None)
    db.commit()

    result = av.flapping(db, hours=1)

    assert [row["changes"] for row in result["rows"]] == [6]
    assert result["rows"][0]["states"] == ["down", "up"]


# -- Acquittements ---------------------------------------------------------------
def _alert_row(**over):
    return {"id": 5, "alert_key": "zabbix:9", "tool": "zabbix", "severity": "high",
            "opened_at": T0, "last_seen_at": T0 + CYCLE, "acknowledged": False,
            "acknowledged_at": None, "acknowledged_by": None, "ack_source": None, **over}


def _seen(ack=True, at=None, severity="high", by="Awa"):
    return {"zabbix:9": {"severity": severity, "is_ack": ack, "tool_ack_at": at, "actor": by}}


NOW = T0 + 2 * CYCLE


@pytest.mark.parametrize("row, at, expected", [
    ({}, T0 + timedelta(minutes=6), (T0 + timedelta(minutes=6), "tool")),
    ({}, None, (NOW, "observed")),
    ({}, T0 - timedelta(days=1), (NOW, "observed")),        # date antérieure à l'alerte
    ({"acknowledged": None}, None, (None, "undated")),      # ligne d'avant la mise à jour
    ({"last_seen_at": T0 - timedelta(hours=3)}, None, (None, "undated")),  # collecteur arrêté
])
def test_acknowledgement_date_is_never_invented(row, at, expected):
    updates, events = history.plan_alert_changes([_alert_row(**row)], _seen(at=at), NOW)
    assert (updates[0]["acknowledged_at"], updates[0]["ack_source"]) == expected
    assert [(e["event"], e["actor"]) for e in events] == [("acknowledged", "Awa")]


def test_first_acknowledgement_survives_a_second_one():
    first = {"acknowledged_at": T0, "acknowledged_by": "Awa", "ack_source": "tool"}
    updates, events = history.plan_alert_changes(
        [_alert_row(**first)], _seen(at=NOW, by="Issa"), NOW
    )
    assert (updates[0]["acknowledged_at"], updates[0]["acknowledged_by"]) == (T0, "Awa")
    assert events[0]["at"] == NOW and events[0]["actor"] == "Issa"


def test_unacknowledge_and_severity_are_journaled_once():
    row = _alert_row(acknowledged=True, acknowledged_at=T0, ack_source="tool")
    updates, events = history.plan_alert_changes(
        [row], _seen(ack=False, severity="critical"), NOW
    )
    assert [e["event"] for e in events] == ["severity", "unacknowledged"]
    assert (events[0]["from_value"], events[0]["to_value"]) == ("high", "critical")
    assert updates[0]["acknowledged"] is False and updates[0]["acknowledged_at"] == T0
    assert history.plan_alert_changes([_alert_row()], _seen(ack=False), NOW) == ([], [])
    assert history.plan_alert_changes([_alert_row()], {}, NOW) == ([], [])


def test_mtta_counts_closed_alerts_and_skips_undated():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    HistAlert.__table__.create(engine)
    now = datetime.now(timezone.utc)
    common = dict(tool="zabbix", kind="technical", severity="high", opened_at=now,
                  first_seen_at=now, last_seen_at=now, acknowledged=True)
    with sessionmaker(engine)() as db:
        for i, (node, delay, closed) in enumerate(
            [("a", 10, now), ("b", 30, None), ("a", None, None)], 1
        ):
            opened = now - timedelta(hours=2)
            db.add(HistAlert(**{
                **common, "id": i, "alert_key": f"z:{i}", "node_id": node,
                "opened_at": opened, "closed_at": closed,
                "acknowledged_at": opened + timedelta(minutes=delay) if delay else None,
            }))
        db.commit()
        assert av.alert_response(db) == {"days": 30, "count": 2, "mtta_minutes": 20.0}
        assert av.alert_response(db, node_ids={"a"})["mtta_minutes"] == 10.0
