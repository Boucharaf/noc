"""
Disponibilité sur la durée, lue dans le journal historique.

Le collecteur écrit (collector/history.py) ; ce module lit `hist_state` et
`hist_alert` pour répondre aux questions que l'instantané ne sait pas
traiter : disponibilité d'un équipement ou d'un lien sur 30 jours ou sur
l'année, nombre de pannes, durée moyenne d'une panne, MTTR technique des
alertes, classement des moins disponibles.

RÈGLES DE CALCUL — les mêmes partout :
  * disponibilité = temps où l'équipement RÉPOND ÷ temps SUPERVISÉ (en
    service + dégradé + hors service) — KPI-01 de l'agence. Un équipement
    dégradé répond : il est disponible ; un équipement injoignable derrière
    une panne en amont (UNREACHABLE) est « inconnu » ;
  * le temps « inconnu » (aucune observation de l'état) n'est PAS une panne :
    il est publié à part (`unsupervised_minutes`) et sort du dénominateur,
    comme la maintenance (AM-29) — sinon un équipement non supervisé
    s'affiche « hors service » et fait chuter tous les taux ;
  * le temps NON OBSERVÉ (collecteur arrêté, outil muet plus de trois
    cycles et d'au moins 5 min, avant le début du journal) est publié à part et n'entre pas dans
    le calcul : il ne compte ni pour ni contre ;
  * une panne = un ÉPISODE continu d'indisponibilité confirmée (INC-39) :
    plusieurs périodes « hors service » séparées par moins de
    FAILURE_MERGE_S (15 min), ou seulement par du temps inconnu / en maintenance, forment
    UNE panne. Sans cette fusion, un équipement qui oscille compte des
    centaines de pannes et le MTBF n'a plus de sens. La durée d'un épisode
    n'entre dans le MTTR qu'une fois close.

SOURCE MAÎTRE (collector/downtime.py) : quand le journal des pannes de
NetXMS (downtime_log) est synchronisé, les équipements NetXMS sont en panne
EXACTEMENT pendant les pannes qu'il enregistre, à la seconde, au lieu des
pannes déduites des cycles de collecte. La maintenance et le temps non
supervisé restent ceux du NOC. Elle ne fait foi que jusqu'à sa dernière
donnée (horizon) ; ensuite, les observations du NOC décident. Chaque résultat dit sur quoi il repose
(`source`) et publie l'écart entre les deux (`reconciliation`).

Si les tables n'existent pas encore (schéma non rejoué), les fonctions
lèvent HistoryUnavailable et la route répond « historique indisponible »
au lieu d'une erreur : rien d'autre dans le NOC n'en dépend.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from collector import downtime as source_downtime
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import (
    AVAILABILITY_THRESHOLDS,
    COLLECT_INTERVAL_S,
    FAILURE_MERGE_S,
    OBSERVATION_GAP_S,
)
from app.models import (
    HistAlert,
    HistDowntime,
    HistSourceObject,
    HistSourceSync,
    HistState,
    HistToolHealth,
    NocAsset,
    NocAssetEvent,
    NocAssetSource,
)

logger = logging.getLogger(__name__)

INTERVAL = timedelta(seconds=COLLECT_INTERVAL_S)
MAX_GAP = timedelta(seconds=OBSERVATION_GAP_S)
EPISODE_GAP = timedelta(seconds=FAILURE_MERGE_S)
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
    ordered = sorted(periods, key=lambda p: _aware(p.started_at))
    episodes = down_episodes(ordered, now)
    down_count = sum(1 for start, _end_, _closed in episodes if start >= lo)
    downs = [
        (end_ - start).total_seconds()
        for start, end_, closed in episodes if closed and start >= lo
    ]
    for row in ordered:
        start, end = _aware(row.started_at), _end(row, now)
        clipped = _clip(start, end, lo, hi)
        if clipped is None:
            continue
        seconds[row.state] += (clipped[1] - clipped[0]).total_seconds()
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
    responding = seconds["up"] + seconds["degraded"]
    measured = responding + seconds["down"]
    window = (hi - lo).total_seconds()
    result = {
        "availability_pct": round(100.0 * responding / measured, 3) if measured > 0 else None,
        "observed_pct": round(100.0 * observed / window, 1) if window else None,
        "minutes": {state: round(value / 60, 1) for state, value in seconds.items() if value},
        "unobserved_minutes": round(max(0.0, window - observed) / 60, 1),
        "unsupervised_minutes": round(
            (seconds["unknown"] + seconds["silent"]) / 60, 1
        ),
        # Secondes où il répond et supervisées : permettent une moyenne
        # PONDÉRÉE par le temps sur un ensemble d'équipements (ranking).
        "up_seconds": round(responding),
        "supervised_seconds": round(measured),
        "down_count": down_count,
        "closed_down_count": len(downs),
        "closed_down_minutes": round(sum(downs) / 60, 1),
        "mttr_minutes": round(sum(downs) / len(downs) / 60, 1) if downs else None,
        "mtbf_hours": (
            round(responding / down_count / 3600, 1) if down_count else None
        ),
    }
    if with_segments:
        result["segments"] = segments[-_MAX_SEGMENTS:]
    return result


def down_episodes(ordered: list, now: datetime) -> list[tuple[datetime, datetime, bool]]:
    """Épisodes de panne (début, fin, clos ?) d'un sujet, périodes triées.

    Une reprise de moins de EPISODE_GAP (15 min) ne clôt pas
    l'épisode : c'est une oscillation, pas un rétablissement. Le temps inconnu
    ou en maintenance entre deux périodes de panne non plus.
    """
    episodes: list[list] = []
    current: list | None = None
    for row in ordered:
        start, end = _aware(row.started_at), _end(row, now)
        if row.state == "down":
            # Ni reprise assez longue, ni preuve de rétablissement depuis (temps
            # inconnu, en maintenance ou non observé) : la même panne.
            if current is not None:
                current[1] = max(current[1], end)
                current[2] = row.ended_at is not None
            else:
                # Début RÉEL de la panne quand la source le connaît
                # (collector/downtime.py) : une panne ouverte depuis des mois
                # n'est pas une panne nouvelle de la période, et sa durée part
                # de son vrai début.
                origin = _aware(getattr(row, "down_since", None)) or start
                current = [min(origin, start), end, row.ended_at is not None]
                episodes.append(current)
        elif row.state in ("up", "degraded") and current is not None \
                and end - start > EPISODE_GAP:
            current = None
        elif row.state in ("unknown", "silent", "maintenance") and current is not None:
            # Ne prolonge pas la panne, mais ne la clôt pas non plus.
            continue
    return [tuple(item) for item in episodes]


OBSERVATION = "noc_observation"


def active_sources(db: Session, now: datetime) -> dict[str, tuple]:
    """Sources maîtres activées ET synchronisées récemment, avec (horizon,
    complet depuis) : jusqu'où chacune sait, et depuis quand son journal de
    pannes est complet. Pour les autres, le calcul repose sur les
    observations du NOC."""
    enabled = source_downtime.enabled_sources()
    if not enabled:
        return {}
    try:
        rows = db.query(HistSourceSync).filter(HistSourceSync.source.in_(enabled)).all()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Synchronisation des pannes des outils illisible : %s", exc)
        return {}
    return {
        row.source: (
            # Sans horizon publié, la source sait jusqu'à sa dernière lecture.
            _aware(getattr(row, "horizon_at", None)) or _aware(row.synced_at),
            _aware(getattr(row, "complete_since", None)),
        )
        for row in rows
        if now - _aware(row.synced_at) <= source_downtime.STALE_AFTER
    }


def _source_windows(db: Session, active: dict, lo: datetime, hi: datetime,
                    node_ids=None, region=None, province=None, site=None) -> dict:
    """Fenêtres de supervision des équipements selon leur source maître, qui
    recoupent [lo, hi) : de quoi reconstituer leur disponibilité depuis la
    source seule, avant (ou sans) observation du NOC."""
    if not active:
        return {}
    try:
        query = db.query(HistSourceObject).filter(
            HistSourceObject.source.in_(sorted(active)),
            HistSourceObject.managed.is_(True),
            HistSourceObject.supervised_since < hi,
        )
        if node_ids is not None:
            query = query.filter(HistSourceObject.node_id.in_(list(node_ids)))
        if region:
            query = query.filter(HistSourceObject.region == region)
        if province:
            query = query.filter(HistSourceObject.province == province)
        if site:
            query = query.filter(HistSourceObject.site == site)
        objects = query.all()
    except SQLAlchemyError as exc:
        # Table absente (schéma non rejoué) : pas d'historique de la source,
        # le calcul reste celui des observations du NOC.
        db.rollback()
        logger.warning("Fenêtres de supervision illisibles : %s", exc)
        return {}
    windows = source_downtime.source_windows(objects, active)
    return {
        key: value for key, value in windows.items()
        if value[0][1] is not None and value[0][1] > lo
    }


def source_active(db: Session, now: datetime) -> bool:
    return bool(active_sources(db, now))


def _source_downtimes(db: Session, node_ids, lo: datetime, hi: datetime,
                      active: set[str]) -> dict:
    """Pannes des sources actives, par (source, équipement du NOC), sur la
    fenêtre (élargie de EPISODE_GAP pour la fusion des épisodes)."""
    node_ids = list(node_ids)
    if not node_ids or not active:
        return {}
    try:
        rows = _overlapping(
            db.query(HistDowntime).filter(
                HistDowntime.source.in_(sorted(active)),
                HistDowntime.node_id.in_(node_ids),
            ),
            HistDowntime.started_at, HistDowntime.ended_at, lo - EPISODE_GAP, hi,
        ).all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HistoryUnavailable(str(exc)) from exc
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        grouped[(row.source, row.node_id)].append((_aware(row.started_at), _aware(row.ended_at)))
    return grouped


def corrected(periods: list, subject_id: str, downtimes: dict, now: datetime,
              active, windows: dict | None = None,
              lo: datetime | None = None) -> tuple[list, str, dict | None, str | None]:
    """Périodes d'un équipement, corrigées par sa source maître si elle est
    active. Rend (périodes, libellé de la source, rapprochement, source).

    `windows` : fenêtres de supervision (_source_windows). Avec elles, le temps
    antérieur à la première observation du NOC est reconstitué depuis la
    source seule — c'est ce qui rend exploitable tout l'historique."""
    windows = windows or {}
    subjects = [subject for (_src, node), (_w, subject) in windows.items() if node == subject_id]
    master = source_downtime.master_source(periods or subjects, active)
    if master is None:
        return periods, OBSERVATION, None, None
    window, subject = windows.get((master, subject_id), (None, None))
    horizon = active[master][0] if isinstance(active, dict) else None
    if window is not None and lo is not None:
        # Rien à reconstituer avant la période demandée (au contexte près de
        # la fusion des épisodes) : le rapprochement porte sur la période.
        window = (max(window[0], lo - EPISODE_GAP), window[1])
    rows, report = source_downtime.overlay(
        periods, downtimes.get((master, subject_id), []), now, lambda r: _end(r, now),
        supervised=window, base=subject, horizon=horizon,
    )
    if lo is not None and horizon is not None and horizon <= lo:
        # La source n'a rien à dire de cette période : tout vient du NOC.
        return rows, OBSERVATION, None, master
    return rows, source_downtime.LABELS[master], report, master


def _window(days: int) -> tuple[datetime, datetime, datetime]:
    now = _now()
    return now - timedelta(days=days), now, now


def _overlapping(query, model_start, model_end, lo, hi):
    return query.filter(model_start < hi, or_(model_end.is_(None), model_end > lo))


def current_asset(db: Session, asset_id: str) -> str:
    """Identifiant qui continue `asset_id`, en suivant les réunions."""
    seen = set()
    try:
        while asset_id not in seen:
            seen.add(asset_id)
            target = db.query(NocAsset.merged_into).filter(NocAsset.id == asset_id).scalar()
            if not target:
                break
            asset_id = target
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Registre d'identité illisible : %s", exc)
    return asset_id


def asset_identity(db: Session, asset_id: str) -> dict | None:
    """Références d'outils et décisions d'identité d'un équipement."""
    try:
        asset = db.query(NocAsset).filter(NocAsset.id == asset_id).first()
        if asset is None:
            return None
        sources = db.query(NocAssetSource).filter(NocAssetSource.asset_id == asset_id).all()
        events = db.query(NocAssetEvent).filter(
            NocAssetEvent.asset_id == asset_id
        ).order_by(NocAssetEvent.at.desc()).limit(50).all()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Registre d'identité illisible : %s", exc)
        return None
    return {
        "since": _aware(asset.created_at).isoformat(),
        "last_seen_at": _aware(asset.last_seen_at).isoformat(),
        "merged_into": asset.merged_into,
        "sources": [
            {"tool": s.tool, "ref": s.ref, "name": s.name, "ip": s.ip,
             "since": _aware(s.valid_from or s.first_seen_at).isoformat()}
            for s in sources
        ],
        "events": [
            {"event": e.event, "at": _aware(e.at).isoformat(), "source": e.source,
             "from": e.from_value, "to": e.to_value}
            for e in events
        ],
    }


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
    source, reconciliation = OBSERVATION, None
    active = active_sources(db, now)
    windows = _source_windows(db, active, lo, hi, node_ids=[node_id]) if active else {}
    if active and (node_periods or windows):
        downtimes = _source_downtimes(db, [node_id], lo, hi, active)
        node_periods, source, report, master = corrected(
            node_periods, node_id, downtimes, now, active, windows, lo
        )
        if report is not None:
            reconciliation = source_downtime.reconciliation_minutes(report, master)
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
        "identity": asset_identity(db, node_id),
        "node": {
            **summarise(node_periods, lo, hi, now, with_segments=True),
            "source": source,
            "reconciliation": reconciliation,
        } if node_periods else None,
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
                    "acknowledged_at": (
                        _aware(a.acknowledged_at).isoformat() if a.acknowledged_at else None
                    ),
                    "acknowledged_by": a.acknowledged_by,
                    "ack_source": a.ack_source,
                }
                for a in alerts[:20]
            ],
        },
    }


