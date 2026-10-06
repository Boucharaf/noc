from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.services import sla_service


class _Result:
    def all(self):
        return [
            SimpleNamespace(
                severity="critical",
                total=10,
                acknowledged=8,
                resolved=4,
                resolved_with_target=4,
                breached=3,
                tta_s=120,
                ttr_s=900,
            )
        ]


class _Session:
    def __init__(self):
        self.query = None

    def execute(self, query):
        self.query = query
        return _Result()


def test_compliance_counts_only_resolved_alerts_with_a_target(monkeypatch):
    monkeypatch.setattr(
        sla_service,
        "targets",
        lambda _db: {
            "critical": SimpleNamespace(
                tta_target_minutes=15,
                ttr_target_minutes=60,
            )
        },
    )

    db = _Session()
    result = sla_service.compliance(db, days=30)
    sql = str(db.query.compile(dialect=postgresql.dialect()))

    assert result["handled_total"] == 10
    assert result["resolved_total"] == 4
    assert result["breached_total"] == 3
    assert result["by_severity"][0]["breached"] == 3
    assert "resolved_with_target" in sql
    assert "breached" in sql


def test_compliance_accepts_an_explicit_half_open_period(monkeypatch):
    monkeypatch.setattr(
        sla_service,
        "targets",
        lambda _db: {
            "critical": SimpleNamespace(
                tta_target_minutes=15,
                ttr_target_minutes=60,
            )
        },
    )
    db = _Session()
    start = datetime(2026, 2, 1, tzinfo=UTC)
    end = datetime(2026, 3, 1, tzinfo=UTC)

    sla_service.compliance(db, start_at=start, end_at=end)

    compiled = db.query.compile(dialect=postgresql.dialect())
    assert start in compiled.params.values()
    assert end in compiled.params.values()
    assert "detected_at >=" in str(compiled)
    assert "detected_at <" in str(compiled)
