"""Pannes NetXMS (downtime_log) : source maître de la disponibilité.

NetXMS date chaque panne à la seconde ; le NOC, lui, ne la voit qu'à un cycle
de collecte près. Pour un équipement NetXMS, la panne est celle du journal
NetXMS ; maintenance et temps non supervisé restent ceux du NOC.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from collector import downtime, history
from collector.merge import MergedNode
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import HistAlert, HistDowntime, HistSourceSync, HistState
from app.services import availability_service as av

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)
M = timedelta(minutes=1)


def _row(state, start, end, tools="netxms", subject="netxms:7", kind="node"):
    return {
        "subject_kind": kind, "subject_id": subject, "node_id": "netxms:7",
        "name": "RT07", "site": "Dédougou", "province": None, "region": "Bankui",
        "tools": tools, "state": state, "measured_state": state,
        "started_at": start, "ended_at": end, "last_seen_at": end or start,
    }


def _closed_end(row):
    return row["ended_at"] or row["last_seen_at"]


def _shape(periods):
    return [(p["state"], p["started_at"], p["ended_at"]) for p in periods]


# -- La règle -----------------------------------------------------------------------
def test_source_dates_the_outage_to_the_second():
    """Le NOC a vu la panne de 10:05 à 10:20 (cycle de 5 min) ; NetXMS
    l'enregistre de 10:02:30 à 10:17:10. C'est NetXMS qui fait foi."""
    now = T0 + 24 * H
    rows = [
        _row("up", T0, T0 + 10 * H + 5 * M),
        _row("down", T0 + 10 * H + 5 * M, T0 + 10 * H + 20 * M),
        _row("up", T0 + 10 * H + 20 * M, T0 + 20 * H),
    ]
    down_start = T0 + 10 * H + timedelta(minutes=2, seconds=30)
    down_end = T0 + 10 * H + timedelta(minutes=17, seconds=10)

    periods, report = downtime.overlay(rows, [(down_start, down_end)], now, _closed_end)

    assert _shape(periods) == [
        ("up", T0, down_start),
        ("down", down_start, down_end),
        ("up", down_end, T0 + 20 * H),
    ]
    # Rapprochement : 2 min 30 de panne que le NOC ne voyait pas encore,
    # 2 min 50 que le NOC comptait en trop.
    assert report["source_only_down_s"] == 150
    assert report["noc_only_down_s"] == 170


def test_short_outage_missed_by_polling_is_counted():
    now = T0 + 24 * H
    rows = [_row("up", T0, T0 + 20 * H)]
    blip = (T0 + 3 * H, T0 + 3 * H + 2 * M)   # plus court qu'un cycle

    periods, report = downtime.overlay(rows, [blip], now, _closed_end)

    assert [p["state"] for p in periods] == ["up", "down", "up"]
    assert report["source_only_down_s"] == 120


def test_maintenance_and_unknown_stay_with_the_noc():
    """Une panne NetXMS pendant une maintenance planifiée n'est pas une panne ;
    le temps non supervisé n'est jamais transformé en temps « en service »."""
    now = T0 + 24 * H
    rows = [
        _row("up", T0, T0 + 2 * H),
        _row("maintenance", T0 + 2 * H, T0 + 4 * H),
        _row("unknown", T0 + 4 * H, T0 + 6 * H),
    ]
    periods, _ = downtime.overlay(rows, [(T0 + 1 * H, T0 + 5 * H)], now, _closed_end)

    assert _shape(periods) == [
        ("up", T0, T0 + 1 * H),
        ("down", T0 + 1 * H, T0 + 2 * H),
        ("maintenance", T0 + 2 * H, T0 + 4 * H),
        ("unknown", T0 + 4 * H, T0 + 6 * H),
    ]


def test_noc_observation_gap_is_filled_by_the_source_but_never_extended():
    """Collecteur arrêté 4 h : NetXMS supervisait, son journal dit ce qui
    s'est passé. Avant la première et après la dernière observation du NOC,
    rien n'est inventé."""
    now = T0 + 24 * H
    rows = [_row("up", T0 + 2 * H, T0 + 6 * H), _row("up", T0 + 10 * H, T0 + 12 * H)]
    downs = [(T0, T0 + 1 * H), (T0 + 7 * H, T0 + 8 * H), (T0 + 13 * H, T0 + 14 * H)]

    periods, report = downtime.overlay(rows, downs, now, _closed_end)

    assert _shape(periods) == [
        ("up", T0 + 2 * H, T0 + 7 * H),
        ("down", T0 + 7 * H, T0 + 8 * H),
        ("up", T0 + 8 * H, T0 + 12 * H),
    ]
    assert report["filled_s"] == 4 * 3600