def alert_response(db: Session, days: int = 30,
                   node_ids: set[str] | None = None,
                   start: datetime | None = None, end: datetime | None = None) -> dict:
    """MTTA des alertes techniques acquittées sur la période, closes ou non.

    Lu dans le journal : se limiter aux alertes encore actives oublierait
    toutes celles qui sont résolues. Un acquittement sans date connue
    n'est pas compté.
    """
    lo, hi, _unused = _window(days)
    lo, hi = start or lo, end or hi
    try:
        rows = db.query(
            HistAlert.node_id, HistAlert.opened_at, HistAlert.acknowledged_at
        ).filter(
            HistAlert.kind == "technical",
            HistAlert.acknowledged_at >= lo, HistAlert.acknowledged_at < hi,
        ).all()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Journal des acquittements illisible : %s", exc)
        raise HistoryUnavailable(str(exc)) from exc
    delays = [
        (_aware(row.acknowledged_at) - _aware(row.opened_at)).total_seconds() / 60
        for row in rows
        if node_ids is None or row.node_id in node_ids
    ]
    return {
        "days": days,
        "count": len(delays),
        "mtta_minutes": round(sum(delays) / len(delays), 1) if delays else None,
    }


def tools_health(db: Session, days: int = 30, start: datetime | None = None,
                 end: datetime | None = None) -> dict:
    """Disponibilité de chaque outil et ses interruptions sur la période.

    Le temps sans collecte (collecteur arrêté) n'est compté ni disponible ni
    en panne. « partial » n'est pas disponible : une partie manquait.
    """
    lo, hi, now = _window(days)
    lo, hi = start or lo, end or hi
    try:
        rows = _overlapping(
            db.query(HistToolHealth), HistToolHealth.started_at, HistToolHealth.ended_at, lo, hi
        ).order_by(HistToolHealth.started_at).all()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Santé des outils illisible : %s", exc)
        raise HistoryUnavailable(str(exc)) from exc
    tools: dict[str, dict] = {}
    for row in rows:
        ended = _aware(row.ended_at) if row.ended_at else min(
            now, _aware(row.last_seen_at) + timedelta(seconds=COLLECT_INTERVAL_S)
        )
        begin, finish = max(_aware(row.started_at), lo), min(ended, hi)
        seconds = max(0.0, (finish - begin).total_seconds())
        item = tools.setdefault(row.tool, {
            "tool": row.tool, "up_s": 0.0, "partial_s": 0.0, "down_s": 0.0, "outages": [],
        })
        item[f"{row.state}_s"] += seconds
        if row.state != "up":
            item["outages"].append({
                "state": row.state, "error": row.error, "minutes": round(seconds / 60, 1),
                "started_at": _aware(row.started_at).isoformat(),
                "ended_at": _aware(row.ended_at).isoformat() if row.ended_at else None,
            })
    result = []
    for item in sorted(tools.values(), key=lambda i: i["tool"]):
        observed = item["up_s"] + item["partial_s"] + item["down_s"]
        result.append({
            "tool": item["tool"],
            "availability_pct": round(100 * item["up_s"] / observed, 2) if observed else None,
            "observed_hours": round(observed / 3600, 2),
            "interruptions": len(item["outages"]),
            "outages": item["outages"][-20:][::-1],
        })
    return {"available": True, "days": days, "tools": result}


