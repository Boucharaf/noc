from app.services.kpi_service import monthly_summary


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