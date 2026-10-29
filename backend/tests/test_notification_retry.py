"""Nouvelles tentatives des notifications échouées.

Avant : le verrou anti-doublon était pris avant l'envoi, et un envoi échoué
n'était jamais retenté — un serveur SMTP en panne pendant une panne critique
et personne n'était prévenu. Ces tests fixent le nouveau contrat.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AlertNotified, NotificationLog, NotificationRetry
from app.services import notification_service as ns

T0 = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)


class _Smtp:
    """Serveur SMTP simulé : en panne tant que `down` est vrai."""

    def __init__(self):
        self.down = True
        self.sent = []

    def __call__(self, subject, html_body, text_body, recipients):
        if self.down:
            raise ConnectionRefusedError("SMTP injoignable")
        self.sent.append((subject, list(recipients)))


class _Twilio:
    """Passerelle SMS simulée : refuse les numéros de `failing`."""

    def __init__(self, failing):
        self.failing = set(failing)
        self.sent = []
        self.messages = self

    def create(self, **kwargs):
        if kwargs["to"] in self.failing:
            raise RuntimeError(f"refusé : {kwargs['to']}")
        self.sent.append(kwargs["to"])


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (AlertNotified, NotificationLog, NotificationRetry):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(ns, "SessionLocal", session)
    monkeypatch.setattr(ns, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(ns, "NOTIFY_RETRY_MAX_ATTEMPTS", 4)
    monkeypatch.setattr(ns, "NOTIFY_RETRY_MAX_AGE_MIN", 360)
    monkeypatch.setattr(ns, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(ns, "email_recipients", lambda site=None: ["astreinte@example.bf"])
    monkeypatch.setattr(ns, "_now", lambda: T0)
    return session


def _jobs(session):
    with session() as db:
        return [
            (job.channel, job.status, job.attempts, job.recipients)
            for job in db.query(NotificationRetry).order_by(NotificationRetry.channel)
        ]


def _logs(session):
    with session() as db:
        return [(log.channel, log.status) for log in db.query(NotificationLog).order_by("id")]


def _notify(key="zabbix:42"):
    ns.notify_alert(
        alert_key=key, node_name="RT-DDG", site="Dédougou", severity="critical",
        message="Ping perdu", source="zabbix",
    )


def test_failed_email_is_retried_with_backoff_until_it_leaves(db, monkeypatch):
    smtp = _Smtp()
    monkeypatch.setattr(ns, "_deliver", smtp)
    _notify()
    assert _jobs(db) == [("email", "pending", 1, None)]

    # Pas encore échu : rien ne part.
    assert ns.retry_due({"zabbix:42"}, now=T0 + timedelta(seconds=30)) == {
        "sent": 0, "failed": 0, "abandoned": 0,
    }
    # Échu, SMTP toujours en panne : prochaine tentative dans 5 min.
    assert ns.retry_due({"zabbix:42"}, now=T0 + timedelta(minutes=1))["failed"] == 1
    assert _jobs(db) == [("email", "pending", 2, None)]
    assert ns.retry_due({"zabbix:42"}, now=T0 + timedelta(minutes=3))["failed"] == 0

    smtp.down = False
    assert ns.retry_due({"zabbix:42"}, now=T0 + timedelta(minutes=6))["sent"] == 1
    assert _jobs(db) == [("email", "sent", 3, None)]
    assert smtp.sent == [("[NOC] Alerte CRITIQUE — RT-DDG", ["astreinte@example.bf"])]
    assert _logs(db)[-1] == ("email", "sent")


def test_sms_retries_only_the_numbers_that_failed(db, monkeypatch):
    monkeypatch.setattr(ns, "SMTP_HOST", "")
    monkeypatch.setattr(ns, "TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setattr(ns, "TWILIO_FROM_NUMBER", "+22600000000")
    monkeypatch.setattr(ns, "NOC_SMS_RECIPIENTS", ["+226001", "+226002", "+226003"])
    gateway = _Twilio(failing={"+226002"})
    monkeypatch.setattr(ns, "_twilio_client", lambda: gateway)

    _notify()
    assert gateway.sent == ["+226001", "+226003"]
    assert _jobs(db) == [("sms", "pending", 1, "+226002")]

    gateway.failing.clear()
    assert ns.retry_due({"zabbix:42"}, now=T0 + timedelta(minutes=1))["sent"] == 1
    # Les deux premiers numéros ne reçoivent pas le message une seconde fois.
    assert gateway.sent == ["+226001", "+226003", "+226002"]


def test_closed_alert_and_exhausted_attempts_are_abandoned(db, monkeypatch):
    monkeypatch.setattr(ns, "_deliver", _Smtp())
    _notify("zabbix:1")
    _notify("zabbix:2")

    # zabbix:1 s'est refermée dans l'outil : on ne prévient plus.
    counts = ns.retry_due({"zabbix:2"}, now=T0 + timedelta(minutes=1))
    assert counts == {"sent": 0, "failed": 1, "abandoned": 1}

    # zabbix:2 : tentatives 2, 3, puis 4 = maximum -> abandon.
    ns.retry_due({"zabbix:2"}, now=T0 + timedelta(minutes=7))
    counts = ns.retry_due({"zabbix:2"}, now=T0 + timedelta(minutes=30))
    assert counts["abandoned"] == 1
    assert {status for _c, status, _a, _r in _jobs(db)} == {"abandoned"}
    assert ("email", "abandoned") in _logs(db)
    assert ns.retry_status(now=T0 + timedelta(hours=1)) == {"pending": 0, "abandoned_24h": 2}


def test_unknown_snapshot_does_not_abandon_and_old_alerts_give_up(db, monkeypatch):
    monkeypatch.setattr(ns, "_deliver", _Smtp())
    _notify()
    # Instantané illisible (None) : on retente au lieu de tout abandonner.
    assert ns.retry_due(None, now=T0 + timedelta(minutes=1))["failed"] == 1
    # Six heures plus tard, prévenir n'a plus de sens.
    assert ns.retry_due(None, now=T0 + timedelta(hours=7))["abandoned"] == 1


def test_a_second_backend_does_not_send_or_schedule_twice(db, monkeypatch):
    smtp = _Smtp()
    monkeypatch.setattr(ns, "_deliver", smtp)
    _notify()
    _notify()  # même alerte reçue par un second backend
    assert len(_jobs(db)) == 1
    assert [log for log in _logs(db) if log[1] == "failed"] == [("email", "failed")]
