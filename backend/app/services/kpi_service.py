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
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import (
    AVAILABILITY_THRESHOLDS,
    HEALTH_AVAILABILITY_DAYS,
    NOC_BUSINESS_HOURS,
    SEVERITIES,
)
from app.models import KpiDaily
from app.services import live_service

logger = logging.getLogger(__name__)


# Score « Santé réseau » (AM-03, KPI-26). PONDÉRATIONS PROPOSÉES PAR
# L'AUDIT, À VALIDER PAR LA DIRECTION : 40 % disponibilité, 20 % incidents,
# 20 % alertes critiques, 20 % couverture de supervision.
HEALTH_WEIGHTS = {"availability": 0.4, "incidents": 0.2, "alerts": 0.2, "coverage": 0.2}
# Chaque incident critique ouvert, chaque alerte critique non acquittée
# retire ce nombre de points à sa composante (plancher 0).
HEALTH_PENALTY = 10


def health_score(
    availability_pct: float | None,
    critical_incidents: int | None,
    critical_alerts: int,
    supervised: int,
    expected: int,
) -> dict:
    """Indice 0–100 et ses composantes, pour que la règle soit VISIBLE.

    La disponibilité est celle de KPI-01 (temps où les équipements répondent,
    HEALTH_AVAILABILITY_DAYS derniers jours), pas le parc instantané.
    Non évaluable sans disponibilité mesurée (aucun équipement supervisé).
    Une composante sans donnée (iTop indisponible : `critical_incidents`
    None) est écartée et les poids restants sont renormalisés ; la réponse
    le dit (`missing`).
    """
    components = {
        "availability": availability_pct,
        "incidents": (
            None if critical_incidents is None
            else max(0, 100 - HEALTH_PENALTY * critical_incidents)
        ),
        "alerts": max(0, 100 - HEALTH_PENALTY * critical_alerts),
        "coverage": round(100.0 * supervised / expected, 2) if expected else None,
    }
    missing = [name for name, value in components.items() if value is None]
    if components["availability"] is None:
        return {"score": None, "components": components, "missing": missing,
                "weights": HEALTH_WEIGHTS}
    weights = {k: w for k, w in HEALTH_WEIGHTS.items() if components[k] is not None}
    total = sum(weights.values())
    score = sum(components[k] * w for k, w in weights.items()) / total
    return {
        "score": round(score),
        "components": components,
        "missing": missing,
        "weights": HEALTH_WEIGHTS,
    }


def _naming(nodes: list[dict]) -> dict:
    import re

    from app.core.config import NODE_NAME_PATTERN

    try:
        pattern = re.compile(NODE_NAME_PATTERN, re.IGNORECASE)
    except re.error:
        logger.error("NODE_NAME_PATTERN invalide : %s", NODE_NAME_PATTERN)
        return {"naming_nonconforming": None, "naming_examples": []}
    off = [n.get("name") or "" for n in nodes if not pattern.match(n.get("name") or "")]
    return {
        "naming_nonconforming": len(off),
        "naming_examples": sorted(off)[:5],
        "naming_pattern": NODE_NAME_PATTERN,
    }


def _cmdb_coverage(nodes: list[dict]) -> dict:
    cmdb = [n for n in nodes if "itop" in (n.get("sources") or {})]
    covered = [
        n for n in cmdb
        if any(tool != "itop" for tool in (n.get("sources") or {}))
        and n.get("state") in ("up", "degraded", "down", "maintenance")
    ]
    return {
        "cmdb_nodes": len(cmdb),
        "cmdb_supervised": len(covered),
        "cmdb_coverage_pct": round(100.0 * len(covered) / len(cmdb), 1) if cmdb else None,
    }


# (périmètre) → (instant, disponibilité). Le score est affiché par tous les
# écrans : KPI-26 demande un calcul toutes les 5 min.
_health_cache: dict[tuple, tuple[float, float | None]] = {}