def test_ongoing_outage_and_open_period_stay_open():
    now = T0 + 10 * H
    rows = [_row("up", T0, None)]
    rows[0]["last_seen_at"] = now
    periods, _ = downtime.overlay(rows, [(T0 + 8 * H, None)], now, lambda r: r["ended_at"] or now)

    assert [p["state"] for p in periods] == ["up", "down"]
    assert periods[-1]["ended_at"] is None and periods[-1]["last_seen_at"] == now


def test_other_tools_and_links_are_untouched():
    rows = [_row("down", T0, T0 + H, tools="zabbix", subject="zabbix:1"),
            _row("down", T0, T0 + H, subject="netxms:7|netxms:70", kind="link")]
    out = downtime.apply_to_states(rows, [], T0 + 2 * H, _closed_end)
    assert sorted(p["state"] for p in out) == ["down", "down"]


def test_overlapping_tags_are_merged():
    spans = downtime.merge_intervals(
        [(T0, T0 + 2 * H), (T0 + H, T0 + 3 * H), (T0 + 5 * H, None)], T0 + 6 * H
    )
    assert spans == [(T0, T0 + 3 * H), (T0 + 5 * H, T0 + 6 * H)]


def test_daily_rows_use_the_source_outage():
    """Bilan journalier : 1 h de panne NetXMS que le NOC n'a pas vue."""
    day = T0.date()
    rows = [_row("up", T0, T0 + 24 * H)]
    corrected = downtime.apply_to_states(
        rows, [{"node_id": "netxms:7", "started_at": T0 + 6 * H, "ended_at": T0 + 7 * H}],
        T0 + 30 * H, history.effective_end,
    )
    (total,) = [r for r in history.daily_rows(day, corrected, [], T0 + 30 * H)
                if r["site"] is None]
    assert total["fleet_availability_pct"] == round(100 * 23 / 24, 2)


# -- Lecture de downtime_log ----------------------------------------------------------
def _client(responses):
    from integrations.netxms_db import NetXMSDatabaseClient

    client = NetXMSDatabaseClient("postgresql://x/netxms")
    queries = []

    async def query(sql):
        queries.append(sql)
        return responses.pop(0)

    client._query = query
    return client, queries


def test_downtime_log_is_read_with_epoch_columns():
    # Colonnes de NetXMS 5 (schéma 50.45, dump de l'agence du 07/08/2026).
    columns = [("object_id", "integer"), ("start_time", "integer"),
               ("end_time", "integer"), ("downtime_tag", "character varying")]
    start = int((T0 + H).timestamp())
    client, queries = _client([columns, [(7, start, start + 600, "node"), (8, start, 0, None)]])

    records = asyncio.run(client.fetch_downtimes(T0))

    assert f"end_time >= {int(T0.timestamp())}" in queries[1]
    assert "downtime_tag FROM downtime_log" in queries[1]
    assert records[0] == {"object_id": 7, "start": T0 + H, "end": T0 + H + 10 * M,
                          "tag": "node"}
    assert records[1]["end"] is None          # 0 = panne en cours


def test_unexpected_downtime_log_schema_names_the_columns_found():
    from integrations.base import ToolUnavailable

    client, _ = _client([[("object_id", "integer"), ("since", "integer")]])
    expected = "downtime_tag ou tag.*colonnes visibles : object_id, since"
    with pytest.raises(ToolUnavailable, match=expected):
        asyncio.run(client.fetch_downtimes(T0))


def test_downtimes_are_attached_to_the_merged_node(monkeypatch):
    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_TAGS", frozenset())
    node = MergedNode(id="zabbix:3", name="RT07", hostname="rt07", ip=None, state="up",
                      site=None, latitude=None, longitude=None, organisation=None,
                      node_type=None, sources={"zabbix": "3", "netxms": "7"})
    rows = downtime.rows_to_store(
        [{"object_id": 7, "start": T0, "end": None, "tag": ""},
         {"object_id": 9, "start": T0, "end": T0 + H, "tag": ""}],
        [node],
    )
    assert [(r["node_id"], r["name"]) for r in rows] == [("zabbix:3", "RT07"), ("netxms:9", None)]


# -- Backend : disponibilité calculée sur la source -------------------------------------
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (HistState, HistAlert, HistDowntime, HistSourceSync):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, now, synced_at):
    db.add(HistState(id=1, subject_kind="node", subject_id="netxms:7", node_id="netxms:7",
                     name="RT07", site="Dédougou", region="Bankui", tools="netxms",
                     state="up", started_at=T0, ended_at=T0 + 10 * H,
                     last_seen_at=T0 + 10 * H))
    db.add(HistDowntime(id=1, source="netxms", object_ref="7", node_id="netxms:7",
                        tag="", started_at=T0 + 2 * H, ended_at=T0 + 3 * H))
    db.add(HistSourceSync(source="netxms", synced_at=synced_at, rows_read=1))
    db.commit()


