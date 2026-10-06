from datetime import datetime
from types import SimpleNamespace

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


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _MonthlyTrendSession:
    def __init__(self, results):
        self.results = iter(results)

    def execute(self, _query):
        return _RowsResult(next(self.results))


def test_monthly_trend_returns_calendar_months_and_noc_alert_counts():
    db = _MonthlyTrendSession(
        [
            [
                SimpleNamespace(
                    period=datetime(2026, 10, 1),
                    avg_alerts=3.24,
                    availability_pct=99.12,
                )
            ],
            [SimpleNamespace(period=datetime(2026, 10, 1), handled=8)],
            [SimpleNamespace(period=datetime(2026, 10, 1), resolved=5)],
        ]
    )

    result = monthly_trend(db, 2026, 10, months=12)

    assert len(result) == 12
    assert (result[0]["year"], result[0]["month"]) == (2025, 11)
    assert (result[-1]["year"], result[-1]["month"]) == (2026, 10)
    assert result[-1] == {
        "year": 2026,
        "month": 10,
        "avg_alerts": 3.2,
        "availability_pct": 99.12,
        "handled": 8,
        "resolved": 5,
    }
    assert result[0]["handled"] == 0