def _health_availability(
    db: Session, key: tuple, node_ids: set[str] | None
) -> tuple[float | None, str]:
    """Disponibilité du score Santé et sa base ; (None, "fleet") sans journal."""
    from app.services import availability_service

    now = time.monotonic()
    cached = _health_cache.get(key)
    if cached is None or now - cached[0] > 300:
        try:
            value = availability_service.ranking(
                db, "node", HEALTH_AVAILABILITY_DAYS, 1, node_ids=node_ids
            )["average_pct"]
        except availability_service.HistoryUnavailable:
            value = None
        if len(_health_cache) > 500:
            _health_cache.clear()
        cached = _health_cache[key] = (now, value)
    return cached[1], "period" if cached[1] is not None else "fleet"


def _delay_minutes(start: str | None, end: str | None) -> float | None:
    """Minutes entre deux horodatages ISO ; None si l'un manque ou si l'ordre
    est incohérent (acquittement daté avant la détection)."""
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    a = a if a.tzinfo else a.replace(tzinfo=timezone.utc)
    b = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
    minutes = (b - a).total_seconds() / 60
    return round(minutes, 1) if minutes >= 0 else None


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
    organisation: str | None = None,
    node_type: str | None = None,
) -> dict:
    """Ce que montre le mur : l'état du parc à cette seconde, sur le
    périmètre demandé. Les incidents sont ceux d'iTop uniquement ; les
    alertes, celles des outils de supervision."""
    from app.services import geo_service

    nodes, alerts, incidents, _index = await geo_service.snapshot(db)
    scoped = geo_service.is_scoped(region, province, site, organisation, node_type, search)
    if scoped:
        nodes = geo_service.scope_nodes(
            nodes, region, province, site, search, organisation, node_type
        )
        ids = {node["id"] for node in nodes}
        alerts = [a for a in alerts if a.get("node_key") in ids]
        incidents = [i for i in incidents if i.get("node_key") in ids]
    summary = await live_service.fleet_summary(nodes, alerts + incidents)
    sites = await live_service.sites_summary(nodes, alerts)
    from app.services import availability_service
    from app.services.alerts_service import _age_minutes, is_obsolete

    now = datetime.now(timezone.utc)
    technical = [a for a in alerts if a.get("kind", "technical") == "technical"]
    obsolete = [a for a in technical if is_obsolete(a, _age_minutes(a.get("since"), now))]
    obsolete_ids = {id(a) for a in obsolete}
    # AM-10 / KPI-05 : MTTA des alertes, sur les alertes actives acquittées
    # dont l'outil date l'acquittement (délai détection → prise en compte).
    ack_delays = [
        delay for a in technical
        if a.get("acknowledged") and a.get("acknowledged_at")
        and (delay := _delay_minutes(a.get("since"), a.get("acknowledged_at"))) is not None
    ]
    mtta_minutes = round(sum(ack_delays) / len(ack_delays), 1) if ack_delays else None
    mtta_count, mtta_basis = len(ack_delays), "active"
    # Le journal, dès qu'il porte des acquittements, remplace ce calcul : il
    # compte aussi les alertes résolues depuis.
    try:
        journal = availability_service.alert_response(
            db, 30, {n["id"] for n in nodes} if scoped else None
        )
        if journal["count"]:
            mtta_minutes, mtta_count = journal["mtta_minutes"], journal["count"]
            mtta_basis = "journal"
    except availability_service.HistoryUnavailable:
        pass
    # AM-12 / INC-23 : complétude de l'inventaire. Sans type ni site, un
    # équipement ne peut être ni regroupé, ni situé, ni comparé à un seuil.
    availability, basis = _health_availability(
        db, (region, province, site, search, organisation, node_type),
        {n["id"] for n in nodes} if scoped else None,
    )
    if basis == "fleet":
        # Journal indisponible ou vide : le parc instantané, en le disant.
        availability = summary["fleet_availability_pct"]
    complete = sum(1 for n in nodes if (n.get("node_type") or n.get("type")) and n.get("site"))
    itop = await live_service.source_stream("itop", "alerts")
    itop_stale = bool(itop.get("stale")) or not itop.get("collected_at")

    return {
        **summary,
        "scope": {
            "region": region, "province": province, "site": site, "search": search,
            "organisation": organisation, "node_type": node_type,
        },
        # Alertes non corrigées d'une source arrêtée : hors des compteurs.
        "alerts_unconfirmed": await _unconfirmed_count(
            {n["id"] for n in nodes} if scoped else None, nodes
        ),
        "frozen_sources": await live_service.frozen_sources(),
        # INC-13 : alertes actives non acquittées depuis plus de 30 jours,
        # signalées « à revoir » et comptées à part.
        "alerts_obsolete": len(obsolete),
        "alerts_obsolete_critical": sum(1 for a in obsolete if a.get("severity") == "critical"),
        # AM-03 : score « Santé réseau » et sa règle de calcul.
        "health": health_score(
            availability,
            # Incidents iTop : écartés si iTop n'est pas à jour.
            None if itop_stale else sum(1 for i in incidents if i.get("severity") == "critical"),
            sum(
                1 for a in technical
                if a.get("severity") == "critical"
                and not a.get("acknowledged")
                and id(a) not in obsolete_ids
            ),
            summary["nodes_supervised"],
            len(nodes) - summary["nodes_by_state"].get("maintenance", 0),
        ),
        "health_availability_basis": basis,
        "health_availability_days": HEALTH_AVAILABILITY_DAYS,
        "thresholds": AVAILABILITY_THRESHOLDS,
        "alerts_mtta_minutes": mtta_minutes,
        "alerts_mtta_count": mtta_count,
        # "journal" : 30 derniers jours, alertes closes comprises ;
        # "active" : seulement les alertes encore actives (journal vide).
        "alerts_mtta_basis": mtta_basis,
        "alerts_critical_unacknowledged": sum(
            1 for a in technical if a.get("severity") == "critical" and not a.get("acknowledged")
        ),
        # AM-11 / KPI-15 : couverture de supervision = équipements de la
        # CMDB iTop réellement observés par un outil ÷ équipements CMDB.
        **_cmdb_coverage(nodes),
        # INC-23 : noms hors convention SITE-RÔLE-NN (NODE_NAME_PATTERN).
        **_naming(nodes),
        "inventory_complete": complete,
        "inventory_complete_pct": round(100.0 * complete / len(nodes), 1) if nodes else None,
        "inventory_missing_type": sum(
            1 for n in nodes if not (n.get("node_type") or n.get("type"))
        ),
        "inventory_missing_site": sum(1 for n in nodes if not n.get("site")),
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


async def _unconfirmed_count(scoped_ids: set[str] | None, nodes: list[dict]) -> int:
    frozen = [a for a in await live_service.get_all_alerts() if a.get("frozen")]
    if scoped_ids is None:
        return len(frozen)
    refs = {f"{tool}:{ref}" for n in nodes for tool, ref in (n.get("sources") or {}).items()}
    return sum(1 for a in frozen if f"{a['tool']}:{a.get('node_ref')}" in refs)


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


async def hour_distribution(
    records: list[dict] | None = None, hours: int | None = None
) -> list[dict]:
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
    # INC-25 : seulement les alertes APPARUES dans la période choisie. Une
    # alerte de plus de 600 jours n'a rien à dire sur l'astreinte d'aujourd'hui.
    since_limit = (
        datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None
    )

    for alert in alerts:
        raw = alert.get("since")
        if not raw:
            continue
        try:
            at = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if since_limit is not None and at < since_limit:
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


def _weighted_availability():
    """Moyenne de plusieurs jours pondérée par le temps supervisé. Un bilan
    antérieur à ces colonnes est pondéré par ses équipements supervisés, sur
    une journée pleine."""
    weight = func.coalesce(
        KpiDaily.supervised_s,
        86400.0 * (
            func.coalesce(KpiDaily.avg_up, 0.0)
            + func.coalesce(KpiDaily.avg_degraded, 0.0)
            + func.coalesce(KpiDaily.avg_down, 0.0)
        ),
    )
    measured = KpiDaily.fleet_availability_pct.isnot(None)
    return (
        func.sum(KpiDaily.fleet_availability_pct * weight).filter(measured)
        / func.nullif(func.sum(weight).filter(measured), 0.0)
    )


def monthly_summary(db: Session, year: int, month: int, site: str | None = None) -> dict:
    """Bilan d'un mois, et écart avec le mois précédent.

    La disponibilité du mois est pondérée par le temps supervisé (INC-01) :
    un jour à moitié collecté pèse moitié moins."""
    def aggregate(y: int, m: int) -> dict:
        start, end = month_bounds(y, m)
        query = select(
            _weighted_availability(),
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
    avg_availability = _weighted_availability()
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
