from datetime import date
from typing import Optional

from sqlalchemy import Integer, and_, cast, desc, distinct, func, select
from sqlalchemy.orm import Session

from app.models.dimension import Cause, Locality, Node, Region
from app.models.incident import Incident
from app.models.kpi import KpiNodeMonthly as mv

# Bucket for incidents with no cause_id. Shown to users, so it is French like
# the rest of the dashboard labels.
UNCLASSIFIED_CATEGORY = "Non classé"

FRENCH_MONTHS = [
    "",
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
]

CRITICAL_AVAILABILITY_THRESHOLD = 95.0
RECURRENT_MIN_COUNT_DEFAULT = 3


def month_label(month: int, year: int) -> str:
    return f"{FRENCH_MONTHS[month]} {year}"


def month_start(month: int, year: int) -> date:
    return date(year, month, 1)


def prev_month(month: int, year: int) -> tuple[int, int]:
    return (12, year - 1) if month == 1 else (month - 1, year)


def shift_months(month: int, year: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) - offset
    return (total % 12) + 1, total // 12


def _month_aggregates(db: Session, period_start: date):
    """Whole-network aggregates over the materialized view for one month."""
    return (
        db.execute(
            select(
                func.coalesce(func.sum(mv.total_incidents), 0).label("total_incidents"),
                func.coalesce(func.sum(mv.resolved), 0).label("resolved"),
                func.coalesce(func.avg(mv.avg_mttr), 0).label("avg_mttr"),
                func.coalesce(func.avg(mv.availability_pct), 100).label(
                    "availability_pct"
                ),
            ).where(mv.month == period_start)
        )
        .mappings()
        .first()
    )


def get_summary(db: Session, month: int, year: int) -> dict:
    period_start = month_start(month, year)

    row = (
        db.execute(
            select(
                func.coalesce(func.sum(mv.total_incidents), 0).label("total_incidents"),
                func.coalesce(func.sum(mv.resolved), 0).label("resolved"),
                func.coalesce(func.avg(mv.avg_mttr), 0).label("avg_mttr"),
                func.coalesce(func.avg(mv.availability_pct), 100).label(
                    "availability_pct"
                ),
                func.count(distinct(mv.locality_id))
                .filter(mv.availability_pct < CRITICAL_AVAILABILITY_THRESHOLD)
                .label("critical_localities"),
                func.count()
                .filter(mv.total_incidents >= RECURRENT_MIN_COUNT_DEFAULT)
                .label("recurrent_nodes"),
            ).where(mv.month == period_start)
        )
        .mappings()
        .first()
    )

    off_hours = db.execute(
        select(func.count())
        .select_from(Incident)
        .where(
            Incident.shift == "auto",
            func.date_trunc("month", Incident.detected_at) == period_start,
        )
    ).scalar()

    total_incidents = int(row["total_incidents"])
    resolved = int(row["resolved"])
    open_incidents = total_incidents - resolved
    resolution_rate = (
        round((resolved / total_incidents * 100), 1) if total_incidents else 0.0
    )

    pm_month, pm_year = prev_month(month, year)
    prev_row = _month_aggregates(db, month_start(pm_month, pm_year))

    kpi = {
        "total_incidents": total_incidents,
        "resolved": resolved,
        "open": open_incidents,
        "resolution_rate_pct": resolution_rate,
        "avg_mttr_minutes": round(float(row["avg_mttr"]), 1),
        "network_availability_pct": round(float(row["availability_pct"]), 1),
        "critical_localities": int(row["critical_localities"]),
        "recurrent_nodes": int(row["recurrent_nodes"]),
        "off_hours_detected": int(off_hours or 0),
    }

    vs_previous_month = {
        "incidents_delta": total_incidents - int(prev_row["total_incidents"]),
        "availability_delta": round(
            float(row["availability_pct"]) - float(prev_row["availability_pct"]), 1
        ),
    }

    return {
        "period": {"month": month, "year": year, "label": month_label(month, year)},
        "kpi": kpi,
        "vs_previous_month": vs_previous_month,
    }


def get_comparison(
    db: Session, month: int, year: int, offsets: tuple[int, ...] = (1, 3)
) -> dict:
    """Spec P2 « Comparaison périodes » — N vs N-1 and N vs N-3 months."""
    current = get_summary(db, month, year)
    comparisons = []
    for offset in offsets:
        m, y = shift_months(month, year, offset)
        past = get_summary(db, m, y)
        deltas = {
            key: round(current["kpi"][key] - past["kpi"][key], 1)
            for key in (
                "total_incidents",
                "resolved",
                "resolution_rate_pct",
                "avg_mttr_minutes",
                "network_availability_pct",
            )
        }
        comparisons.append(
            {
                "offset_months": offset,
                "period": past["period"],
                "kpi": past["kpi"],
                "deltas": deltas,
            }
        )
    return {
        "period": current["period"],
        "kpi": current["kpi"],
        "comparisons": comparisons,
    }


