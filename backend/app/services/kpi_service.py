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
from app.models import KpiDaily
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
async def live_summary(
    db: Session,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> dict:
    """Ce que montre le mur : l'état du parc à cette seconde, sur le
    périmètre demandé. Les incidents sont ceux d'iTop uniquement ; les
    alertes, celles des outils de supervision."""
    from app.services import geo_service

    nodes, alerts, incidents, _index = await geo_service.snapshot(db)
    scoped = bool(region or province or site or search)
    if scoped:
        nodes = geo_service.scope_nodes(nodes, region, province, site, search)
        ids = {node["id"] for node in nodes}
        alerts = [a for a in alerts if a.get("node_key") in ids]
        incidents = [i for i in incidents if i.get("node_key") in ids]
    summary = await live_service.fleet_summary(nodes, alerts + incidents)
    sites = await live_service.sites_summary(nodes, alerts)

    return {
        **summary,
        "scope": {"region": region, "province": province, "site": site, "search": search},
        "incidents_total": len(incidents),
        "incidents_critical": sum(1 for i in incidents if i.get("severity") == "critical"),
        "incidents_high": sum(1 for i in incidents if i.get("severity") == "high"),
        "incidents_unassigned": sum(
            1 for i in incidents if not (i.get("details") or {}).get("agent")
        ),
        "regions_total": len({geo_service.locality_of(n, "region") for n in nodes}),
        "sites_total": len(sites),
        # Un site est « en souffrance » dès qu'un de ses équipements est en
        # panne. Le seuil est volontairement bas : sur un réseau
        # administratif, un seul site coupé prive un ministère entier.
        "sites_impacted": sum(1 for site in sites if site["down"] > 0),
        "worst_sites": sites[:5],
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def alerts_by_severity(records: list[dict] | None = None) -> list[dict]:
    """Répartition des alertes actives par gravité.

    Toutes les gravités sont rendues, y compris à zéro : un histogramme dont
    les barres apparaissent et disparaissent au fil des alertes est illisible.
    """
    alerts = [
        alert for alert in (await live_service.get_alerts() if records is None else records)
        if alert.get("kind", "technical") == "technical"
    ]
    counts = {severity: 0 for severity in SEVERITIES}
    for alert in alerts:
        key = alert.get("severity", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return [{"severity": s, "count": counts[s]} for s in SEVERITIES]


async def alerts_by_tool(records: list[dict] | None = None) -> list[dict]:
    """D'où viennent les alertes.

    Utile au responsable du NOC : un outil qui produit 90 % des alertes est
    soit le seul à superviser quelque chose d'important, soit mal réglé et en
    train de noyer l'équipe. Les deux méritent d'être vus.
    """
    alerts = [
        alert for alert in (await live_service.get_alerts() if records is None else records)
        if alert.get("kind", "technical") == "technical"
    ]
    counts: dict[str, int] = {}
    for alert in alerts:
        counts[alert.get("tool", "?")] = counts.get(alert.get("tool", "?"), 0) + 1
    return [
        {"tool": tool, "count": count}
        for tool, count in sorted(counts.items(), key=lambda item: -item[1])
    ]


_ALERT_AGE_BUCKETS = (
    ("lt1h", "Moins d'1 heure", 60),
    ("lt24h", "1 à 24 heures", 1440),
    ("lt7d", "1 à 7 jours", 10080),
    ("lt30d", "7 à 30 jours", 43200),
    ("gt30d", "Plus de 30 jours", None),
)


async def alert_ages(records: list[dict] | None = None) -> list[dict]:
    """Depuis combien de temps durent les alertes en cours, par tranche.

    Lecture immédiate : beaucoup d'alertes récentes = incident en cours ;
    beaucoup d'alertes très anciennes = problèmes laissés sans suite.
    """
    alerts = [
        alert for alert in (await live_service.get_alerts() if records is None else records)
        if alert.get("kind", "technical") == "technical"
    ]
    now = datetime.now(timezone.utc)
    counts = {key: {"count": 0, "critical": 0} for key, _l, _m in _ALERT_AGE_BUCKETS}
    for alert in alerts:
        try:
            since = datetime.fromisoformat(alert.get("since") or "")
        except (TypeError, ValueError):
            continue
        minutes = (now - since).total_seconds() / 60
        for key, _label, limit in _ALERT_AGE_BUCKETS:
            if limit is None or minutes < limit:
                counts[key]["count"] += 1
                if alert.get("severity") == "critical":
                    counts[key]["critical"] += 1
                break
    return [{"key": key, "label": label, **counts[key]} for key, label, _m in _ALERT_AGE_BUCKETS]


async def hour_distribution(records: list[dict] | None = None) -> list[dict]:
    """Répartition horaire des alertes ouvertes, et part hors heures ouvrées.

    Répond à une question de dimensionnement d'astreinte : les pannes
    tombent-elles surtout quand personne n'est là ? Calculé sur les alertes
    ACTIVES uniquement — c'est une photographie, pas une statistique
    annuelle, et l'écran doit le dire.
    """
    alerts = [
        alert for alert in (await live_service.get_alerts() if records is None else records)
        if alert.get("kind", "technical") == "technical"
    ]
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
def rollup_key(
    region: str | None = None, province: str | None = None, site: str | None = None
) -> str | None:
    """Ligne de `kpi_daily` du périmètre : site, sinon province, sinon région,
    sinon la ligne « tout le réseau » (None)."""
    from collector.rollup import rollup_key as key

    if site:
        return site
    if province:
        return key("province", province)
    if region:
        return key("region", region)
    return None


def trend(
    db: Session,
    days: int = 30,
    site: str | None = None,
    start_at: date | datetime | None = None,
    end_at: date | datetime | None = None,
) -> list[dict]:
    """Évolution jour par jour sur la période demandée.

    `site=None` lit la ligne « tous sites confondus » et non la somme des
    sites : les équipements dont aucun outil ne connaît la localité
    n'appartiennent à aucun site, et les additionner en oublierait une partie.
    """
    start = (
        start_at.date() if isinstance(start_at, datetime) else start_at
    ) or (date.today() - timedelta(days=days))
    end = end_at.date() if isinstance(end_at, datetime) else end_at
    query = select(KpiDaily).where(KpiDaily.day >= start)
    if end is not None:
        query = query.where(KpiDaily.day < end)
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


def monthly_trend(
    db: Session, year: int, month: int, site: str | None = None
) -> list[dict]:
    start, end = month_bounds(year, month)
    return trend(db, site=site, start_at=start, end_at=end)


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
    previous_reliable = previous["days_with_data"] >= 15

    def delta(field: str) -> float | None:
        # Pas d'écart contre un mois lacunaire : il mesurerait les trous de
        # collecte, pas l'évolution. Nul ici plutôt qu'à chaque lecteur — le
        # rapport PDF l'imprimait sans regarder `previous_reliable`.
        a, b = current.get(field), previous.get(field)
        if a is None or b is None or not previous_reliable:
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
        # Même règle pour le mois de référence (les écarts sont alors nuls).
        "previous_reliable": previous_reliable,
    }


def sites_ranking(
    db: Session,
    days: int = 30,
    limit: int = 20,
    sort: str = "availability",
    start_at: date | datetime | None = None,
    end_at: date | datetime | None = None,
    sites: set[str] | None = None,
) -> list[dict]:
    """Sites classés par disponibilité ou par moyenne d'alertes actives.

    `sites` restreint le classement aux sites du périmètre courant. Les
    agrégats de région et de province (préfixe « @ ») n'en font jamais partie.
    """
    start = (
        start_at.date() if isinstance(start_at, datetime) else start_at
    ) or (date.today() - timedelta(days=days))
    end = end_at.date() if isinstance(end_at, datetime) else end_at
    avg_availability = func.avg(KpiDaily.fleet_availability_pct)
    avg_alerts = func.avg(KpiDaily.avg_alerts)
    ordering = (
        (avg_alerts.desc().nullslast(), func.avg(KpiDaily.avg_critical).desc().nullslast())
        if sort == "alerts"
        else (avg_availability.asc().nullslast(),)
    )
    conditions = [
        KpiDaily.day >= start,
        KpiDaily.site.isnot(None),
        ~KpiDaily.site.startswith("@"),
    ]
    if sites is not None:
        conditions.append(KpiDaily.site.in_(sorted(sites) or [""]))
    if end is not None:
        conditions.append(KpiDaily.day < end)
    rows = db.execute(
        select(
            KpiDaily.site,
            avg_availability.label("availability"),
            avg_alerts.label("alerts"),
            func.avg(KpiDaily.avg_critical).label("critical"),
            func.avg(KpiDaily.avg_down).label("down"),
            func.avg(KpiDaily.avg_nodes).label("nodes"),
        )
        .where(*conditions)
        .group_by(KpiDaily.site)
        .order_by(*ordering, KpiDaily.site.asc())
        .limit(limit)
    )
    return [
        {
            "site": row.site,
            "availability_pct": round(row.availability, 2) if row.availability is not None else None,
            "avg_alerts": round(row.alerts, 1) if row.alerts is not None else None,
            "avg_critical": round(row.critical, 1) if row.critical is not None else None,
            "avg_down": round(row.down, 1) if row.down is not None else None,
            "avg_nodes": round(row.nodes, 1) if row.nodes is not None else None,
        }
        for row in rows
    ]
