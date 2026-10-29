"""Rapport mensuel : agrégats de collecte (kpi_daily) et tickets iTop du mois."""
import asyncio
from datetime import UTC, date, datetime

import pytest

from app.services import incident_service, kpi_service, report_service


def _patch_kpi_daily(monkeypatch, calls):
    monkeypatch.setattr(
        kpi_service,
        "monthly_summary",
        lambda _db, year, month: {
            "year": year,
            "month": month,
            "current": {"availability_pct": 98.5, "days_with_data": 28},
            "previous": {"availability_pct": 97.0},
            "delta": {"availability_pct": 1.5},
            "reliable": True,
        },
    )

    def monthly_trend(_db, year, month):
        calls["trend"] = (year, month)
        return []

    def sites_ranking(_db, **kwargs):
        calls["sites"] = kwargs
        return [{"site": "Ouaga DGI", "availability_pct": 97.2, "avg_alerts": 1.5, "avg_down": 0.2}]

    monkeypatch.setattr(kpi_service, "monthly_trend", monthly_trend)
    monkeypatch.setattr(kpi_service, "sites_ranking", sites_ranking)


SLA = {
    "totals": {"mtto_minutes": 12.0, "mttr_minutes": 300.0, "compliance_pct": 90.0, "breached": 2},
    "by_severity": [
        {"severity": "critical", "incidents": 4, "mtto_minutes": 10.0,
         "mttr_minutes": 200.0, "compliance_pct": 75.0},
    ],
    "targets": {"critical": {"tto": 15, "ttr": 240}},
}
KPIS = {
    "total": 20, "resolved": 18, "resolution_rate_pct": 90.0, "recurrent_threshold": 3,
    "recurrent_nodes": 1, "without_cause_pct": 10.0, "reopened": 1, "cause_available": True,
    "causes": [{"cause": "hardware repair", "count": 9, "share_pct": 50.0}],
    "breaches": [
        {"ref": "I-1", "node_name": "RT-OUAGA", "severity": "critical", "open": False,
         "ttr_minutes": 400.0, "target_minutes": 240, "overrun_minutes": 160.0},
    ],
}


def test_monthly_report_reads_the_selected_month_everywhere(monkeypatch):
    calls = {}
    _patch_kpi_daily(monkeypatch, calls)

    async def sla_by_group(_db, group_by, **kwargs):
        calls["sla"] = (group_by, kwargs)
        return SLA

    async def incident_kpis(_db, **kwargs):
        calls["kpis"] = kwargs
        return KPIS

    monkeypatch.setattr(incident_service, "sla_by_group", sla_by_group)
    monkeypatch.setattr(incident_service, "incident_kpis", incident_kpis)

    data = asyncio.run(report_service.collect_report_data(object(), month=2, year=2024))

    start = datetime(2024, 2, 1, tzinfo=UTC)
    end = datetime(2024, 3, 1, tzinfo=UTC)
    assert calls["trend"] == (2024, 2)
    assert calls["sites"] == {"limit": 15, "start_at": date(2024, 2, 1), "end_at": date(2024, 3, 1)}
    assert calls["sla"] == ("region", {"start_at": start, "end_at": end})
    assert calls["kpis"] == {"start_at": start, "end_at": end}
    assert data["itop_error"] is None
    assert ["Délai moyen de résolution (MTTR)", "5 h"] in report_service.incident_rows(data)
    assert report_service.severity_rows(data) == [
        ["Critique", "4", "10 min", "3 h 20", "4 h", "75.0 %"]
    ]
    assert report_service.cause_rows(data) == [["Réparation matérielle", "9", "50.0 %"]]
    assert report_service.breach_rows(data)[0][:3] == ["I-1", "RT-OUAGA", "Critique"]


def test_monthly_report_is_still_produced_when_itop_is_unavailable(monkeypatch):
    _patch_kpi_daily(monkeypatch, {})

    async def unavailable(*_args, **_kwargs):
        raise incident_service.IncidentsUnavailable("HTTP 503")

    monkeypatch.setattr(incident_service, "sla_by_group", unavailable)
    monkeypatch.setattr(incident_service, "incident_kpis", unavailable)

    data = asyncio.run(report_service.collect_report_data(object(), month=2, year=2024))

    assert data["itop_error"]
    assert data["sites"]  # la partie collecte reste là
    assert report_service.severity_rows(data) == []
    assert report_service.cause_rows(data) == []


@pytest.mark.parametrize("renderer", ["render_pdf", "render_docx"])
def test_report_files_are_rendered(monkeypatch, tmp_path, renderer):
    monkeypatch.setattr(report_service, "REPORT_OUTPUT_DIR", str(tmp_path))
    data = {
        "organisation": "ANPTIC",
        "generated_at": datetime(2024, 3, 1, tzinfo=UTC),
        "period": "février 2024",
        "month": 2,
        "year": 2024,
        "monthly": {
            "current": {"availability_pct": 98.5, "days_with_data": 28},
            "previous": {"availability_pct": 97.0},
            "delta": {"availability_pct": 1.5},
            "reliable": True,
        },
        "trend": [],
        "sites": [],
        "sla": SLA,
        "incidents": KPIS,
        "itop_error": None,
    }

    path = getattr(report_service, renderer)(data)

    assert path.endswith((".pdf", ".docx"))
    assert (tmp_path / path.split("\\")[-1].split("/")[-1]).stat().st_size > 1000