def get_localities(db: Session, month: int, year: int, limit: int = 10) -> list[dict]:
    period_start = month_start(month, year)
    rows = (
        db.execute(
            select(
                mv.locality_id,
                mv.locality,
                mv.region,
                Locality.latitude,
                Locality.longitude,
                func.sum(mv.total_incidents).label("total_incidents"),
                func.sum(mv.resolved).label("resolved"),
                func.avg(mv.avg_mttr).label("avg_mttr"),
                func.avg(mv.availability_pct).label("availability_pct"),
            )
            .join(Locality, Locality.id == mv.locality_id)
            .where(mv.month == period_start)
            .group_by(
                mv.locality_id,
                mv.locality,
                mv.region,
                Locality.latitude,
                Locality.longitude,
            )
            .order_by(desc("total_incidents"))
            .limit(limit)
        )
        .mappings()
        .all()
    )

    return [
        {
            "locality_id": r["locality_id"],
            "locality": r["locality"],
            "region": r["region"],
            "latitude": float(r["latitude"]) if r["latitude"] is not None else None,
            "longitude": float(r["longitude"]) if r["longitude"] is not None else None,
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "avg_mttr": (
                round(float(r["avg_mttr"]), 1) if r["avg_mttr"] is not None else None
            ),
            "availability_pct": (
                round(float(r["availability_pct"]), 1)
                if r["availability_pct"] is not None
                else None
            ),
        }
        for r in rows
    ]


