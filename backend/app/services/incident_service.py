"""
Incidents — iTop, et iTop seulement.

LA RÈGLE. Une ALERTE est un signal technique émis par un outil de
supervision (Zabbix, Centreon, NetXMS, Nagios, NSP). Un INCIDENT est un
ticket ouvert dans iTop : une prise en charge, avec un responsable, une
priorité et un engagement de délai. Le NOC ne fabrique pas d'incident à
partir d'une alerte ; il montre, pour chaque incident iTop, les alertes
techniques qui l'expliquent.

LES SLA SE MESURENT SUR LES INCIDENTS. Délai de prise en charge (TTO :
assignation - ouverture) et de résolution (TTR : résolution - ouverture),
comparés aux objectifs par gravité (`ops_sla_target`). Les tickets résolus
restent chez iTop et y sont lus à la demande (`fetch_incident_history`),
mis en cache quelques minutes, jamais recopiés.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.db.redis_client import get_store
from app.services import geo_service, history_service, live_service, sla_service
from integrations.base import ToolUnavailable
from integrations.normalize import severity as normalise_severity

logger = logging.getLogger(__name__)

_HISTORY_TTL_S = 300

# Tranches d'ancienneté des tickets ouverts (minutes) : au-delà d'un mois, un
# ticket « ouvert » est le plus souvent un ticket oublié.
AGE_BUCKETS = (
    ("lt4h", "< 4 h", 240),
    ("lt24h", "4 – 24 h", 1440),
    ("lt7d", "1 – 7 j", 10080),
    ("lt30d", "7 – 30 j", 43200),
    ("gt30d", "> 30 j", None),
)
# Ordre du circuit de traitement iTop, pour l'entonnoir.
STATUS_FLOW = ("new", "assigned", "escalated_tto", "escalated_ttr", "pending",
               "waiting_for_approval", "approved")

# Délai de résolution rapporté à l'objectif : la forme lisible d'une
# distribution quand les objectifs diffèrent selon la gravité.
TTR_RATIO_BUCKETS = (
    ("le50", "≤ 50 % de l'objectif", 0.5),
    ("le100", "50 – 100 %", 1.0),
    ("le200", "100 – 200 %", 2.0),
    ("gt200", "> 200 %", None),
)


def _age_bucket(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    for key, _label, limit in AGE_BUCKETS:
        if limit is None or minutes < limit:
            return key
    return None
GROUP_LEVELS = ("region", "province", "site", "node")


class IncidentsUnavailable(RuntimeError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _parse(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _minutes(start, end) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60.0, 1)


def _sla_state(severity: str, opened, assigned, resolved, goals: dict, now: datetime) -> dict:
    """État d'engagement d'un incident.

    Un incident encore ouvert dont l'objectif est DÉJÀ dépassé compte comme
    non tenu : attendre sa clôture pour le compter masquerait précisément
    les dépassements en cours.
    """
    goal = goals.get(severity)
    tto = _minutes(opened, assigned)
    ttr = _minutes(opened, resolved)
    elapsed = _minutes(opened, resolved or now)
    result = {
        "tto_minutes": tto,
        "ttr_minutes": ttr,
        "elapsed_minutes": elapsed,
        "tto_target_minutes": goal.tta_target_minutes if goal else None,
        "ttr_target_minutes": goal.ttr_target_minutes if goal else None,
        "ttr_status": "no_target",
    }
    if goal is None or goal.ttr_target_minutes is None or elapsed is None:
        return result
    if resolved is not None:
        result["ttr_status"] = "met" if ttr <= goal.ttr_target_minutes else "breached"
    elif elapsed > goal.ttr_target_minutes:
        result["ttr_status"] = "breached"
    else:
        result["ttr_status"] = "running"
        result["ttr_remaining_minutes"] = round(goal.ttr_target_minutes - elapsed, 1)
    return result


def _locate(record: dict, node: dict | None) -> dict:
    return {
        "node_key": node["id"] if node else None,
        "node_name": (node or {}).get("name") or record.get("node_name"),
        "site": (node or {}).get("site"),
        "province": (node or {}).get("province"),
        "region": (node or {}).get("region"),
    }


def _related_alerts(node: dict | None, alerts: list[dict], index) -> list[dict]:
    """Alertes techniques de l'équipement concerné — et de ses homonymes
    supervisés quand le CI iTop n'a pas pu être fusionné avec eux."""
    if node is None:
        return []
    node_ids = {node["id"]} | {other["id"] for other in index.namesakes(node)}
    related = [alert for alert in alerts if alert.get("node_key") in node_ids]
    related.sort(key=lambda a: a.get("since") or "", reverse=True)
    return related


