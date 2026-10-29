"""Résilience : notifications après une coupure, bilans journaliers qui
survivent à un redémarrage et à une base indisponible, rafales d'alertes."""
import asyncio
from datetime import date, datetime, timezone

from collector import rollup
from collector.state import KEY_ALERT_SEEN, KEY_ALERT_SEEN_SINCE, SnapshotStore
from integrations.models import Alert

from app.services import notification_service as ns
from tests.fakes import MemoryStore


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return queue

    async def execute(self):
        for name, args, kwargs in self.ops:
            await getattr(self.redis, name)(*args, **kwargs)


class _Redis:
    """Le sous-ensemble de Redis qu'utilise diff_new_alerts, sans expiration
    implicite : ce qui est écrit reste."""

    def __init__(self):
        self.data = {}

    async def smembers(self, key):
        return set(self.data.get(key, set()))

    async def exists(self, key):
        return int(key in self.data)

    async def delete(self, key):
        self.data.pop(key, None)

    async def sadd(self, key, *members):
        self.data.setdefault(key, set()).update(members)

    async def set(self, key, value, nx=False):
        if not (nx and key in self.data):
            self.data[key] = value

    def pipeline(self, transaction=True):
        return _Pipeline(self)


def _alert(ref):
    return Alert(tool="zabbix", ref=ref, severity="critical", message="x",
                 since=datetime(2026, 10, 29, tzinfo=timezone.utc))


def test_first_start_is_silent_but_an_empty_network_still_notifies():
    store = SnapshotStore(_Redis())

    async def scenario():
        first = await store.diff_new_alerts([_alert("1")])      # vrai premier démarrage
        cleared = await store.diff_new_alerts([])                # plus aucune alerte
        fresh = await store.diff_new_alerts([_alert("2")])       # une panne apparaît
        return first, cleared, fresh

    first, cleared, fresh = asyncio.run(scenario())
    assert first == [] and cleared == []
    # Autrefois : ensemble vide = « premier démarrage » -> panne jamais notifiée.
    assert [a.ref for a in fresh] == ["2"]


def test_alerts_born_during_an_outage_are_notified_on_return():
    redis = _Redis()
    store = SnapshotStore(redis)
    asyncio.run(store.diff_new_alerts([_alert("1")]))
    # Collecteur arrêté des heures : rien n'expire (pas de TTL sur ces clés).
    assert KEY_ALERT_SEEN in redis.data and KEY_ALERT_SEEN_SINCE in redis.data
    back = asyncio.run(store.diff_new_alerts([_alert("1"), _alert("7"), _alert("8")]))
    assert sorted(a.ref for a in back) == ["7", "8"]


def test_previous_version_seen_set_counts_as_initialised():
    redis = _Redis()
    redis.data[KEY_ALERT_SEEN] = {"zabbix:1"}   # écrit par l'ancienne version
    new = asyncio.run(SnapshotStore(redis).diff_new_alerts([_alert("1"), _alert("2")]))
    assert [a.ref for a in new] == ["2"]


# -- Bilans journaliers --------------------------------------------------------
class _Node:
    def __init__(self, state):
        self.state, self.id, self.site = state, state, None


def test_rollup_counters_survive_a_restart(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})
    day = date(2026, 10, 28)
    rollup.observe(day, None, [_Node("up"), _Node("down")], [])
    saved = rollup.export_accumulator()

    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})        # redémarrage
    assert rollup.restore_accumulator(saved) == 1
    assert rollup.restore_accumulator(saved) == 1          # rejoué : rien de doublé
    rollup.observe(day, None, [_Node("up"), _Node("up")], [])
    (row,) = rollup.rows_for(day)
    assert row["samples"] == 2
    assert row["fleet_availability_pct"] == 75.0
    assert rollup._ACCUMULATOR, "rows_for ne vide pas les compteurs"


def test_pending_days_wait_for_rollup_hour(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})
    monkeypatch.setattr(rollup.config, "ROLLUP_HOUR", 1)
    for day in (date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 29)):
        rollup.observe(day, None, [_Node("up")], [])
    before = datetime(2026, 10, 29, 0, 30, tzinfo=timezone.utc)
    after = datetime(2026, 10, 29, 1, 5, tzinfo=timezone.utc)
    assert rollup.pending_days(before) == [date(2026, 10, 26)]
    assert rollup.pending_days(after) == [date(2026, 10, 26), date(2026, 10, 28)]


def test_failed_write_keeps_the_day_and_retries(monkeypatch):
    monkeypatch.setattr(rollup, "_ACCUMULATOR", {})
    monkeypatch.setattr(rollup.config, "ROLLUP_HOUR", 1)
    day = date(2026, 10, 28)
    rollup.observe(day, None, [_Node("up")], [])
    now = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
    store = MemoryStore()
    written = []

    async def down(_rows):
        raise ConnectionError("base indisponible")

    async def up(rows):
        written.extend(rows)

    monkeypatch.setattr(rollup, "write_rows", down)
    assert asyncio.run(rollup.write_pending(store, now)) is True
    assert rollup.pending_days(now) == [day]
    assert store.rollup and store.rollup[0]["day"] == day.isoformat()   # sauvegardé

    monkeypatch.setattr(rollup, "write_rows", up)
    assert asyncio.run(rollup.write_pending(store, now)) is False
    assert [row["day"] for row in written] == [day]
    assert rollup.pending_days(now) == [] and store.rollup == []


# -- Rafales -------------------------------------------------------------------
def test_burst_sends_one_summary_and_claims_every_alert(monkeypatch):
    claimed, sent = set(), []
    monkeypatch.setattr(ns, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(ns, "NOTIFY_BURST_MAX", 3)
    monkeypatch.setattr(ns, "_claim", lambda key: key not in claimed and not claimed.add(key))
    monkeypatch.setattr(ns, "send_sms", lambda key, body: sent.append(("sms", key, body)))
    monkeypatch.setattr(
        ns, "send_email",
        lambda key, subject, html_body, text_body, site=None: sent.append(("email", key, subject)),
    )
    alerts = [
        {"tool": "zabbix", "ref": str(i), "severity": "critical" if i < 2 else "high",
         "node_name": f"n{i}", "site": "Gaoua", "message": "Ping"}
        for i in range(5)
    ]
    asyncio.run(ns.notify_new_alerts(alerts))
    assert len(claimed) == 5
    channels = [entry[0] for entry in sent]
    assert channels == ["sms", "email"]
    assert sent[1][2] == "[NOC] 5 nouvelles alertes graves dont 2 critiques"
    assert sent[1][1].startswith("digest:")

    sent.clear()
    asyncio.run(ns.notify_new_alerts(alerts))   # second backend : déjà réservées
    assert sent == []
