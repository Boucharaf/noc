"""
Disponibilité sur la durée, lue dans le journal historique.

Le collecteur écrit (collector/history.py) ; ce module lit `hist_state` et
`hist_alert` pour répondre aux questions que l'instantané ne sait pas
traiter : disponibilité d'un équipement ou d'un lien sur 30 jours ou sur
l'année, nombre de pannes, durée moyenne d'une panne, MTTR technique des
alertes, classement des moins disponibles.

RÈGLES DE CALCUL — les mêmes partout :
  * disponibilité = temps « en service » ÷ (temps observé − maintenance) ;
    dégradé, inconnu, hors service ne sont jamais « disponibles » ;
  * le temps NON OBSERVÉ (collecteur arrêté, outil muet plus de trois
    cycles, avant le début du journal) est publié à part et n'entre pas dans
    le calcul : il ne compte ni pour ni contre ;
  * une panne = une période « hors service » ; sa durée n'est comptée dans
    le MTTR équipement qu'une fois close.

Si les tables n'existent pas encore (schéma non rejoué), les fonctions
lèvent HistoryUnavailable et la route répond « historique indisponible »
au lieu d'une erreur : rien d'autre dans le NOC n'en dépend.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import COLLECT_INTERVAL_S
from app.models import HistAlert, HistState

logger = logging.getLogger(__name__)

INTERVAL = timedelta(seconds=COLLECT_INTERVAL_S)
MAX_GAP = 3 * INTERVAL
_MAX_SEGMENTS = 400


class HistoryUnavailable(RuntimeError):
    """Journal absent (schéma non appliqué) ou base injoignable."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _end(row, now: datetime) -> datetime:
    """Même règle que collector/history.effective_end."""
    if row.ended_at is not None:
        return _aware(row.ended_at)
    seen = _aware(row.last_seen_at)
    return now if now - seen <= MAX_GAP else seen + INTERVAL


def _clip(start: datetime, end: datetime, lo: datetime, hi: datetime):
    start, end = max(start, lo), min(end, hi)
    return (start, end) if end > start else None


def summarise(periods: list, lo: datetime, hi: datetime, now: datetime,
              with_segments: bool = False) -> dict:
    """Disponibilité, pannes et temps par état d'un sujet sur [lo, hi)."""
    seconds: dict[str, float] = defaultdict(float)
    segments: list[dict] = []
    downs: list[float] = []
    down_count = 0
    for row in sorted(periods, key=lambda p: _aware(p.started_at)):
        start, end = _aware(row.started_at), _end(row, now)
        clipped = _clip(start, end, lo, hi)
        if clipped is None:
            continue
        seconds[row.state] += (clipped[1] - clipped[0]).total_seconds()
        if row.state == "down":
            if start >= lo:
                down_count += 1
            if row.ended_at is not None and start >= lo:
                downs.append((end - start).total_seconds())
        if with_segments:
            if segments and segments[-1]["state"] == row.state and \
                    segments[-1]["end"] == clipped[0].isoformat():
                segments[-1]["end"] = clipped[1].isoformat()
            else:
                segments.append({
                    "state": row.state,
                    "start": clipped[0].isoformat(),
                    "end": clipped[1].isoformat(),
                })
    observed = sum(seconds.values())
    measured = observed - seconds["maintenance"]
    window = (hi - lo).total_seconds()
    result = {
        "availability_pct": round(100.0 * seconds["up"] / measured, 3) if measured > 0 else None,
        "observed_pct": round(100.0 * observed / window, 1) if window else None,
        "minutes": {state: round(value / 60, 1) for state, value in seconds.items() if value},
        "unobserved_minutes": round(max(0.0, window - observed) / 60, 1),
        "down_count": down_count,
        "mttr_minutes": round(sum(downs) / len(downs) / 60, 1) if downs else None,
        "mtbf_hours": (
            round(seconds["up"] / down_count / 3600, 1) if down_count else None
        ),
    }
    if with_segments:
        result["segments"] = segments[-_MAX_SEGMENTS:]
    return result


def _window(days: int) -> tuple[datetime, datetime, datetime]:
    now = _now()
    return now - timedelta(days=days), now, now


def _overlapping(query, model_start, model_end, lo, hi):
    return query.filter(model_start < hi, or_(model_end.is_(None), model_end > lo))


