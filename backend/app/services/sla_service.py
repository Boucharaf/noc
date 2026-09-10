"""
Respect des engagements de service.

CE QUE LE NOC MESURE, ET CE QU'IL NE MESURE PAS.

Il mesure SON délai de réaction : entre le moment où une alerte est apparue
et celui où un exploitant l'a prise en charge (TTA), puis clôturée (TTR).
Ces deux durées se lisent dans `ops_alert_state`, la table que le NOC
remplit lui-même.

Il ne mesure PAS le délai de détection de l'outil de supervision — le temps
entre la panne réelle et l'alerte. Cette question appartient à Zabbix ou à
Centreon, qui la connaissent mieux que nous, et la faire remonter ici
donnerait un chiffre dont personne ne saurait dire ce qu'il recouvre.

POURQUOI LES CIBLES VIVENT EN BASE ET NON DANS LE CODE. Un engagement de
service se négocie, se révise et doit pouvoir être modifié par le chef du
NOC sans redéploiement. `ops_sla_target` est livrée avec des valeurs de
départ pour que les écrans ne soient pas vides — ce sont des PARAMÈTRES avec
une valeur par défaut, pas des données fictives.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.models import AlertState, SlaTarget
from app.services import live_service

logger = logging.getLogger(__name__)


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
            "availability_target_pct": rows[severity].availability_target_pct,
        }
        for severity in SEVERITIES
        if severity in rows
    ]


def update_target(
    db: Session,
    severity: str,
    tta_target_minutes: int | None = None,
    ttr_target_minutes: int | None = None,
    availability_target_pct: float | None = None,
) -> dict:
    row = db.execute(
        select(SlaTarget).where(SlaTarget.severity == severity)
    ).scalar_one_or_none()
    if row is None:
        row = SlaTarget(
            severity=severity,
            tta_target_minutes=tta_target_minutes or 60,
            ttr_target_minutes=ttr_target_minutes or 480,
            availability_target_pct=availability_target_pct or 99.0,
        )
        db.add(row)
    else:
        if tta_target_minutes is not None:
            row.tta_target_minutes = tta_target_minutes
        if ttr_target_minutes is not None:
            row.ttr_target_minutes = ttr_target_minutes
        if availability_target_pct is not None:
            row.availability_target_pct = availability_target_pct
    db.commit()
    db.refresh(row)
    return {
        "severity": row.severity,
        "tta_target_minutes": row.tta_target_minutes,
        "ttr_target_minutes": row.ttr_target_minutes,
        "availability_target_pct": row.availability_target_pct,
    }


def compliance(db: Session, days: int = 30) -> dict:
    """Taux de respect, par gravité, sur la période.

    Le calcul est fait EN SQL et non en Python : compter des alertes tenues
    et non tenues est exactement ce qu'une base de données fait bien, et
    remonter toutes les lignes pour les compter côté application serait
    gratuitement coûteux le jour où la table grossira.

    Une alerte non encore clôturée n'entre dans aucun des deux camps — elle
    n'a pas encore de délai de résolution. La compter comme non tenue
    dégraderait le taux à cause d'alertes qu'on est peut-être en train de
    traiter dans les délais.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    goals = targets(db)

    rows = db.execute(
        select(
            AlertState.severity_at_pickup.label("severity"),
            func.count().label("total"),
            func.count(AlertState.acknowledged_at).label("acknowledged"),
            func.count(AlertState.resolved_at).label("resolved"),
            func.avg(
                func.extract("epoch", AlertState.acknowledged_at - AlertState.detected_at)
            ).label("tta_s"),
            func.avg(
                func.extract("epoch", AlertState.resolved_at - AlertState.detected_at)
            ).label("ttr_s"),
        )
        .where(AlertState.detected_at >= since)
        .group_by(AlertState.severity_at_pickup)
    ).all()

    results = []
    for row in rows:
        severity = row.severity or "unknown"
        goal = goals.get(severity)
        tta_minutes = round(row.tta_s / 60, 1) if row.tta_s else None
        ttr_minutes = round(row.ttr_s / 60, 1) if row.ttr_s else None

        results.append(
            {
                "severity": severity,
                "alerts": row.total,
                "acknowledged": row.acknowledged,
                "resolved": row.resolved,
                "mtta_minutes": tta_minutes,
                "mttr_minutes": ttr_minutes,
                "tta_target_minutes": goal.tta_target_minutes if goal else None,
                "ttr_target_minutes": goal.ttr_target_minutes if goal else None,
                "tta_met": (
                    tta_minutes <= goal.tta_target_minutes
                    if goal and tta_minutes is not None
                    else None
                ),
                "ttr_met": (
                    ttr_minutes <= goal.ttr_target_minutes
                    if goal and ttr_minutes is not None
                    else None
                ),
            }
        )

    results.sort(key=lambda r: SEVERITIES.index(r["severity"]) if r["severity"] in SEVERITIES else 99)
    return {
        "period_days": days,
        "by_severity": results,
        "handled_total": sum(r["alerts"] for r in results),
    }


