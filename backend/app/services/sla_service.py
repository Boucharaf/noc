"""
Objectifs de service (SLA) par gravité : délai de prise en charge (TTO) et
de résolution (TTR).

Ce module ne porte que les OBJECTIFS. Le respect des engagements se mesure
sur les tickets iTop (incident_service.sla_by_group, at_risk, incident_kpis) :
c'est dans iTop que les incidents sont pris en charge et résolus.

Il ne mesure PAS le délai de détection de l'outil de supervision — le temps
entre la panne réelle et l'alerte. Cette question appartient à Zabbix ou à
Centreon, qui la connaissent mieux que nous.

POURQUOI LES CIBLES VIVENT EN BASE ET NON DANS LE CODE. Un engagement de
service se négocie, se révise et doit pouvoir être modifié par le chef du
NOC sans redéploiement. `ops_sla_target` est livrée avec des valeurs de
départ pour que les écrans ne soient pas vides — ce sont des PARAMÈTRES avec
une valeur par défaut, pas des données fictives.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.models import SlaTarget


def targets(db: Session) -> dict[str, SlaTarget]:
    return {
        row.severity: row
        for row in db.execute(select(SlaTarget)).scalars()
    }


def list_targets(db: Session) -> list[dict]:
    rows = targets(db)
    return [
        {
            "severity": severity,
            "tta_target_minutes": rows[severity].tta_target_minutes,
            "ttr_target_minutes": rows[severity].ttr_target_minutes,
        }
        for severity in SEVERITIES
        if severity in rows
    ]


def update_target(
    db: Session,
    severity: str,
    tta_target_minutes: int | None = None,
    ttr_target_minutes: int | None = None,
) -> dict:
    row = db.execute(
        select(SlaTarget).where(SlaTarget.severity == severity)
    ).scalar_one_or_none()
    if row is None:
        row = SlaTarget(
            severity=severity,
            tta_target_minutes=tta_target_minutes or 60,
            ttr_target_minutes=ttr_target_minutes or 480,
        )
        db.add(row)
    else:
        if tta_target_minutes is not None:
            row.tta_target_minutes = tta_target_minutes
        if ttr_target_minutes is not None:
            row.ttr_target_minutes = ttr_target_minutes
    db.commit()
    db.refresh(row)
    return {
        "severity": row.severity,
        "tta_target_minutes": row.tta_target_minutes,
        "ttr_target_minutes": row.ttr_target_minutes,
    }
