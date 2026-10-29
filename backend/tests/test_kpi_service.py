from datetime import date

from app.services import kpi_service
from app.services.kpi_service import monthly_summary, monthly_trend


class _Result:
    def __init__(self, values):
        self.values = values

    def one(self):
        return self.values


class _Session:
    def __init__(self, rows):
        self.rows = iter(rows)

    def execute(self, _query):
        return _Result(next(self.rows))


def test_monthly_delta_is_unavailable_when_previous_period_is_sparse():
    db = _Session(
        [
            (99.5, 4.0, 1.0, 2.0, 600, 20),
            (98.0, 5.0, 2.0, 3.0, 120, 4),
        ]
    )

    result = monthly_summary(db, 2026, 10)

    assert result["reliable"] is True
    assert result["previous_reliable"] is False
    assert result["delta"] == {
        "availability_pct": None,
        "avg_alerts": None,
        "avg_critical": None,
    }


def test_monthly_delta_is_computed_when_both_months_are_reliable():
    db = _Session(
        [
            (99.5, 4.0, 1.0, 2.0, 600, 20),
            (98.0, 5.0, 2.0, 3.0, 600, 30),
        ]
    )

    result = monthly_summary(db, 2026, 10)

    assert result["previous_reliable"] is True
    assert result["delta"] == {
        "availability_pct": 1.5,
        "avg_alerts": -1.0,
        "avg_critical": -1.0,
    }


def test_monthly_trend_reads_the_daily_rows_of_the_calendar_month(monkeypatch):
    calls = []

    def trend(_db, **kwargs):
        calls.append(kwargs)
        return [{"day": "2026-12-01"}]

    monkeypatch.setattr(kpi_service, "trend", trend)

    assert monthly_trend(None, 2026, 12, site="Ouaga DGI") == [{"day": "2026-12-01"}]
    # Décembre se termine au 1er janvier de l'année suivante.
    assert calls == [
        {"site": "Ouaga DGI", "start_at": date(2026, 12, 1), "end_at": date(2027, 1, 1)}
    ]
