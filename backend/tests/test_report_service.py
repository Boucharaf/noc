from datetime import UTC, date, datetime

from app.services import kpi_service, report_service, sla_service


def test_monthly_report_passes_the_selected_month_to_every_section(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        kpi_service, "monthly_summary", lambda _db, year, month: {"year": year, "month": month}
    )

    def capture(name, result):
        def recorder(_db, **kwargs):
            calls[name] = kwargs
            return result

        return recorder

    monkeypatch.setattr(kpi_service, "trend", capture("trend", []))
    monkeypatch.setattr(kpi_service, "sites_ranking", capture("sites", []))
    monkeypatch.setattr(kpi_service, "causes", capture("causes", []))
    monkeypatch.setattr(kpi_service, "resolution_times", capture("resolution", {}))
    monkeypatch.setattr(sla_service, "compliance", capture("compliance", {}))
    monkeypatch.setattr(sla_service, "breaches", capture("breaches", []))

    result = report_service.collect_report_data(object(), month=2, year=2024)

    start = datetime(2024, 2, 1, tzinfo=UTC)
    end = datetime(2024, 3, 1, tzinfo=UTC)
    assert calls["trend"] == {
        "start_date": date(2024, 2, 1),
        "end_date": date(2024, 3, 1),
    }
    assert calls["sites"] == {
        "limit": 15,
        "start_date": date(2024, 2, 1),
        "end_date": date(2024, 3, 1),
    }
    for section in ("causes", "resolution", "compliance"):
        assert calls[section] == {"start_at": start, "end_at": end}
    assert calls["breaches"] == {
        "limit": 15,
        "start_at": start,
        "end_at": end,
    }
    assert result["monthly"] == {"year": 2024, "month": 2}