def ranking(db: Session, kind: str = "node", days: int = 30, limit: int = 20,
            region: str | None = None, province: str | None = None,
            site: str | None = None, core_ids: set[str] | None = None,
            node_ids: set[str] | None = None,
            start: datetime | None = None, end: datetime | None = None) -> dict:
    """Équipements (ou liens) les moins disponibles sur la période.

    `core_ids` : équipements de cœur, dont les seuils sont plus stricts
    (KPI-01). `node_ids` : restreint à ces équipements.

    Le périmètre porte sur la localité ENREGISTRÉE avec chaque période : un
    équipement déplacé reste compté là où il était. `start`/`end` : bornes
    explicites (un mois passé), à la place des `days` derniers jours."""
    lo, hi, now = _window(days)
    lo, hi = start or lo, min(end, now) if end else hi
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
        if node_ids is None or period.node_id in node_ids:
            grouped[period.subject_id].append(period)
    active = active_sources(db, now) if kind == "node" else {}
    # Équipements que leur source supervisait sur la période, même jamais
    # observés par le NOC (journal plus récent que la période demandée).
    windows = _source_windows(db, active, lo, hi, region=region, province=province,
                              site=site) if active else {}
    for _source, node_id in windows:
        if node_ids is None or node_id in node_ids:
            grouped.setdefault(node_id, [])
    downtimes = _source_downtimes(db, grouped, lo, hi, active) if active else None
    rows = []
    unsupervised = 0
    sources: dict[str, int] = defaultdict(int)
    gaps: dict[str, float] = defaultdict(float)
    for subject_id, items in grouped.items():
        source = OBSERVATION
        if downtimes is not None:
            items, source, report, _master = corrected(
                items, subject_id, downtimes, now, active, windows, lo
            )
            for key, value in (report or {}).items():
                gaps[key] += value
        summary = summarise(items, lo, hi, now)
        if summary["availability_pct"] is None:
            unsupervised += 1
            continue
        if not items:
            continue
        last = max(items, key=lambda p: _aware(p.started_at))
        sources[source] += 1
        rows.append({
            "subject_id": subject_id,
            "source": source,
            "class": (
                None if core_ids is None
                else "core" if last.node_id in core_ids else "access"
            ),
            "node_id": last.node_id,
            "name": last.name,
            "site": last.site,
            "region": last.region,
            "state": last.state,
            **summary,
        })
    rows.sort(key=lambda r: (r["availability_pct"], -r["minutes"].get("down", 0)))
    # Moyenne PONDÉRÉE par le temps supervisé (INC-01, INC-42) : un
    # équipement supervisé une heure ne pèse pas autant qu'un équipement
    # supervisé trente jours. C'est la « disponibilité » officielle du
    # périmètre sur la période ; la base est publiée avec elle (AM-34).
    up_s = sum(r["up_seconds"] for r in rows)
    supervised_s = sum(r["supervised_seconds"] for r in rows)
    episodes = sum(r["down_count"] for r in rows)
    closed = sum(r["closed_down_count"] for r in rows)
    closed_minutes = sum(r["closed_down_minutes"] for r in rows)
    return {
        "available": True,
        "kind": kind,
        "days": days,
        "subjects": len(rows),
        "average_pct": round(100.0 * up_s / supervised_s, 3) if supervised_s else None,
        # Cœur et accès séparément : leurs seuils diffèrent (KPI-01).
        "classes": None if core_ids is None else {
            name: _class_summary([r for r in rows if r["class"] == name])
            for name in ("core", "access")
        },
        "thresholds": AVAILABILITY_THRESHOLDS,
        # AM-10 : MTTR et MTBF techniques du périmètre, sur les ÉPISODES de
        # panne (INC-39) : un MTBF = temps en service ÷ nombre de pannes.
        "failures": episodes,
        "mttr_minutes": round(closed_minutes / closed, 1) if closed else None,
        "mtbf_hours": round(up_s / episodes / 3600, 1) if episodes else None,
        "basis": {
            "subjects": len(rows),
            "unsupervised": unsupervised,
            "days": days,
            # Sur quoi reposent les chiffres : journal de pannes de l'outil
            # (à la seconde) ou observations du NOC (au cycle près).
            "sources": dict(sources),
            "reconciliation": (
                {
                    **source_downtime.reconciliation_minutes(gaps),
                    "source": ",".join(
                        sorted(label for label in sources if label != OBSERVATION)
                    ),
                } if downtimes is not None else None
            ),
            "computed_at": now.isoformat(),
        },
        "rows": rows[:limit],
    }


