"""
Le mur d'alertes — assemblage de trois sources.

CE QUE VOIT UN EXPLOITANT est la réunion de :

  1. les alertes actives de l'instantané Redis (Zabbix, Centreon, iTop…) ;
  2. les incidents signalés à la main, qu'aucune sonde ne voit — câble
     sectionné sur un site sans supervision, groupe électrogène en panne ;
  3. le travail du NOC sur chacune : acquittement, affectation, cause
     retenue, notes.

Aucune de ces trois n'est complète seule. C'est ce module qui les assemble,
et c'est le seul endroit du backend qui le fasse.

LA MAINTENANCE PLANIFIÉE ne supprime pas une alerte, elle la MARQUE. La
distinction compte : un exploitant doit pouvoir voir qu'un site est en
coupure programmée — sinon il croit à un trou de supervision et lance une
intervention pour rien. En revanche, une alerte marquée est exclue des
indicateurs, parce qu'une coupure voulue n'est pas une panne.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import SEVERITIES
from app.models import AlertState, ManualIncident, MaintenanceWindow, User
from app.services import live_service

logger = logging.getLogger(__name__)

# Alertes signalées à la main : préfixe qui ne peut entrer en collision avec
# une clé du collecteur, celui-ci ne produisant que des clés préfixées du nom
# d'un outil configuré.
MANUAL_PREFIX = "manual:"


def _severity_rank(severity: str) -> int:
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return len(SEVERITIES)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def _active_windows(db: Session, at: datetime) -> list[MaintenanceWindow]:
    return list(
        db.execute(
            select(MaintenanceWindow).where(
                MaintenanceWindow.starts_at <= at,
                MaintenanceWindow.ends_at >= at,
                MaintenanceWindow.suppress_alerts.is_(True),
            )
        ).scalars()
    )


def _covered_by_maintenance(
    windows: list[MaintenanceWindow], node_key: str | None, site: str | None
) -> MaintenanceWindow | None:
    """Fenêtre couvrant cette alerte, s'il y en a une.

    Une fenêtre porte sur un équipement OU sur un site entier. Le second cas
    est celui qui compte en pratique : quand un groupe électrogène est coupé
    pour entretien, ce sont tous les équipements du site qui tombent, pas un
    seul — et personne n'a le temps de déclarer trente fenêtres.
    """
    for window in windows:
        if window.node_key and window.node_key == node_key:
            return window
        if window.site and site and window.site == site:
            return window
    return None


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
def _states_by_key(db: Session, keys: list[str]) -> dict[str, AlertState]:
    """Travail du NOC, indexé par clé d'alerte.

    Une seule requête pour tout le mur, et non une par alerte : sur un parc
    en crise, la seconde option produirait plusieurs centaines d'allers-
    retours vers PostgreSQL pour afficher un écran.
    """
    if not keys:
        return {}
    rows = db.execute(
        select(AlertState).where(AlertState.alert_key.in_(keys))
    ).scalars()
    return {row.alert_key: row for row in rows}


def _user_names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(user_ids))
    )
    return {row.id: row.full_name or row.username for row in rows}


def _manual_alerts(db: Session) -> list[dict]:
    """Incidents signalés à la main, mis au format d'une alerte.

    Ils traversent ensuite exactement le même chemin que les alertes des
    outils : même vocabulaire de sévérité, même acquittement, même
    marquage de maintenance. Un incident humain n'est pas un citoyen de
    seconde zone du mur d'alertes.
    """
    rows = db.execute(
        select(ManualIncident).where(ManualIncident.resolved_at.is_(None))
    ).scalars()
    return [
        {
            "tool": "manual",
            "ref": str(row.id),
            "key": row.alert_key(),
            "severity": row.severity,
            "message": row.title,
            "description": row.description,
            "since": row.detected_at.isoformat() if row.detected_at else None,
            "node_ref": row.node_key,
            "node_name": row.node_name,
            "site": row.site,
            "acknowledged": False,
            "acknowledged_at": None,
            "ticket_ref": None,
        }
        for row in rows
    ]


async def list_alerts(
    db: Session,
    severity: str | None = None,
    tool: str | None = None,
    site: str | None = None,
    acknowledged: bool | None = None,
    include_maintenance: bool = True,
    limit: int = 500,
) -> dict:
    """Le mur d'alertes complet.

    Rend aussi l'âge de l'instantané : l'interface doit pouvoir signaler des
    données vieillissantes plutôt que de les présenter comme fraîches.
    """
    now = datetime.now(timezone.utc)

    live = await live_service.get_alerts()
    nodes = {node["id"]: node for node in await live_service.get_nodes()}

    # Index (outil, référence) -> équipement fusionné, pour retrouver le site
    # d'une alerte. Construit une fois : le refaire par alerte coûterait le
    # produit des deux ensembles.
    node_by_source: dict[str, dict] = {}
    for node in nodes.values():
        for source_tool, ref in (node.get("sources") or {}).items():
            node_by_source[f"{source_tool}:{ref}"] = node

    alerts: list[dict] = []
    for alert in live:
        node = node_by_source.get(f"{alert['tool']}:{alert.get('node_ref')}")
        alerts.append(
            {
                **alert,
                "key": f"{alert['tool']}:{alert['ref']}",
                "node_key": node["id"] if node else None,
                "node_name": alert.get("node_name") or (node["name"] if node else None),
                "site": node.get("site") if node else None,
            }
        )

    for manual in _manual_alerts(db):
        node = nodes.get(manual.get("node_ref") or "")
        alerts.append(
            {
                **manual,
                "node_key": manual.get("node_ref"),
                "site": manual.get("site") or (node.get("site") if node else None),
            }
        )

    # -- travail du NOC ---------------------------------------------------
    states = _states_by_key(db, [a["key"] for a in alerts])
    user_ids = {
        uid
        for state in states.values()
        for uid in (state.acknowledged_by, state.assigned_to)
        if uid
    }
    names = _user_names(db, user_ids)

    # -- maintenance ------------------------------------------------------
    windows = _active_windows(db, now)

    enriched: list[dict] = []
    for alert in alerts:
        state = states.get(alert["key"])
        window = _covered_by_maintenance(windows, alert.get("node_key"), alert.get("site"))

        enriched.append(
            {
                **alert,
                # L'acquittement vient soit de l'outil source, soit du NOC.
                # Les deux comptent : un technicien qui acquitte dans Zabbix
                # a fait le travail, même s'il n'est pas passé par le NOC.
                "acknowledged": bool(alert.get("acknowledged")) or bool(state and state.acknowledged_at),
                "acknowledged_by": names.get(state.acknowledged_by) if state else None,
                "acknowledged_at": (
                    state.acknowledged_at.isoformat()
                    if state and state.acknowledged_at
                    else alert.get("acknowledged_at")
                ),
                "assigned_to": names.get(state.assigned_to) if state else None,
                "cause": state.cause if state else None,
                "escalation_level": state.escalation_level if state else 0,
                "is_maintenance": window is not None,
                "maintenance_reason": window.reason if window else None,
            }
        )

    # -- filtres ----------------------------------------------------------
    def keep(alert: dict) -> bool:
        if severity and alert.get("severity") != severity:
            return False
        if tool and alert.get("tool") != tool:
            return False
        if site and alert.get("site") != site:
            return False
        if acknowledged is not None and bool(alert.get("acknowledged")) != acknowledged:
            return False
        if not include_maintenance and alert.get("is_maintenance"):
            return False
        return True

    filtered = [a for a in enriched if keep(a)]
    # Les plus graves d'abord, et à gravité égale les plus récentes : c'est
    # l'ordre dans lequel un exploitant traite sa file.
    #
    # Deux tris successifs plutôt qu'une clé composite, parce que les deux
    # critères vont en sens INVERSE — gravité croissante (critical d'abord),
    # date décroissante — et que `since` est une chaîne ISO qu'on ne peut pas
    # nier. Le tri de Python étant stable, trier d'abord sur le critère
    # secondaire puis sur le principal donne exactement le bon résultat.
    filtered.sort(key=lambda a: a.get("since") or "", reverse=True)
    filtered.sort(key=lambda a: _severity_rank(a.get("severity", "unknown")))

    return {
        "alerts": filtered[:limit],
        "total": len(filtered),
        "truncated": len(filtered) > limit,
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def get_alert(db: Session, alert_key: str) -> dict | None:
    """Fiche d'une alerte, avec son journal d'exploitation."""
    from app.models import AlertTimeline

    result = await list_alerts(db, limit=100000)
    alert = next((a for a in result["alerts"] if a["key"] == alert_key), None)

    state = db.get(AlertState, alert_key)
    if alert is None and state is None:
        return None

    if alert is None:
        # L'alerte a quitté l'instantané (résolue à la source) mais le NOC a
        # travaillé dessus. On sert la fiche depuis ce qu'on a figé au moment
        # de la prise en charge — d'où l'existence des colonnes `*_at_pickup`.
        alert = {
            "key": alert_key,
            "tool": alert_key.split(":", 1)[0],
            "severity": state.severity_at_pickup or "unknown",
            "message": state.message_at_pickup,
            "since": state.detected_at.isoformat() if state.detected_at else None,
            "node_key": state.node_key,
            "node_name": state.node_name,
            "cleared": True,
        }

    # Matérialisé en liste : le résultat est parcouru deux fois — une fois
    # pour collecter les identifiants d'utilisateurs, une fois pour rendre
    # les lignes. Un curseur SQLAlchemy s'épuise au premier parcours et le
    # second rendrait une liste vide, sans erreur.
    timeline = list(
        db.execute(
            select(AlertTimeline)
            .where(AlertTimeline.alert_key == alert_key)
            .order_by(AlertTimeline.created_at.desc())
        ).scalars()
    )
    names = _user_names(db, {row.user_id for row in timeline if row.user_id})

    return {
        **alert,
        "resolution_note": state.resolution_note if state else None,
        "resolved_at": (
            state.resolved_at.isoformat() if state and state.resolved_at else None
        ),
        "ticket_ref": state.ticket_ref if state else None,
        "timeline": [
            {
                "action": row.action,
                "note": row.note,
                "user": names.get(row.user_id),
                "at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in timeline
        ],
    }


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------
async def _ensure_state(db: Session, alert_key: str) -> AlertState:
    """Récupère l'état d'une alerte, en le créant au besoin.

    La création FIGE une copie du libellé et de la sévérité. C'est la seule
    duplication tolérée dans ce schéma, et elle a une raison précise : quand
    Zabbix aura purgé l'événement, la fiche d'exploitation devra rester
    lisible. Elle n'est jamais rafraîchie ensuite — sinon elle deviendrait
    une seconde source de vérité qui dériverait de l'instantané.
    """
    state = db.get(AlertState, alert_key)
    if state is not None:
        return state

    snapshot = None
    for alert in await live_service.get_alerts():
        if f"{alert['tool']}:{alert['ref']}" == alert_key:
            snapshot = alert
            break

    detected_at = None
    if snapshot and snapshot.get("since"):
        try:
            detected_at = datetime.fromisoformat(snapshot["since"])
        except ValueError:
            detected_at = None

    state = AlertState(
        alert_key=alert_key,
        node_key=snapshot.get("node_ref") if snapshot else None,
        node_name=snapshot.get("node_name") if snapshot else None,
        severity_at_pickup=snapshot.get("severity") if snapshot else None,
        message_at_pickup=snapshot.get("message") if snapshot else None,
        detected_at=detected_at,
    )
    db.add(state)
    return state


async def acknowledge(db: Session, alert_key: str, user_id: int, note: str | None) -> dict:
    from app.models import AlertTimeline

    state = await _ensure_state(db, alert_key)
    if state.acknowledged_at is None:
        state.acknowledged_at = datetime.now(timezone.utc)
        state.acknowledged_by = user_id
    state.updated_at = datetime.now(timezone.utc)

    db.add(
        AlertTimeline(
            alert_key=alert_key, user_id=user_id, action="acknowledged", note=note
        )
    )
    db.commit()
    return {"alert_key": alert_key, "acknowledged_at": state.acknowledged_at.isoformat()}


async def assign(db: Session, alert_key: str, user_id: int, assignee_id: int,
                 note: str | None) -> dict:
    from app.models import AlertTimeline

    state = await _ensure_state(db, alert_key)
    state.assigned_to = assignee_id
    state.assigned_at = datetime.now(timezone.utc)
    state.updated_at = state.assigned_at

    db.add(
        AlertTimeline(
            alert_key=alert_key,
            user_id=user_id,
            action="assigned",
            note=note or f"Affectée à l'utilisateur {assignee_id}",
        )
    )
    db.commit()
    return {"alert_key": alert_key, "assigned_to": assignee_id}


async def resolve(db: Session, alert_key: str, user_id: int, cause: str | None,
                  note: str | None) -> dict:
    """Clôture côté NOC.

    Ne ferme RIEN chez l'outil source : le NOC n'a pas à décider qu'un
    déclencheur Zabbix doit se taire. Cette clôture enregistre le diagnostic
    et la fin du travail d'exploitation ; si l'alerte reste active à la
    source, elle reste visible, marquée comme traitée. C'est volontaire —
    masquer une alerte encore active serait dangereux.
    """
    from app.models import AlertTimeline

    state = await _ensure_state(db, alert_key)
    state.resolved_at = datetime.now(timezone.utc)
    state.cause = cause or state.cause
    state.resolution_note = note or state.resolution_note
    state.updated_at = state.resolved_at

    db.add(
        AlertTimeline(
            alert_key=alert_key,
            user_id=user_id,
            action="resolved",
            note=note or cause,
        )
    )
    db.commit()
    return {"alert_key": alert_key, "resolved_at": state.resolved_at.isoformat()}


async def add_note(db: Session, alert_key: str, user_id: int, note: str) -> dict:
    from app.models import AlertTimeline

    await _ensure_state(db, alert_key)
    entry = AlertTimeline(alert_key=alert_key, user_id=user_id, action="note", note=note)
    db.add(entry)
    db.commit()
    return {"alert_key": alert_key, "note": note}
