"""
Indicateurs du NOC — deux horizons, deux sources.

  « MAINTENANT »  vient de l'instantané Redis. Combien d'équipements sont
                  en panne à cette seconde, quelles alertes sont ouvertes,
                  quels sites souffrent. Coût : une lecture Redis.

  « DEPUIS »      vient de la table `kpi_daily`, une ligne par jour et par
                  site écrite par le collecteur. Évolution sur trente jours,
                  comparaison mois par mois, tendance annuelle. Coût :
                  quelques dizaines de lignes lues.

CE QUI A DISPARU, et pourquoi c'est un progrès. L'ancien service calculait
tout en SQL sur `v_incident` et `metric_value` : six cent lignes de requêtes
sur des tables de plusieurs millions d'enregistrements, avec un cache Redis
pour rendre l'attente supportable. Le cache masquait le vrai problème —
recalculer sans cesse un agrégat de mois écoulés dont le résultat ne
changera plus jamais. Agréger une fois par jour et lire le résultat coûte
mille fois moins, et donne le même chiffre.

CE QU'ON A PERDU, dit franchement : `kpi_daily` ne permet plus de répondre à
« quel incident précis a causé la chute du 14 mars ». Cette question se pose
désormais à l'outil source, qui la connaît mieux que nous. C'est le
compromis assumé de l'architecture — voir ARCHITECTURE.md, §5.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import NOC_BUSINESS_HOURS, SEVERITIES
from app.models import AlertState, KpiDaily
from app.services import live_service

logger = logging.getLogger(__name__)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month // 12), (month % 12) + 1, 1)
    return start, end


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# ---------------------------------------------------------------------------
# « Maintenant »
# ---------------------------------------------------------------------------
async def live_summary() -> dict:
    """Ce que montre le mur : l'état du parc à cette seconde."""
    summary = await live_service.fleet_summary()
    sites = await live_service.sites_summary()

    return {
        **summary,
        "sites_total": len(sites),
        # Un site est « en souffrance » dès qu'un de ses équipements est en
        # panne. Le seuil est volontairement bas : sur un réseau
        # administratif, un seul site coupé prive un ministère entier.
        "sites_impacted": sum(1 for site in sites if site["down"] > 0),
        "worst_sites": sites[:5],
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def alerts_by_severity() -> list[dict]:
    """Répartition des alertes actives par gravité.

    Toutes les gravités sont rendues, y compris à zéro : un histogramme dont
    les barres apparaissent et disparaissent au fil des alertes est illisible.
    """
    alerts = await live_service.get_alerts()
    counts = {severity: 0 for severity in SEVERITIES}
    for alert in alerts:
        key = alert.get("severity", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return [{"severity": s, "count": counts[s]} for s in SEVERITIES]


async def alerts_by_tool() -> list[dict]:
    """D'où viennent les alertes.

    Utile au responsable du NOC : un outil qui produit 90 % des alertes est
    soit le seul à superviser quelque chose d'important, soit mal réglé et en
    train de noyer l'équipe. Les deux méritent d'être vus.
    """
    alerts = await live_service.get_alerts()
    counts: dict[str, int] = {}
    for alert in alerts:
        counts[alert.get("tool", "?")] = counts.get(alert.get("tool", "?"), 0) + 1
    return [
        {"tool": tool, "count": count}
        for tool, count in sorted(counts.items(), key=lambda item: -item[1])
    ]


async def hour_distribution() -> list[dict]:
    """Répartition horaire des alertes ouvertes, et part hors heures ouvrées.

    Répond à une question de dimensionnement d'astreinte : les pannes
    tombent-elles surtout quand personne n'est là ? Calculé sur les alertes
    ACTIVES uniquement — c'est une photographie, pas une statistique
    annuelle, et l'écran doit le dire.
    """
    alerts = await live_service.get_alerts()
    buckets = {hour: 0 for hour in range(24)}
    start_hour, end_hour = NOC_BUSINESS_HOURS
    off_hours = 0

    for alert in alerts:
        raw = alert.get("since")
        if not raw:
            continue
        try:
            at = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        hour = at.hour
        buckets[hour] += 1
        if not (start_hour <= hour < end_hour):
            off_hours += 1

    total = sum(buckets.values())
    return [
        {
            "hour": hour,
            "count": count,
            "off_hours": not (start_hour <= hour < end_hour),
            "share_pct": round(100.0 * count / total, 1) if total else 0.0,
        }
        for hour, count in buckets.items()
    ]


# ---------------------------------------------------------------------------
# « Depuis » — agrégats journaliers
# ---------------------------------------------------------------------------
def trend(db: Session, days: int = 30, site: str | None = None) -> list[dict]:
    """Évolution jour par jour sur la période demandée.

    `site=None` lit la ligne « tous sites confondus » et non la somme des
    sites : les équipements dont aucun outil ne connaît la localité
    n'appartiennent à aucun site, et les additionner en oublierait une partie.
    """
    since = date.today() - timedelta(days=days)
    query = select(KpiDaily).where(KpiDaily.day >= since)
    query = query.where(
        KpiDaily.site == site if site else KpiDaily.site.is_(None)
    )
    rows = db.execute(query.order_by(KpiDaily.day)).scalars()

    return [
        {
            "day": row.day.isoformat(),
            "nodes": row.avg_nodes,
            "up": row.avg_up,
            "down": row.avg_down,
            "degraded": row.avg_degraded,
            "alerts": row.avg_alerts,
            "critical": row.avg_critical,
            "availability_pct": row.fleet_availability_pct,
            # Nombre de cycles ayant réellement alimenté la moyenne du jour.
            # Rendu à l'écran : une journée à 12 échantillons au lieu de 288
            # est une journée où la collecte a été interrompue, et sa moyenne
            # ne se compare pas aux autres.
            "samples": row.samples,
        }
        for row in rows
    ]


def monthly_summary(db: Session, year: int, month: int, site: str | None = None) -> dict:
    """Bilan d'un mois, et écart avec le mois précédent."""
    def aggregate(y: int, m: int) -> dict:
        start, end = month_bounds(y, m)
        query = select(
            func.avg(KpiDaily.fleet_availability_pct),
            func.avg(KpiDaily.avg_alerts),
            func.avg(KpiDaily.avg_critical),
            func.avg(KpiDaily.avg_down),
            func.sum(KpiDaily.samples),
            func.count(KpiDaily.day),
        ).where(KpiDaily.day >= start, KpiDaily.day < end)
        query = query.where(
            KpiDaily.site == site if site else KpiDaily.site.is_(None)
        )
        availability, alerts, critical, down, samples, days = db.execute(query).one()
        return {
            "availability_pct": round(availability, 2) if availability is not None else None,
            "avg_alerts": round(alerts, 1) if alerts is not None else None,
            "avg_critical": round(critical, 1) if critical is not None else None,
            "avg_down": round(down, 1) if down is not None else None,
            "samples": int(samples or 0),
            "days_with_data": int(days or 0),
        }

    current = aggregate(year, month)
    previous = aggregate(*previous_month(year, month))

    def delta(field: str) -> float | None:
        a, b = current.get(field), previous.get(field)
        if a is None or b is None:
            return None
        return round(a - b, 2)

    return {
        "year": year,
        "month": month,
        "site": site,
        "current": current,
        "previous": previous,
        "delta": {
            "availability_pct": delta("availability_pct"),
            "avg_alerts": delta("avg_alerts"),
            "avg_critical": delta("avg_critical"),
        },
        # Un mois dont moins de la moitié des jours ont des données ne doit
        # pas être présenté comme comparable. L'écran l'affiche en grisé.
        "reliable": current["days_with_data"] >= 15,
    }


def sites_ranking(db: Session, days: int = 30, limit: int = 20) -> list[dict]:
    """Sites classés par disponibilité moyenne, les moins bons d'abord."""
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(
            KpiDaily.site,
            func.avg(KpiDaily.fleet_availability_pct).label("availability"),
            func.avg(KpiDaily.avg_alerts).label("alerts"),
            func.avg(KpiDaily.avg_down).label("down"),
            func.avg(KpiDaily.avg_nodes).label("nodes"),
        )
        .where(KpiDaily.day >= since, KpiDaily.site.isnot(None))
        .group_by(KpiDaily.site)
        .order_by(func.avg(KpiDaily.fleet_availability_pct).asc().nullslast())
        .limit(limit)
    )
    return [
        {
            "site": row.site,
            "availability_pct": round(row.availability, 2) if row.availability is not None else None,
            "avg_alerts": round(row.alerts, 1) if row.alerts is not None else None,
            "avg_down": round(row.down, 1) if row.down is not None else None,
            "avg_nodes": round(row.nodes, 1) if row.nodes is not None else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Causes — le seul historique que le NOC produit lui-même
# ---------------------------------------------------------------------------
def causes(db: Session, days: int = 90, limit: int = 15) -> list[dict]:
    """Causes retenues par les exploitants sur la période.

    C'est la donnée la plus précieuse du système, et la seule dont le NOC
    est propriétaire : aucun outil de supervision ne sait qu'une coupure
    venait d'un groupe électrogène à sec. Elle vient de `ops_alert_state`,
    renseignée à la clôture par le technicien.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(AlertState.cause, func.count().label("count"))
        .where(AlertState.cause.isnot(None), AlertState.resolved_at >= since)
        .group_by(AlertState.cause)
        .order_by(func.count().desc())
        .limit(limit)
    )
    results = [{"cause": row.cause, "count": row.count} for row in rows]
    total = sum(row["count"] for row in results)
    for row in results:
        row["share_pct"] = round(100.0 * row["count"] / total, 1) if total else 0.0
    return results


def resolution_times(db: Session, days: int = 30) -> dict:
    """Délais de prise en charge et de résolution, mesurés par le NOC.

    Calculés sur `ops_alert_state` et non sur les outils sources : le NOC
    mesure SON délai de réaction, ce qui est la question posée en revue de
    service. Le délai de détection de l'outil est une autre question, et
    elle appartient à l'outil.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    tta = db.execute(
        select(
            func.avg(
                func.extract("epoch", AlertState.acknowledged_at - AlertState.detected_at)
            )
        ).where(
            AlertState.acknowledged_at.isnot(None),
            AlertState.detected_at.isnot(None),
            AlertState.acknowledged_at >= since,
        )
    ).scalar()

    ttr = db.execute(
        select(
            func.avg(
                func.extract("epoch", AlertState.resolved_at - AlertState.detected_at)
            )
        ).where(
            AlertState.resolved_at.isnot(None),
            AlertState.detected_at.isnot(None),
            AlertState.resolved_at >= since,
        )
    ).scalar()

    handled = db.execute(
        select(func.count()).select_from(AlertState).where(AlertState.resolved_at >= since)
    ).scalar()

    return {
        "period_days": days,
        # En minutes : un délai d'astreinte se raisonne en minutes, et
        # afficher 14 400 secondes oblige chacun à diviser de tête.
        "mtta_minutes": round(tta / 60, 1) if tta else None,
        "mttr_minutes": round(ttr / 60, 1) if ttr else None,
        "handled_alerts": int(handled or 0),
    }