def _class_summary(rows: list[dict]) -> dict:
    supervised = sum(r["supervised_seconds"] for r in rows)
    return {
        "subjects": len(rows),
        "average_pct": (
            round(100.0 * sum(r["up_seconds"] for r in rows) / supervised, 3)
            if supervised else None
        ),
    }


def month_alerts(db: Session, lo: datetime, hi: datetime, region: str | None = None,
                 province: str | None = None, site: str | None = None,
                 limit: int = 200) -> dict:
    """Alertes du mois [lo, hi) : apparues dans le mois, et antérieures encore
    non corrigées pendant le mois."""
    try:
        query = _overlapping(
            db.query(HistAlert).filter(HistAlert.kind == "technical"),
            HistAlert.opened_at, HistAlert.closed_at, lo, hi,
        )
        for column, value in (
            (HistAlert.region, region), (HistAlert.province, province), (HistAlert.site, site)
        ):
            if value:
                query = query.filter(column == value)
        rows = query.order_by(HistAlert.opened_at.desc()).all()
        since = _aware(db.query(func.min(HistAlert.first_seen_at)).scalar())
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Journal des alertes illisible : %s", exc)
        raise HistoryUnavailable(str(exc)) from exc
    opened = [row for row in rows if _aware(row.opened_at) >= lo]
    by_severity: dict[str, int] = defaultdict(int)
    for row in opened:
        by_severity[row.severity] += 1
    return {
        "opened": len(opened),
        "opened_by_severity": dict(by_severity),
        # Avant le début du journal, une alerte corrigée n'a laissé aucune
        # trace dans le NOC : 0 serait faux, None dit « non suivi ».
        "closed": None if since is None or hi <= since else sum(
            1 for row in rows if row.closed_at is not None and _aware(row.closed_at) < hi
        ),
        "journal_since": since.isoformat() if since else None,
        "earlier_open": len(rows) - len(opened),
        "rows": [
            {
                "key": row.alert_key,
                "tool": row.tool,
                "severity": row.severity,
                "message": row.message,
                "node_id": row.node_id,
                "node_name": row.node_name,
                "site": row.site,
                "opened_at": _aware(row.opened_at).isoformat(),
                "closed_at": _aware(row.closed_at).isoformat() if row.closed_at else None,
                "earlier": _aware(row.opened_at) < lo,
            }
            for row in rows[:limit]
        ],
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


FLAPPING_CHANGES = 5


def flapping(db: Session, hours: int = 1, threshold: int = FLAPPING_CHANGES,
             region: str | None = None, province: str | None = None,
             site: str | None = None) -> dict:
    """Équipements instables (AM-08, KPI-14) : au moins `threshold`
    changements d'état sur les `hours` dernières heures.

    Un changement = une nouvelle période d'état commencée dans la fenêtre,
    lue dans le journal. L'oscillation génère une alerte à chaque bascule :
    la signaler en un seul point coupe le bruit à la racine.
    """
    now = _now()
    lo = now - timedelta(hours=hours)
    try:
        query = db.query(HistState).filter(
            HistState.subject_kind == "node", HistState.started_at >= lo
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
        raise HistoryUnavailable(str(exc)) from exc
    grouped: dict[str, list] = defaultdict(list)
    for period in periods:
        grouped[period.subject_id].append(period)
    rows = []
    for items in grouped.values():
        if len(items) < threshold:
            continue
        items.sort(key=lambda p: _aware(p.started_at))
        last = items[-1]
        rows.append({
            "node_id": last.node_id,
            "name": last.name,
            "site": last.site,
            "changes": len(items),
            "states": sorted({p.state for p in items}),
            "last_state": last.state,
            "last_change_at": _aware(last.started_at).isoformat(),
        })
    rows.sort(key=lambda r: -r["changes"])
    return {"available": True, "hours": hours, "threshold": threshold, "rows": rows}