def test_ranking_uses_the_source_when_synchronised(db, monkeypatch):
    now = T0 + 10 * H
    monkeypatch.setattr(av, "_now", lambda: now)
    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_ENABLED", True)
    _seed(db, now, synced_at=now - H)

    ranking = av.ranking(db, "node", days=1)

    (row,) = ranking["rows"]
    assert row["source"] == "netxms_downtime_log"
    assert row["availability_pct"] == 90.0
    assert ranking["failures"] == 1 and ranking["mttr_minutes"] == 60
    assert ranking["basis"]["sources"] == {"netxms_downtime_log": 1}
    assert ranking["basis"]["reconciliation"]["source_only_down_minutes"] == 60
    node = av.node_history(db, "netxms:7", days=1)["node"]
    assert node["source"] == "netxms_downtime_log" and node["availability_pct"] == 90.0


def test_stale_or_disabled_source_falls_back_to_noc_observation(db, monkeypatch):
    now = T0 + 10 * H
    monkeypatch.setattr(av, "_now", lambda: now)
    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_ENABLED", True)
    _seed(db, now, synced_at=now - 7 * H)      # plus de 6 h sans synchronisation

    (row,) = av.ranking(db, "node", days=1)["rows"]
    assert (row["source"], row["availability_pct"]) == ("noc_observation", 100.0)

    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_ENABLED", False)
    db.get(HistSourceSync, "netxms").synced_at = now
    db.commit()
    (row,) = av.ranking(db, "node", days=1)["rows"]
    assert row["source"] == "noc_observation"


# -- Historique de la source avant (ou sans) observation du NOC --------------------
D = timedelta(days=1)


def test_history_before_first_noc_observation_is_rebuilt_from_the_source():
    """Supervisé par NetXMS depuis J0, base connue jusqu'à J10 (dump), NOC
    présent seulement à partir de J20 : J0→J10 reconstitué depuis la source,
    J10→J20 non observé (personne ne sait), puis le NOC."""
    now = T0 + 21 * D
    rows = [_row("up", T0 + 20 * D, T0 + 21 * D)]
    downs = [(T0 + 2 * D, T0 + 3 * D)]

    periods, report = downtime.overlay(rows, downs, now, _closed_end,
                                       supervised=(T0, T0 + 10 * D))

    assert _shape(periods) == [
        ("up", T0, T0 + 2 * D),
        ("down", T0 + 2 * D, T0 + 3 * D),
        ("up", T0 + 3 * D, T0 + 10 * D),
        ("up", T0 + 20 * D, T0 + 21 * D),
    ]
    assert report["history_s"] == 10 * 86400
    assert downtime.reconciliation_minutes(report)["history_minutes"] == 10 * 1440


def test_never_observed_node_and_gaps_beyond_the_horizon():
    base = {"subject_kind": "node", "subject_id": "netxms:9", "node_id": "netxms:9",
            "name": "RT09", "tools": "netxms"}
    periods, _ = downtime.overlay([], [(T0 + D, None)], T0 + 30 * D, _closed_end,
                                  supervised=(T0, T0 + 5 * D), base=base)
    # Panne encore ouverte au moment du dump : en panne jusqu'à l'horizon, pas au-delà.
    assert _shape(periods) == [("up", T0, T0 + D), ("down", T0 + D, T0 + 5 * D)]
    assert periods[0]["name"] == "RT09"

    # Trou d'observation du NOC APRÈS l'horizon : non comblé.
    rows = [_row("up", T0 + 6 * D, T0 + 7 * D), _row("up", T0 + 8 * D, T0 + 9 * D)]
    periods, report = downtime.overlay(rows, [], T0 + 10 * D, _closed_end,
                                       supervised=(T0 + 6 * D, T0 + 5 * D))
    assert report["filled_s"] == 0
    assert [p["started_at"] for p in periods] == [T0 + 6 * D, T0 + 8 * D]


def test_daily_rebuild_covers_days_before_the_noc_journal():
    objects = [{"source": "netxms", "object_ref": "9", "node_id": "netxms:9", "name": "RT09",
                "site": "Pâ", "province": None, "region": "Hauts-Bassins", "tools": "netxms",
                "supervised_since": T0, "managed": True},
               {"source": "netxms", "object_ref": "10", "node_id": "netxms:10", "name": "X",
                "tools": "netxms", "supervised_since": T0, "managed": False}]
    downs = [{"source": "netxms", "node_id": "netxms:9",
              "started_at": T0 + 6 * H, "ended_at": T0 + 12 * H}]
    states = downtime.apply_to_states([], downs, T0 + 40 * D, history.effective_end,
                                      {"netxms"}, objects, {"netxms": T0 + 30 * D})
    (total,) = [r for r in history.daily_rows(T0.date(), states, [], T0 + 40 * D)
                if r["site"] is None]
    # Un seul équipement (le non géré n'existe pas pour le calcul), 6 h de panne.
    assert total["fleet_availability_pct"] == 75.0
    assert total["avg_nodes"] == 1.0


