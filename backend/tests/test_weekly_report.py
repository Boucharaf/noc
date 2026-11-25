"""Rapport hebdomadaire (AM-27) : rendu PDF et envoi UNIQUE par semaine."""
import asyncio
import os
from datetime import UTC, datetime

from app.services import weekly_report_service as weekly

MONDAY_8H = datetime(2026, 11, 23, 8, tzinfo=UTC)


def _data():
    return {
        "start": datetime(2026, 11, 16, 8, tzinfo=UTC),
        "end": MONDAY_8H,
        "generated_at": MONDAY_8H,
        "availability": {
            "available": True, "average_pct": 98.75, "subjects": 12,
            "basis": {"unsupervised": 3}, "failures": 4, "mttr_minutes": 95.0,
            "mtbf_hours": 40.0,
            "rows": [{"name": "PA-RTR-01", "site": "Pâ", "availability_pct": 91.2,
                      "down_count": 2}],
        },
        "incidents": {"total": 20, "resolved": 15, "resolution_rate_pct": 75.0, "breached": 3},
        "sla": {"compliance_pct": 88.0, "mtto_minutes": 30.0, "mttr_minutes": 300.0},
    }


def test_weekly_pdf_renders_with_accents_and_missing_sections():
    path = weekly.render_pdf(_data())
    try:
        with open(path, "rb") as handle:
            assert handle.read(5) == b"%PDF-"
    finally:
        os.remove(path)
    # Sections absentes (iTop et journal indisponibles) : le rapport sort quand même.
    path = weekly.render_pdf({**_data(), "availability": None, "incidents": None, "sla": None})
    os.remove(path)


def test_weekly_report_is_sent_once_per_week(monkeypatch):
    from app.db import redis_client
    from app.services import notification_service

    class Redis:
        def __init__(self):
            self.keys = set()

        def set(self, key, _value, nx=False, ex=None):
            if nx and key in self.keys:
                return None
            self.keys.add(key)
            return True

    sent = []
    monkeypatch.setattr(redis_client, "redis_sync", Redis())
    monkeypatch.setattr(weekly, "recipients", lambda: ["direction@anptic.bf"])

    async def fake_generate(_db):
        return weekly.render_pdf(_data())

    monkeypatch.setattr(weekly, "generate", fake_generate)
    monkeypatch.setattr(
        notification_service, "deliver_with_attachment",
        lambda subject, _text, to, path, filename: sent.append((to, filename)),
    )

    class Session:
        def close(self):
            pass

    from app.db import session as db_session

    monkeypatch.setattr(db_session, "SessionLocal", Session)

    # Mardi : pas d'envoi. Lundi 08:00 : un envoi, puis plus rien (2e processus).
    assert asyncio.run(weekly.send_if_due(datetime(2026, 11, 24, 8, tzinfo=UTC))) is False
    assert asyncio.run(weekly.send_if_due(MONDAY_8H)) is True
    assert asyncio.run(weekly.send_if_due(MONDAY_8H)) is False
    assert sent == [(["direction@anptic.bf"], "rapport-noc-2026-S48.pdf")]