def get_localities_map(db: Session, month: int, year: int) -> list[dict]:
    """Every locality with a coordinate, for the map — including ones with zero
    incidents this month (unlike get_localities, which only returns localities
    that have activity in mv_kpi_node_monthly)."""
    period_start = month_start(month, year)
    rows = (
        db.execute(
            select(
                Locality.id.label("locality_id"),
                Locality.name.label("locality"),
                Region.name.label("region"),
                Locality.latitude,
                Locality.longitude,
                func.coalesce(func.sum(mv.total_incidents), 0).label("total_incidents"),
                func.coalesce(func.sum(mv.resolved), 0).label("resolved"),
                func.avg(mv.avg_mttr).label("avg_mttr"),
                func.coalesce(func.avg(mv.availability_pct), 100).label(
                    "availability_pct"
                ),
            )
            .select_from(Locality)
            .join(Region, Region.id == Locality.region_id)
            .outerjoin(
                mv, and_(mv.locality_id == Locality.id, mv.month == period_start)
            )
            .where(Locality.latitude.isnot(None), Locality.longitude.isnot(None))
            .group_by(
                Locality.id,
                Locality.name,
                Region.name,
                Locality.latitude,
                Locality.longitude,
            )
            .order_by(desc("total_incidents"))
        )
        .mappings()
        .all()
    )
    severity_counts = get_severity_counts_by_locality(db, period_start)

    return [
        {
            "locality_id": r["locality_id"],
            "locality": r["locality"],
            "region": r["region"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "avg_mttr": (
                round(float(r["avg_mttr"]), 1) if r["avg_mttr"] is not None else None
            ),
            "availability_pct": round(float(r["availability_pct"]), 1),
            "by_severity": severity_counts.get(r["locality_id"], {}),
        }
        for r in rows
    ]


def get_severity_counts_by_locality(
    db: Session, period_start: date
) -> dict[int, dict[str, int]]:
    """{locality_id: {severity: incident count}} for one month.

    Month-scoped, like every other figure the map carries, so the period picker
    drives this page the same way it drives the rest of the dashboard. An
    earlier version counted what was open *right now* instead, which read
    sensibly on its own but left the picker apparently broken: the payload
    reloaded on every month change and nothing on screen moved.

    Served alongside the monthly aggregates so severity filtering stays a
    client-side sum rather than a request per toggle.
    """
    rows = (
        db.execute(
            select(
                Node.locality_id,
                Incident.severity,
                func.count().label("n"),
            )
            .select_from(Incident)
            .join(Node, Incident.node_id == Node.id)
            .where(func.date_trunc("month", Incident.detected_at) == period_start)
            .group_by(Node.locality_id, Incident.severity)
        )
        .mappings()
        .all()
    )
    counts: dict[int, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["locality_id"], {})[r["severity"]] = int(r["n"])
    return counts


def get_nodes(
    db: Session,
    month: int,
    year: int,
    locality_id: Optional[int] = None,
    limit: int = 10,
) -> list[dict]:
    period_start = month_start(month, year)
    stmt = select(
        mv.node_id,
        mv.code,
        mv.name,
        mv.source_tool,
        mv.locality,
        mv.total_incidents,
        mv.resolved,
        mv.avg_mttr,
        mv.availability_pct,
    ).where(mv.month == period_start)
    if locality_id is not None:
        stmt = stmt.where(mv.locality_id == locality_id)
    stmt = stmt.order_by(mv.total_incidents.desc()).limit(limit)

    rows = db.execute(stmt).mappings().all()

    return [
        {
            "node_id": r["node_id"],
            "code": r["code"],
            "name": r["name"],
            "locality": r["locality"],
            "source_tool": r["source_tool"],
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "avg_mttr": (
                round(float(r["avg_mttr"]), 1) if r["avg_mttr"] is not None else None
            ),
            "availability_pct": (
                round(float(r["availability_pct"]), 1)
                if r["availability_pct"] is not None
                else None
            ),
        }
        for r in rows
    ]


# A node is "flapping" when it produces many short episodes rather than one
# long outage. Both shapes land in the recurrent list with the same incident
# count, and they call for opposite responses: a flapping link needs the link
# fixed, a chronic one needs someone sent to the site. 15 minutes is well above
# a poll interval (so a genuine short outage is not mislabelled) and well below
# any outage worth dispatching for.
FLAPPING_MAX_AVG_MINUTES = 15


def get_recurrent_nodes(
    db: Session, month: int, year: int, min_count: int = 3
) -> list[dict]:
    period_start = month_start(month, year)
    rows = (
        db.execute(
            select(mv.node_id, mv.code, mv.name, mv.locality, mv.total_incidents)
            .where(mv.month == period_start, mv.total_incidents >= min_count)
            .order_by(mv.total_incidents.desc())
        )
        .mappings()
        .all()
    )
    if not rows:
        return []

    # Mean episode length per node. An unresolved incident is measured to now,
    # the same convention mv_kpi_node_monthly uses for availability — otherwise
    # a node that is simply still down would read as a 0-minute episode.
    ongoing = func.extract("epoch", func.now() - Incident.detected_at) / 60
    durations = {
        r["node_id"]: r["avg_minutes"]
        for r in db.execute(
            select(
                Incident.node_id,
                func.avg(func.coalesce(Incident.downtime_minutes, ongoing)).label(
                    "avg_minutes"
                ),
            )
            .where(
                Incident.node_id.in_([r["node_id"] for r in rows]),
                func.date_trunc("month", Incident.detected_at) == period_start,
            )
            .group_by(Incident.node_id)
        )
        .mappings()
        .all()
    }

    result = []
    for r in rows:
        avg_minutes = durations.get(r["node_id"])
        avg_minutes = round(float(avg_minutes), 1) if avg_minutes is not None else None
        result.append(
            {
                "node_id": r["node_id"],
                "code": r["code"],
                "name": r["name"],
                "locality": r["locality"],
                "total_incidents": int(r["total_incidents"]),
                "avg_duration_minutes": avg_minutes,
                "flapping": (
                    avg_minutes is not None and avg_minutes < FLAPPING_MAX_AVG_MINUTES
                ),
            }
        )
    return result


def get_trend(db: Session, month: int, year: int, months: int = 6) -> list[dict]:
    points = []
    for offset in range(months - 1, -1, -1):
        m, y = shift_months(month, year, offset)
        row = _month_aggregates(db, month_start(m, y))
        points.append(
            {
                "month": m,
                "year": y,
                "label": month_label(m, y),
                "total_incidents": int(row["total_incidents"]),
                "resolved": int(row["resolved"]),
                "avg_mttr": round(float(row["avg_mttr"]), 1),
                "availability_pct": round(float(row["availability_pct"]), 1),
            }
        )
    return points


def get_hour_distribution(db: Session, month: int, year: int) -> list[dict]:
    period_start = month_start(month, year)
    hour = cast(func.extract("hour", Incident.detected_at), Integer).label("hour")
    rows = (
        db.execute(
            select(hour, func.count().label("total_incidents"))
            .where(func.date_trunc("month", Incident.detected_at) == period_start)
            .group_by(hour)
        )
        .mappings()
        .all()
    )

    counts = {int(r["hour"]): int(r["total_incidents"]) for r in rows}
    return [{"hour": h, "total_incidents": counts.get(h, 0)} for h in range(24)]


def get_latest_data_month(db: Session) -> tuple[int, int]:
    latest = db.execute(select(func.max(mv.month))).scalar()
    if latest is None:
        today = date.today()
        return today.month, today.year
    return latest.month, latest.year


def get_cause_breakdown(db: Session, month: int, year: int) -> list[dict]:
    """Incident counts per cause category for one month.

    Outer-joined on purpose. Incidents collected from the supervision tools
    carry no cause — none of those APIs reports one, and nothing classifies
    them afterwards — so an inner join silently drops every one of them and
    leaves the chart empty for any month that was not seeded by hand. Counting
    them under UNCLASSIFIED_CATEGORY keeps the breakdown summing to the
    month's real incident total, and makes the size of the unclassified slice
    the visible measure of how much classification is still missing.
    """
    period_start = month_start(month, year)
    category = func.coalesce(Cause.category, UNCLASSIFIED_CATEGORY).label("category")
    rows = (
        db.execute(
            select(
                category,
                func.count(Incident.id).label("total_incidents"),
                func.avg(Incident.mttr_minutes).label("avg_mttr"),
            )
            .select_from(Incident)
            .outerjoin(Cause, Incident.cause_id == Cause.id)
            .where(func.date_trunc("month", Incident.detected_at) == period_start)
            .group_by(category)
            .order_by(desc("total_incidents"))
        )
        .mappings()
        .all()
    )

    return [
        {
            "category": r["category"],
            "total_incidents": int(r["total_incidents"]),
            "avg_mttr": (
                round(float(r["avg_mttr"]), 1) if r["avg_mttr"] is not None else None
            ),
        }
        for r in rows
    ]


SLA_TARGETS = {
    "core_availability": ("Disponibilité Cœur de Réseau", 99.5),
    "node_availability": ("Disponibilité Nœuds d'Accès", 95.0),
    "resolution_rate": ("Taux de Résolution < 4h", 80.0),
}


def get_sla(db: Session, month: int, year: int) -> dict:
    summary = get_summary(db, month, year)
    kpi = summary["kpi"]

    period_start = month_start(month, year)
    core_availability_raw = db.execute(
        select(func.avg(mv.availability_pct)).where(
            mv.month == period_start,
            mv.source_tool.in_(("centreon", "netxms", "nsp")),
        )
    ).scalar()
    core_availability = (
        round(float(core_availability_raw), 1)
        if core_availability_raw is not None
        else kpi["network_availability_pct"]
    )

    values = {
        "core_availability": core_availability,
        "node_availability": kpi["network_availability_pct"],
        "resolution_rate": kpi["resolution_rate_pct"],
    }

    indicators = []
    for key, (label, target) in SLA_TARGETS.items():
        value = values[key]
        indicators.append(
            {
                "metric": label,
                "value": value,
                "target": target,
                "status": "met" if value >= target else "not_met",
            }
        )

    return {
        "period": summary["period"],
        "indicators": indicators,
    }


def get_locality_nodes(
    db: Session, locality_id: int, month: int, year: int
) -> Optional[dict]:
    period_start = month_start(month, year)

    locality_row = (
        db.execute(
            select(
                Locality.id.label("locality_id"),
                Locality.name.label("locality"),
                Region.name.label("region"),
            )
            .join(Region, Locality.region_id == Region.id)
            .where(Locality.id == locality_id)
        )
        .mappings()
        .first()
    )
    if locality_row is None:
        return None

    total_incidents = func.coalesce(mv.total_incidents, 0).label("total_incidents")
    rows = (
        db.execute(
            select(
                Node.id.label("node_id"),
                Node.code,
                Node.name,
                Node.node_type,
                Node.source_tool,
                Node.is_active,
                total_incidents,
                func.coalesce(mv.resolved, 0).label("resolved"),
                mv.avg_mttr,
                func.coalesce(mv.availability_pct, 100).label("availability_pct"),
            )
            .select_from(Node)
            .outerjoin(mv, and_(mv.node_id == Node.id, mv.month == period_start))
            .where(Node.locality_id == locality_id)
            .order_by(desc("total_incidents"), Node.code)
        )
        .mappings()
        .all()
    )

    nodes = [
        {
            "node_id": r["node_id"],
            "code": r["code"],
            "name": r["name"],
            "node_type": r["node_type"],
            "source_tool": r["source_tool"],
            "is_active": r["is_active"],
            "total_incidents": int(r["total_incidents"]),
            "resolved": int(r["resolved"]),
            "open": int(r["total_incidents"]) - int(r["resolved"]),
            "avg_mttr": (
                round(float(r["avg_mttr"]), 1) if r["avg_mttr"] is not None else None
            ),
            "availability_pct": round(float(r["availability_pct"]), 1),
        }
        for r in rows
    ]

    return {
        "locality_id": locality_row["locality_id"],
        "locality": locality_row["locality"],
        "region": locality_row["region"],
        "period": {"month": month, "year": year, "label": month_label(month, year)},
        "nodes": nodes,
    }