def breaches(db: Session, days: int = 30, limit: int = 50) -> list[dict]:
    """Alertes ayant dépassé leur objectif de résolution.

    C'est la liste que le chef du NOC regarde en revue de service : pas un
    pourcentage, mais les cas précis, avec leur cause quand elle a été
    renseignée.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    goals = targets(db)
    if not goals:
        return []

    # L'objectif dépend de la gravité : on construit un CASE qui associe à
    # chaque ligne son seuil, plutôt que de faire une requête par gravité.
    target_case = case(
        *[
            (AlertState.severity_at_pickup == severity, goal.ttr_target_minutes * 60)
            for severity, goal in goals.items()
        ],
        else_=None,
    )
    elapsed = func.extract("epoch", AlertState.resolved_at - AlertState.detected_at)

    rows = db.execute(
        select(
            AlertState.alert_key,
            AlertState.node_name,
            AlertState.severity_at_pickup,
            AlertState.message_at_pickup,
            AlertState.detected_at,
            AlertState.resolved_at,
            AlertState.cause,
            elapsed.label("elapsed_s"),
            target_case.label("target_s"),
        )
        .where(
            AlertState.resolved_at.isnot(None),
            AlertState.detected_at >= since,
            elapsed > target_case,
        )
        .order_by((elapsed - target_case).desc())
        .limit(limit)
    ).all()

    return [
        {
            "alert_key": row.alert_key,
            "node_name": row.node_name,
            "severity": row.severity_at_pickup,
            "message": row.message_at_pickup,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            "cause": row.cause,
            "ttr_minutes": round(row.elapsed_s / 60, 1),
            "target_minutes": round(row.target_s / 60, 1),
            "overrun_minutes": round((row.elapsed_s - row.target_s) / 60, 1),
        }
        for row in rows
    ]


async def at_risk(db: Session) -> list[dict]:
    """Alertes EN COURS qui vont manquer leur objectif.

    Le plus utile des trois indicateurs de ce module : les deux autres
    racontent le passé, celui-ci permet encore d'agir. Calculé sur
    l'instantané — donc sur les alertes réellement actives — croisé avec les
    objectifs par gravité.
    """
    goals = targets(db)
    now = datetime.now(timezone.utc)
    alerts = await live_service.get_alerts()

    at_risk_rows = []
    for alert in alerts:
        goal = goals.get(alert.get("severity", ""))
        if goal is None or not alert.get("since"):
            continue
        try:
            since = datetime.fromisoformat(alert["since"])
        except (TypeError, ValueError):
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        elapsed_minutes = (now - since).total_seconds() / 60
        remaining = goal.ttr_target_minutes - elapsed_minutes
        # Seuil à 25 % du budget restant : assez tôt pour agir, assez tard
        # pour ne pas noyer l'écran d'alertes qui viennent de tomber.
        if remaining > goal.ttr_target_minutes * 0.25:
            continue

        at_risk_rows.append(
            {
                "alert_key": f"{alert['tool']}:{alert['ref']}",
                "tool": alert.get("tool"),
                "severity": alert.get("severity"),
                "message": alert.get("message"),
                "node_name": alert.get("node_name"),
                "since": alert.get("since"),
                "elapsed_minutes": round(elapsed_minutes, 1),
                "target_minutes": goal.ttr_target_minutes,
                "remaining_minutes": round(remaining, 1),
                "breached": remaining < 0,
            }
        )

    at_risk_rows.sort(key=lambda row: row["remaining_minutes"])
    return at_risk_rows
