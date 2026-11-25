"""Pannes des hôtes Centreon : même règle que NetXMS, priorité à NetXMS.

Centreon ne garde pas de table de pannes : ses pannes se déduisent des
changements d'état CONFIRMÉS (HARD) de chaque hôte. Seul DOWN est une panne
de l'hôte ; UNREACHABLE (panne en amont) n'en est pas une.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from collector import downtime
from integrations.base import ToolUnavailable
from integrations.centreon import CentreonClient, host_downtimes
from integrations.centreon_logs import CentreonLogClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import HistAlert, HistDowntime, HistSourceSync, HistState
from app.services import availability_service as av

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)


def test_state_changes_become_outages():
    events = [(T0 + H, 1), (T0 + 2 * H, 0), (T0 + 3 * H, 1), (T0 + 4 * H, 2), (T0 + 5 * H, 1)]
    assert host_downtimes("host-5", events) == [
        {"object_id": "host-5", "start": T0 + H, "end": T0 + 2 * H, "tag": "DOWN"},
        # DOWN → UNREACHABLE : l'hôte n'est plus en panne lui-même.
        {"object_id": "host-5", "start": T0 + 3 * H, "end": T0 + 4 * H, "tag": "DOWN"},
        {"object_id": "host-5", "start": T0 + 5 * H, "end": None, "tag": "DOWN"},
    ]


def test_first_recovery_closes_an_outage_started_earlier():
    """Panne commencée avant la fenêtre relue : seule sa fin est connue."""
    records = host_downtimes("host-5", [(T0 + H, 0), (T0 + 2 * H, 1), (T0 + 3 * H, 0)])
    assert records[0] == {"object_id": "host-5", "start": None, "end": T0 + H, "tag": "DOWN"}
    assert downtime.closures(records) == [("host-5", "DOWN", T0 + H)]
    stored = downtime.rows_to_store(records, [], "centreon")
    assert [(r["node_id"], r["started_at"]) for r in stored] == [("centreon:host-5", T0 + 2 * H)]


def test_api_timeline_is_paginated_filtered_and_retried_without_date_filter():
    client = CentreonClient("http://centreon")
    calls = []

    async def fake_resources(_types, _extra=None):
        return [{"id": 5, "type": "host"}]

    async def fake_get(path, params=None):
        calls.append((path, dict(params or {})))
        if "search" in (params or {}):
            raise ToolUnavailable("centreon", "HTTP 400 search non supporté")
        rows = [
            {"type": "event", "date": (T0 - H).isoformat(), "status": {"code": 1}},  # trop ancien
            {"type": "event", "date": (T0 + H).isoformat(), "status": {"code": 1}},
            {"type": "comment", "date": (T0 + 90 * timedelta(minutes=1)).isoformat()},
            {"type": "event", "date": (T0 + 2 * H).isoformat(), "status": {"code": 0}},
        ]
        return {"result": rows, "meta": {"total": len(rows)}}

    client._resources = fake_resources
    client._get = fake_get

    records = asyncio.run(client.fetch_downtimes(T0))

    assert calls[0][0] == "/monitoring/hosts/5/timeline" and "search" in calls[0][1]
    assert "search" not in calls[1][1]
    assert records == [{"object_id": "host-5", "start": T0 + H, "end": T0 + 2 * H,
                        "tag": "DOWN"}]


def test_log_export_gives_the_same_outages(tmp_path):
    header = "log_id\tctime\thost_id\thost_name\tmsg_type\toutput\tservice_description\t" \
             "service_id\tstatus\ttype\n"
    lines = [
        (1, T0 + H, 1, 1, "1"),        # HOST ALERT DOWN HARD
        (2, T0 + H + 60 * timedelta(seconds=1), 0, 1, "0"),   # SOFT : ignoré
        (3, T0 + 2 * H, 0, 1, "1"),    # UP HARD
    ]
    body = "".join(
        f"{log_id}\t{int(at.timestamp())}\t7\tRT07\t{msg}\tPING\t\t\t{status}\t{kind}\n"
        for log_id, at, status, msg, kind in lines
    )
    path = tmp_path / "logs.tsv"
    path.write_text(header + body, encoding="utf8")

    client = CentreonLogClient(f"file://{path}")
    assert asyncio.run(client.fetch_downtimes(T0)) == [
        {"object_id": "host-7", "start": T0 + H, "end": T0 + 2 * H, "tag": "DOWN"}
    ]


# -- Priorité : une seule source maître par équipement ---------------------------------
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


def _node(db, row_id, node_id, tools):
    db.add(HistState(id=row_id, subject_kind="node", subject_id=node_id, node_id=node_id,
                     name=node_id, tools=tools, state="up", started_at=T0,
                     ended_at=T0 + 10 * H, last_seen_at=T0 + 10 * H))


def _down(db, row_id, source, node_id, start, end):
    db.add(HistDowntime(id=row_id, source=source, object_ref=node_id, node_id=node_id,
                        tag="", started_at=start, ended_at=end))


def test_netxms_wins_over_centreon_and_centreon_covers_the_rest(db, monkeypatch):
    now = T0 + 10 * H
    monkeypatch.setattr(av, "_now", lambda: now)
    monkeypatch.setattr(downtime.config, "NETXMS_DOWNTIME_ENABLED", True)
    monkeypatch.setattr(downtime.config, "CENTREON_DOWNTIME_ENABLED", True)
    _node(db, 1, "a", "centreon,netxms")     # vu par les deux
    _node(db, 2, "b", "centreon")            # Centreon seul
    _node(db, 3, "c", "zabbix")              # aucune source maître
    _down(db, 1, "netxms", "a", T0 + H, T0 + 2 * H)
    _down(db, 2, "centreon", "a", T0 + H, T0 + 5 * H)   # ignoré : NetXMS fait foi
    _down(db, 3, "centreon", "b", T0 + H, T0 + 3 * H)
    for source in ("netxms", "centreon"):
        db.add(HistSourceSync(source=source, synced_at=now - H, rows_read=1))
    db.commit()

    rows = {row["subject_id"]: row for row in av.ranking(db, "node", days=1)["rows"]}

    assert (rows["a"]["source"], rows["a"]["availability_pct"]) == ("netxms_downtime_log", 90.0)
    assert (rows["b"]["source"], rows["b"]["availability_pct"]) == ("centreon_host_events", 80.0)
    assert (rows["c"]["source"], rows["c"]["availability_pct"]) == ("noc_observation", 100.0)