def node_history(db: Session, node_id: str, days: int = 30) -> dict:
    """Historique d'un équipement : son état, ses liens, ses alertes."""
    lo, hi, now = _window(days)
    try:
        periods = _overlapping(
            db.query(HistState).filter(HistState.node_id == node_id),
            HistState.started_at, HistState.ended_at, lo, hi,
        ).all()
        alerts = _overlapping(
            db.query(HistAlert).filter(
                HistAlert.node_id == node_id, HistAlert.kind == "technical"
            ),
            HistAlert.opened_at, HistAlert.closed_at, lo, hi,
        ).order_by(HistAlert.opened_at.desc()).all()
        since = db.query(func.min(HistState.started_at)).filter(
            HistState.node_id == node_id
        ).scalar()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Journal historique illisible : %s", exc)
        raise HistoryUnavailable(str(exc)) from exc

    node_periods = [p for p in periods if p.subject_kind == "node"]
    links: dict[str, list] = defaultdict(list)
    for period in periods:
        if period.subject_kind == "link":
            links[period.subject_id].append(period)

    closed = [
        (_aware(a.closed_at) - _aware(a.opened_at)).total_seconds()
        for a in alerts if a.closed_at is not None and _aware(a.closed_at) >= lo
    ]
    by_severity: dict[str, int] = defaultdict(int)
    for alert in alerts:
        if _aware(alert.opened_at) >= lo:
            by_severity[alert.severity] += 1
    return {
        "available": True,
        "days": days,
        "since": _aware(since).isoformat() if since else None,
        "node": summarise(node_periods, lo, hi, now, with_segments=True)
        if node_periods else None,
        "links": sorted(
            (
                {
                    "subject_id": subject_id,
                    "name": rows[-1].name,
                    "state": max(rows, key=lambda p: _aware(p.started_at)).state,
                    **summarise(rows, lo, hi, now),
                }
                for subject_id, rows in links.items()
            ),
            key=lambda item: (
                item["availability_pct"] if item["availability_pct"] is not None else 101
            ),
        ),
        "alerts": {
            "opened": sum(by_severity.values()),
            "by_severity": dict(by_severity),
            "closed": len(closed),
            "mttr_minutes": round(sum(closed) / len(closed) / 60, 1) if closed else None,
            "recent": [
                {
                    "key": a.alert_key,
                    "tool": a.tool,
                    "severity": a.severity,
                    "message": a.message,
                    "opened_at": _aware(a.opened_at).isoformat(),
                    "closed_at": _aware(a.closed_at).isoformat() if a.closed_at else None,
                }
                for a in alerts[:20]
            ],
        },
    }


def ranking(db: Session, kind: str = "node", days: int = 30, limit: int = 20,
            region: str | None = None, province: str | None = None,
            site: str | None = None) -> dict:
    """Équipements (ou liens) les moins disponibles sur la période.

    Le périmètre porte sur la localité ENREGISTRÉE avec chaque période : un
    équipement déplacé reste compté là où il était."""
    lo, hi, now = _window(days)
    try:
        query = _overlapping(
            db.query(HistState).filter(HistState.subject_kind == kind),
            HistState.started_at, HistState.ended_at, lo, hi,
        )
        if region:
            query = query.filter(HistState.region == region)
        if province:
            query = query.filter(HistState.province == province)
        if site:
            query = query.filter(HistState.site == site)
        periods = query.all()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Journal historique illisible : %s", exc)
        raise HistoryUnavailable(str(exc)) from exc

    grouped: dict[str, list] = defaultdict(list)
    for period in periods:
        grouped[period.subject_id].append(period)
    rows = []
    for subject_id, items in grouped.items():
        summary = summarise(items, lo, hi, now)
        if summary["availability_pct"] is None:
            continue
        last = max(items, key=lambda p: _aware(p.started_at))
        rows.append({
            "subject_id": subject_id,
            "node_id": last.node_id,
            "name": last.name,
            "site": last.site,
            "region": last.region,
            "state": last.state,
            **summary,
        })
    rows.sort(key=lambda r: (r["availability_pct"], -r["minutes"].get("down", 0)))
    measured = [r["availability_pct"] for r in rows]
    return {
        "available": True,
        "kind": kind,
        "days": days,
        "subjects": len(rows),
        "average_pct": round(sum(measured) / len(measured), 3) if measured else None,
        "rows": rows[:limit],
    }


def status(db: Session) -> dict:
    """Profondeur du journal : depuis quand il est tenu, et ce qu'il contient."""
    try:
        since = db.query(func.min(HistState.started_at)).scalar()
        counts = dict(
            db.query(HistState.subject_kind, func.count(func.distinct(HistState.subject_id)))
            .group_by(HistState.subject_kind).all()
        )
        alerts = db.query(func.count(HistAlert.id)).scalar()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HistoryUnavailable(str(exc)) from exc
    return {
        "available": True,
        "since": _aware(since).isoformat() if since else None,
        "nodes": counts.get("node", 0),
        "links": counts.get("link", 0),
        "alerts": alerts or 0,
    }