def _incident_row(record: dict, node: dict | None, alerts: list[dict], index,
                  goals: dict, now: datetime) -> dict:
    details = record.get("details") or {}
    opened = _parse(record.get("since"))
    related = _related_alerts(node, alerts, index)
    return {
        "key": record["key"],
        "ref": record.get("ticket_ref") or record.get("ref"),
        "title": record.get("message"),
        "severity": record.get("severity", "unknown"),
        "status": details.get("status") or ("assigned" if record.get("acknowledged") else "new"),
        "priority": details.get("priority"),
        "class": details.get("class"),
        "organisation": details.get("organisation"),
        "caller": details.get("caller"),
        "agent": details.get("agent"),
        "team": details.get("team"),
        "opened_at": opened.isoformat() if opened else None,
        "assigned_at": details.get("assignment_date"),
        "age_minutes": _minutes(opened, now),
        **_locate(record, node),
        "cis": details.get("cis") or [],
        "related_alerts": len(related),
        "related_alerts_critical": sum(1 for a in related if a.get("severity") == "critical"),
        "sla": _sla_state(
            record.get("severity", "unknown"),
            opened,
            _parse(details.get("assignment_date")),
            _parse(details.get("resolution_date")),
            goals,
            now,
        ),
    }


async def list_incidents(
    db: Session,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict:
    """Incidents iTop ouverts, dans le périmètre.

    Les compteurs portent sur TOUS les incidents filtrés ; seule la liste
    est découpée en page (`offset`, `limit`).
    """
    nodes, alerts, incidents, index = await geo_service.snapshot(db)
    scoped_ids = (
        {n["id"] for n in geo_service.scope_nodes(nodes, region, province, site)}
        if (region or province or site)
        else None
    )
    goals = sla_service.targets(db)
    now = datetime.now(timezone.utc)
    needle = (search or "").strip().casefold()

    rows = []
    # Répartition de TOUS les tickets ouverts, avant le filtre de localité :
    # un écran filtré sur une région doit pouvoir dire combien de tickets il
    # ne montre pas, et pourquoi (ticket sans équipement identifiable).
    network_by_region: dict[str, int] = defaultdict(int)
    network_unlocated = 0
    status_counts: Counter = Counter()
    for record in incidents:
        node = index.by_id.get(record.get("node_key") or "")
        network_by_region[geo_service.locality_of(node or {}, "region")] += 1
        if node is None:
            network_unlocated += 1
        if scoped_ids is not None and (node is None or node["id"] not in scoped_ids):
            continue
        row = _incident_row(record, node, alerts, index, goals, now)
        if severity and row["severity"] != severity:
            continue
        if needle:
            haystack = " ".join(
                str(row.get(field) or "")
                for field in (
                    "ref", "title", "node_name", "site", "province", "region",
                    "organisation", "agent", "team", "caller",
                )
            ).casefold()
            if needle not in haystack:
                continue
        # Circuit de traitement compté AVANT le filtre de statut : filtrer
        # sur « Nouveau » ne doit pas faire disparaître les autres étapes.
        status_counts[row["status"]] += 1
        if status and row["status"] != status:
            continue
        rows.append(row)

    rank = {sev: i for i, sev in enumerate(SEVERITIES)}
    rows.sort(key=lambda r: r["opened_at"] or "", reverse=True)
    rows.sort(key=lambda r: rank.get(r["severity"], 99))
    return {
        "incidents": rows[offset:offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "truncated": len(rows) > offset + limit,
        "by_severity": {
            sev: sum(1 for r in rows if r["severity"] == sev) for sev in SEVERITIES
        },
        "unassigned": sum(1 for r in rows if not r["agent"]),
        "sla_breached": sum(1 for r in rows if r["sla"]["ttr_status"] == "breached"),
        "unlocated": sum(1 for r in rows if not r["node_key"]),
        # Formes de la file, sur TOUS les tickets filtrés (pas la seule page).
        "age_buckets": [
            {
                "key": key,
                "label": label,
                "count": sum(1 for r in rows if _age_bucket(r["age_minutes"]) == key),
                "breached": sum(
                    1 for r in rows
                    if _age_bucket(r["age_minutes"]) == key and r["sla"]["ttr_status"] == "breached"
                ),
            }
            for key, label, _limit in AGE_BUCKETS
        ],
        "by_status": sorted(
            ({"status": status, "count": count}
             for status, count in status_counts.items()),
            key=lambda item: (
                STATUS_FLOW.index(item["status"]) if item["status"] in STATUS_FLOW else 99
            ),
        ),
        "opened_last_hour": sum(
            1 for r in rows if r["age_minutes"] is not None and r["age_minutes"] <= 60
        ),
        "oldest_opened_at": min((r["opened_at"] for r in rows if r["opened_at"]), default=None),
        "scoped": scoped_ids is not None,
        "network_total": len(incidents),
        "network_unlocated": network_unlocated,
        "network_by_region": sorted(
            ({"region": name, "count": count} for name, count in network_by_region.items()),
            key=lambda item: (item["region"] == geo_service.UNKNOWN["region"], -item["count"]),
        ),
        "by_organisation": [
            {"organisation": name, "count": count}
            for name, count in Counter(r["organisation"] or "Organisation non renseignée"
                                       for r in rows).most_common(12)
        ],
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def get_incident(db: Session, key: str) -> dict | None:
    """Fiche d'incident : le ticket iTop ET ce que les outils disent de
    l'équipement concerné (état, sources, alertes techniques en cours)."""
    nodes, alerts, incidents, index = await geo_service.snapshot(db)
    record = next((i for i in incidents if i["key"] == key), None)
    if record is None:
        return None
    node = index.by_id.get(record.get("node_key") or "")
    row = _incident_row(record, node, alerts, index, sla_service.targets(db),
                        datetime.now(timezone.utc))
    supervised = [node, *index.namesakes(node)] if node else []
    return {
        **row,
        "itop": record.get("details") or {},
        "node": (
            {
                "id": node["id"],
                "name": node.get("name"),
                "hostname": node.get("hostname"),
                "ip": node.get("ip"),
                "state": node.get("state"),
                "measured_state": node.get("measured_state"),
                "node_type": node.get("node_type"),
                "organisation": node.get("organisation"),
                "latitude": node.get("latitude"),
                "longitude": node.get("longitude"),
            }
            if node
            else None
        ),
        "position": geo_service.position(node, nodes),
        # Vue des OUTILS : chaque équipement supervisé lié au CI, avec l'état
        # et la référence que chaque outil lui donne.
        "tool_views": [
            {
                "node_key": item["id"],
                "name": item.get("name"),
                "state": item.get("state"),
                "sources": item.get("sources") or {},
                "state_conflict": item.get("state_conflict") or {},
            }
            for item in supervised
        ],
        "alerts": _related_alerts(node, alerts, index)[:100],
    }


# ---------------------------------------------------------------------------
# SLA des incidents
# ---------------------------------------------------------------------------
async def _history(start: datetime, end: datetime) -> list[dict]:
    """Tickets iTop ouverts sur la période, avec cache court."""
    store = get_store()
    step = _HISTORY_TTL_S
    raw = f"itop-incidents|{int(start.timestamp()) // step}|{int(end.timestamp()) // step}"
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:32]
    cached = await store.get_history(fingerprint)
    if cached is not None:
        return cached
    try:
        client = history_service._client("itop")
    except history_service.HistoryUnavailable as exc:
        raise IncidentsUnavailable(exc.detail) from exc
    try:
        tickets = await client.fetch_incident_history(start, end)
    except ToolUnavailable as exc:
        raise IncidentsUnavailable(str(exc)) from exc
    serialised = [
        {
            **ticket,
            **{
                field: ticket[field].isoformat() if ticket.get(field) else None
                for field in (
                    "start_date", "assignment_date", "resolution_date", "close_date",
                    "last_update",
                )
            },
        }
        for ticket in tickets
    ]
    await store.set_history(fingerprint, serialised, _HISTORY_TTL_S)
    return serialised


async def incident_history(
    db: Session,
    days: int = 30,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """Historique des tickets iTop ouverts sur la période, clos ou non,
    du plus récent au plus ancien, découpé en pages.

    Lu chez iTop (cache court), jamais recopié : même source que les SLA.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    tickets = await _history(start, end)

    nodes, _alerts, _incidents, index = await geo_service.snapshot(db)
    scoped_ids = (
        {n["id"] for n in geo_service.scope_nodes(nodes, region, province, site)}
        if (region or province or site)
        else None
    )
    goals = sla_service.targets(db)
    needle = (search or "").strip().casefold()

    rows = []
    for ticket in tickets:
        ci = (ticket.get("cis") or [{}])[0] if ticket.get("cis") else {}
        node = index.find("itop", ci.get("ref"), ci.get("name"))
        if scoped_ids is not None and (node is None or node["id"] not in scoped_ids):
            continue
        sev = ticket.get("severity") or normalise_severity("itop", ticket.get("priority"))
        if severity and sev != severity:
            continue
        if status and ticket.get("status") != status:
            continue
        opened = _parse(ticket.get("start_date"))
        resolved = _parse(ticket.get("resolution_date"))
        row = {
            "key": f"itop:{ticket.get('id')}",
            "ref": ticket.get("ref"),
            "title": ticket.get("title"),
            "severity": sev,
            "status": ticket.get("status"),
            "organisation": ticket.get("organisation"),
            "agent": ticket.get("agent"),
            "team": ticket.get("team"),
            "opened_at": ticket.get("start_date"),
            "resolved_at": ticket.get("resolution_date"),
            "closed_at": ticket.get("close_date"),
            "node_key": node["id"] if node else None,
            "node_name": (node or {}).get("name") or ci.get("name"),
            "site": (node or {}).get("site"),
            "province": (node or {}).get("province"),
            "region": (node or {}).get("region"),
            "sla": _sla_state(
                sev, opened, _parse(ticket.get("assignment_date")), resolved, goals, end
            ),
        }
        if needle:
            haystack = " ".join(
                str(row.get(field) or "")
                for field in (
                    "ref", "title", "node_name", "site", "province", "region",
                    "organisation", "agent", "team",
                )
            ).casefold()
            if needle not in haystack:
                continue
        row["_node"] = node
        rows.append(row)

    rows.sort(key=lambda r: r["opened_at"] or "", reverse=True)
    page = rows[offset:offset + limit]
    # Position calculée pour la seule page servie : le repli sur le
    # barycentre du site parcourt tout le parc.
    for row in page:
        row["position"] = geo_service.position(row.pop("_node"), nodes)
    return {
        "incidents": page,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "days": days,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "resolved": sum(1 for r in rows if r["resolved_at"]),
        "sla_breached": sum(1 for r in rows if r["sla"]["ttr_status"] == "breached"),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 1)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 1)


def _empty_group() -> dict:
    return {
        "incidents": 0,
        "resolved": 0,
        "evaluated": 0,
        "breached": 0,
        "running": 0,
        "tto": [],
        "ttr": [],
    }


async def sla_by_group(
    db: Session,
    group_by: str = "region",
    days: int = 30,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
) -> dict:
    """Respect des engagements sur les incidents iTop, ventilé par région,
    province, site ou équipement.

    Taux = incidents tenus / incidents évalués. Sont évalués les incidents
    résolus dotés d'un objectif ET les incidents ouverts qui l'ont déjà
    dépassé. Un incident en cours encore dans les délais n'est pas compté :
    il peut encore être tenu.
    """
    if group_by not in GROUP_LEVELS:
        raise ValueError(f"Regroupement inconnu : {group_by}")
    end = end_at or datetime.now(timezone.utc)
    start = start_at or (end - timedelta(days=days))
    tickets = await _history(start, end)

    nodes, _alerts, _incidents, index = await geo_service.snapshot(db)
    scoped_ids = (
        {n["id"] for n in geo_service.scope_nodes(nodes, region, province, site)}
        if (region or province or site)
        else None
    )
    goals = sla_service.targets(db)
    now = datetime.now(timezone.utc)

    groups: dict[str, dict] = defaultdict(_empty_group)
    labels: dict[str, dict] = {}
    totals = _empty_group()
    by_severity: dict[str, dict] = defaultdict(_empty_group)
    # Semaine (lundi) d'OUVERTURE du ticket -> compteurs ; et délai de
    # résolution rapporté à l'objectif de sa gravité.
    weekly: dict[str, dict] = defaultdict(_empty_group)
    ratio_counts: dict[str, int] = {key: 0 for key, _l, _m in TTR_RATIO_BUCKETS}
    open_breached = 0

    for ticket in tickets:
        ci = (ticket.get("cis") or [{}])[0] if ticket.get("cis") else {}
        node = index.find("itop", ci.get("ref"), ci.get("name"))
        if scoped_ids is not None and (node is None or node["id"] not in scoped_ids):
            continue
        severity = ticket.get("severity") or normalise_severity("itop", ticket.get("priority"))
        state = _sla_state(
            severity,
            _parse(ticket.get("start_date")),
            _parse(ticket.get("assignment_date")),
            _parse(ticket.get("resolution_date")),
            goals,
            now,
        )
        if group_by == "node":
            key = node["id"] if node else "__none__"
            labels[key] = {
                "name": (node or {}).get("name") or ci.get("name") or "CI non rattaché",
                "site": (node or {}).get("site"),
                "province": (node or {}).get("province"),
                "region": (node or {}).get("region"),
            }
        else:
            key = geo_service.locality_of(node or {}, group_by)
            labels[key] = {"name": key}
        opened = _parse(ticket.get("start_date"))
        week = (
            (opened - timedelta(days=opened.weekday())).date().isoformat() if opened else None
        )
        goal = goals.get(severity)
        if state["ttr_minutes"] is not None and goal and goal.ttr_target_minutes:
            ratio = state["ttr_minutes"] / goal.ttr_target_minutes
            for bucket_key, _label, limit in TTR_RATIO_BUCKETS:
                if limit is None or ratio <= limit:
                    ratio_counts[bucket_key] += 1
                    break
        elif state["ttr_status"] == "breached":
            open_breached += 1
        targets_buckets = [groups[key], totals, by_severity[severity]]
        if week:
            targets_buckets.append(weekly[week])
        for bucket in targets_buckets:
            bucket["incidents"] += 1
            if ticket.get("resolution_date"):
                bucket["resolved"] += 1
            if state["ttr_status"] in ("met", "breached"):
                bucket["evaluated"] += 1
            if state["ttr_status"] == "breached":
                bucket["breached"] += 1
            if state["ttr_status"] == "running":
                bucket["running"] += 1
            if state["tto_minutes"] is not None:
                bucket["tto"].append(state["tto_minutes"])
            if state["ttr_minutes"] is not None:
                bucket["ttr"].append(state["ttr_minutes"])

    def finish(bucket: dict) -> dict:
        evaluated, breached = bucket["evaluated"], bucket["breached"]
        return {
            "incidents": bucket["incidents"],
            "resolved": bucket["resolved"],
            "evaluated": evaluated,
            "breached": breached,
            "running": bucket["running"],
            "compliance_pct": (
                round(100.0 * (evaluated - breached) / evaluated, 1) if evaluated else None
            ),
            "mtto_minutes": (
                round(sum(bucket["tto"]) / len(bucket["tto"]), 1) if bucket["tto"] else None
            ),
            "mttr_minutes": (
                round(sum(bucket["ttr"]) / len(bucket["ttr"]), 1) if bucket["ttr"] else None
            ),
            # Sur combien de tickets portent ces moyennes, et leur médiane :
            # un ticket sans date d'assignation (passé directement à
            # « résolu ») n'a pas de délai de prise en charge, et une moyenne
            # sur deux tickets ne se lit pas comme une moyenne sur deux cents.
            "tto_count": len(bucket["tto"]),
            "ttr_count": len(bucket["ttr"]),
            "median_tto_minutes": _median(bucket["tto"]),
            "median_ttr_minutes": _median(bucket["ttr"]),
        }

    rows = [
        {"key": key, **labels[key], **finish(bucket)}
        for key, bucket in groups.items()
    ]
    rows.sort(
        key=lambda r: (
            r["compliance_pct"] if r["compliance_pct"] is not None else 101,
            -r["breached"],
            str(r["name"]).lower(),
        )
    )
    return {
        "group_by": group_by,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "scope": {"region": region, "province": province, "site": site},
        "totals": finish(totals),
        "by_severity": [
            {"severity": sev, **finish(by_severity[sev])}
            for sev in SEVERITIES
            if sev in by_severity
        ],
        "rows": rows,
        "weekly": [
            {"week": week, **finish(bucket)} for week, bucket in sorted(weekly.items())
        ],
        "ttr_distribution": [
            {"key": key, "label": label, "count": ratio_counts[key]}
            for key, label, _limit in TTR_RATIO_BUCKETS
        ] + [{"key": "open_breached", "label": "Ouverts, déjà hors délai", "count": open_breached}],
        "targets": {
            sev: {"tto": goal.tta_target_minutes, "ttr": goal.ttr_target_minutes}
            for sev, goal in goals.items()
        },
    }