def test_supervision_is_read_from_netxms():
    from integrations.netxms_db import NetXMSDatabaseClient

    client = NetXMSDatabaseClient("postgresql://x/netxms")
    created = int(T0.timestamp())

    async def query(sql):
        if "creation_time" in sql:
            return [(7, created, 0), (8, created, 6)]
        return [(created + 86400,)]

    client._query = query
    result = asyncio.run(client.fetch_supervision())
    assert result["horizon"] == T0 + D
    assert result["complete_since"] == T0 + D
    assert [(o["object_id"], o["since"], o["managed"]) for o in result["objects"]] == [
        (7, T0, True), (8, T0, False)]   # statut 6 : non géré


def test_ranking_includes_nodes_only_known_by_the_source(db, monkeypatch):
    from app.models import HistSourceObject

    HistSourceObject.__table__.create(db.get_bind())
    now = T0 + 40 * D
    monkeypatch.setattr(av, "_now", lambda: now)
    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_ENABLED", True)
    # Base NetXMS figée à J30 ; le NOC n'a jamais observé RT09.
    db.add(HistSourceSync(source="netxms", synced_at=now - H, rows_read=1,
                          horizon_at=T0 + 30 * D))
    db.add(HistSourceObject(source="netxms", object_ref="9", node_id="netxms:9", name="RT09",
                            region="Hauts-Bassins", tools="netxms", supervised_since=T0,
                            managed=True))
    db.add(HistDowntime(id=1, source="netxms", object_ref="9", node_id="netxms:9", tag="",
                        started_at=T0 + 29 * D, ended_at=T0 + 29 * D + 12 * H))
    db.commit()

    ranking = av.ranking(db, "node", days=40)
    (row,) = ranking["rows"]
    assert (row["subject_id"], row["source"]) == ("netxms:9", "netxms_downtime_log")
    # 30 jours connus, dont 12 h de panne ; les 10 jours après l'horizon ne
    # comptent ni pour ni contre.
    assert row["availability_pct"] == round(100 * (30 * 24 - 12) / (30 * 24), 3)
    assert row["down_count"] == 1
    assert ranking["basis"]["reconciliation"]["history_minutes"] == 30 * 1440
    # Filtre de périmètre appliqué aux équipements connus de la seule source.
    assert av.ranking(db, "node", days=40, region="Centre")["rows"] == []


def test_outage_open_before_the_period_is_not_a_new_failure():
    """Panne ouverte depuis J2 selon NetXMS, vue par le NOC à partir de J20 :
    sur la période [J10, J30], ce n'est PAS une panne nouvelle ; close à J25,
    sa durée part de J2."""
    now = T0 + 30 * D
    rows = [_row("down", T0 + 20 * D, T0 + 25 * D), _row("up", T0 + 25 * D, T0 + 30 * D)]
    periods, _ = downtime.overlay(rows, [(T0 + 2 * D, T0 + 25 * D)], now, _closed_end)
    assert periods[0]["down_since"] == T0 + 2 * D

    summary = av.summarise(periods, T0 + 10 * D, now, now)
    assert summary["down_count"] == 0
    assert summary["mttr_minutes"] is None          # pas une panne de la période
    long_view = av.summarise(periods, T0, now, now)
    assert long_view["down_count"] == 1
    assert long_view["mttr_minutes"] == 23 * 1440  # de J2 à J25


def test_nothing_is_rebuilt_before_the_source_journal_is_complete():
    """NetXMS efface les pannes terminées au-delà de 90 jours : avant la plus
    ancienne panne terminée encore présente, le journal est incomplet et
    rien n'est reconstitué (sinon : disponibilité inventée, sans ses pannes)."""
    objects = [{"source": "netxms", "node_id": "netxms:9", "tools": "netxms",
                "supervised_since": T0, "managed": True}]
    windows = downtime.source_windows(objects, {"netxms": (T0 + 100 * D, T0 + 10 * D)})
    ((since, horizon), _subject) = windows[("netxms", "netxms:9")]
    assert (since, horizon) == (T0 + 10 * D, T0 + 100 * D)
    # Journal complet seulement après l'horizon : aucune fenêtre.
    assert downtime.source_windows(objects, {"netxms": (T0 + D, T0 + 2 * D)}) == {}
