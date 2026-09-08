"""
Indicateurs SLA du mois.

Les objectifs ne sont plus codés en dur : ils viennent de
`ops_sla_target` (peuplée avec des valeurs par défaut par
sql/01_backend_extensions.sql), une ligne par sévérité normalisée.

Les incidents survenus pendant une fenêtre de maintenance planifiée sont
exclus du calcul — c'est précisément la raison d'être de la colonne
`is_maintenance` de la vue `v_incident`. Les compter reviendrait à
sanctionner le SLA pour des coupures décidées à l'avance.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.kpi_service import _period_availability
from app.services.periods import month_bounds, period_payload


def get_sla(db: Session, month: int, year: int) -> dict:
    start, end = month_bounds(month, year)

    rows = db.execute(
        text(
            """
            SELECT
                t.severity,
                t.ttr_target_minutes,
                t.tta_target_minutes,
                t.availability_target_pct,
                COALESCE(agg.total, 0)     AS total,
                COALESCE(agg.resolved, 0)  AS resolved,
                agg.avg_mttr,
                agg.avg_mtta,
                COALESCE(agg.ttr_met, 0)   AS ttr_met,
                COALESCE(agg.tta_met, 0)   AS tta_met
            FROM ops_sla_target t
            LEFT JOIN LATERAL (
                SELECT
                    count(*)                                                   AS total,
                    count(*) FILTER (WHERE i.status IN ('resolved','closed'))   AS resolved,
                    avg(i.mttr_minutes)                                        AS avg_mttr,
                    avg(i.mtta_minutes)                                        AS avg_mtta,
                    count(*) FILTER (
                        WHERE i.mttr_minutes IS NOT NULL
                          AND i.mttr_minutes <= t.ttr_target_minutes
                    )                                                          AS ttr_met,
                    count(*) FILTER (
                        WHERE i.mtta_minutes IS NOT NULL
                          AND i.mtta_minutes <= t.tta_target_minutes
                    )                                                          AS tta_met
                FROM v_incident i
                WHERE i.severity = t.severity
                  AND i.detected_at >= :start AND i.detected_at < :end
                  AND NOT i.is_maintenance
            ) agg ON TRUE
            ORDER BY noc_severity_rank(t.severity)
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()

    by_severity = []
    indicators = []

    for r in rows:
        total = int(r["total"])
        resolved = int(r["resolved"])
        ttr_met = int(r["ttr_met"])
        tta_met = int(r["tta_met"])

        # Taux de respect calculé sur les incidents RÉSOLUS, pas sur le
        # total : un incident encore ouvert n'a pas de MTTR, l'inclure au
        # dénominateur ferait chuter le taux à mesure que le mois avance.
        ttr_rate = round(ttr_met / resolved * 100, 1) if resolved else None

        by_severity.append(
            {
                "severity": r["severity"],
                "total_incidents": total,
                "resolved": resolved,
                "ttr_target_minutes": int(r["ttr_target_minutes"]),
                "tta_target_minutes": int(r["tta_target_minutes"]),
                "avg_mttr_minutes": round(float(r["avg_mttr"]), 1) if r["avg_mttr"] else None,
                "avg_mtta_minutes": round(float(r["avg_mtta"]), 1) if r["avg_mtta"] else None,
                "ttr_compliance_pct": ttr_rate,
                "tta_compliance_pct": round(tta_met / resolved * 100, 1) if resolved else None,
                "breached": max(0, resolved - ttr_met),
            }
        )

        if r["avg_mttr"] is not None:
            indicators.append(
                {
                    "metric": f"MTTR {r['severity']}",
                    "value": round(float(r["avg_mttr"]), 1),
                    "target": float(r["ttr_target_minutes"]),
                    "unit": "min",
                    "status": (
                        "met"
                        if float(r["avg_mttr"]) <= float(r["ttr_target_minutes"])
                        else "not_met"
                    ),
                }
            )

    availability = _period_availability(db, month, year)
    availability_target = db.execute(
        text("SELECT availability_target_pct FROM ops_sla_target WHERE severity = 'critical'")
    ).scalar()
    if availability is not None and availability_target is not None:
        indicators.insert(
            0,
            {
                "metric": "Disponibilité réseau",
                "value": availability,
                "target": float(availability_target),
                "unit": "%",
                "status": "met" if availability >= float(availability_target) else "not_met",
            },
        )

    total_resolved = sum(s["resolved"] for s in by_severity)
    total_breached = sum(s["breached"] for s in by_severity)

    return {
        "period": period_payload(month, year),
        "indicators": indicators,
        "by_severity": by_severity,
        "global_compliance_pct": (
            round((total_resolved - total_breached) / total_resolved * 100, 1)
            if total_resolved
            else None
        ),
        "total_breached": total_breached,
    }


def list_targets(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, severity, ttr_target_minutes, tta_target_minutes,
                   availability_target_pct
            FROM ops_sla_target
            ORDER BY noc_severity_rank(severity)
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def update_target(
    db: Session,
    severity: str,
    *,
    ttr_target_minutes: int | None = None,
    tta_target_minutes: int | None = None,
    availability_target_pct: float | None = None,
) -> dict:
    db.execute(
        text(
            """
            UPDATE ops_sla_target SET
                ttr_target_minutes = COALESCE(:ttr, ttr_target_minutes),
                tta_target_minutes = COALESCE(:tta, tta_target_minutes),
                availability_target_pct = COALESCE(:avail, availability_target_pct)
            WHERE severity = :severity
            """
        ),
        {
            "severity": severity,
            "ttr": ttr_target_minutes,
            "tta": tta_target_minutes,
            "avail": availability_target_pct,
        },
    )
    db.commit()
    return next(t for t in list_targets(db) if t["severity"] == severity)
