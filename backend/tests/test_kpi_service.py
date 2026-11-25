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


def test_health_score_weights_components_and_reports_missing_ones():
    """AM-03 : 40 % dispo, 20 % incidents, 20 % alertes, 20 % couverture."""
    from app.services.kpi_service import health_score

    full = health_score(90.0, critical_incidents=1, critical_alerts=2, supervised=80, expected=100)
    # 0,4×90 + 0,2×90 + 0,2×80 + 0,2×80 = 86
    assert full["score"] == 86
    assert full["missing"] == []

    # iTop indisponible : la composante « incidents » est écartée, poids renormalisés.
    no_itop = health_score(90.0, None, 2, 80, 100)
    assert no_itop["missing"] == ["incidents"]
    assert no_itop["score"] == round((0.4 * 90 + 0.2 * 80 + 0.2 * 80) / 0.8)

    # Aucun équipement supervisé : non évaluable.
    assert health_score(None, 0, 0, 0, 10)["score"] is None


def test_cmdb_coverage_and_ack_delay():
    from app.services.kpi_service import _cmdb_coverage, _delay_minutes

    nodes = [
        {"sources": {"itop": "1", "zabbix": "1"}, "state": "up"},
        {"sources": {"itop": "2"}, "state": "unknown"},          # CMDB seule
        {"sources": {"itop": "3", "netxms": "3"}, "state": "unknown"},  # vu, pas observé
        {"sources": {"zabbix": "4"}, "state": "up"},              # hors CMDB
    ]
    assert _cmdb_coverage(nodes) == {
        "cmdb_nodes": 3, "cmdb_supervised": 1, "cmdb_coverage_pct": 33.3,
    }
    assert _delay_minutes("2026-01-01T00:00:00+00:00", "2026-01-01T00:12:00Z") == 12.0
    assert _delay_minutes("2026-01-01T00:12:00+00:00", "2026-01-01T00:00:00+00:00") is None
    assert _delay_minutes(None, "2026-01-01T00:00:00+00:00") is None


def test_naming_convention_flags_names_outside_site_role_nn():
    from app.services.kpi_service import _naming

    result = _naming([{"name": "PA-RTR-01"}, {"name": "pa-sw-12"}, {"name": "OUAHA-x"},
                      {"name": "PA2BONI"}])
    assert result["naming_nonconforming"] == 2
    assert result["naming_examples"] == ["OUAHA-x", "PA2BONI"]
