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
    assert history.plan_alerts(open_rows, current, {"zabbix"}, T0)[2] == [(5, "critical")]
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


# -- Le cycle ne casse pas --------------------------------------------------------
def test_history_failure_never_breaks_the_cycle(monkeypatch):
    async def broken(*_args, **_kwargs):
        raise ConnectionError("base du NOC injoignable")

    monkeypatch.setattr(cycle.config, "HISTORY_ENABLED", True)
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
