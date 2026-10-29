"""Objectifs SLA par gravité — seul contenu SLA conservé en base."""
from types import SimpleNamespace

from app.services import sla_service


class _Session:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commits = 0

    def execute(self, _query):
        existing = self.existing
        return SimpleNamespace(scalar_one_or_none=lambda: existing)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1

    def refresh(self, _row):
        pass


def test_list_targets_follows_severity_order(monkeypatch):
    monkeypatch.setattr(
        sla_service,
        "targets",
        lambda _db: {
            "low": SimpleNamespace(tta_target_minutes=480, ttr_target_minutes=4320),
            "critical": SimpleNamespace(tta_target_minutes=15, ttr_target_minutes=240),
        },
    )

    assert [row["severity"] for row in sla_service.list_targets(None)] == ["critical", "low"]


def test_update_target_changes_only_the_fields_sent():
    row = SimpleNamespace(severity="critical", tta_target_minutes=15, ttr_target_minutes=240)
    db = _Session(existing=row)

    result = sla_service.update_target(db, "critical", ttr_target_minutes=180)

    assert result == {"severity": "critical", "tta_target_minutes": 15, "ttr_target_minutes": 180}
    assert db.commits == 1
    assert db.added == []


def test_update_target_creates_a_missing_severity():
    db = _Session()

    result = sla_service.update_target(db, "info", tta_target_minutes=600)

    assert result["tta_target_minutes"] == 600
    assert result["ttr_target_minutes"] == 480
    assert len(db.added) == 1
