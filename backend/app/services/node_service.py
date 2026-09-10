"""
Inventaire des équipements.

TOUT VIENT DE L'INSTANTANÉ REDIS. L'ancien service dérivait l'état d'un
équipement en SQL, par une requête de cent lignes croisant `metric_value`,
`fact_incident` et `ops_maintenance_window`. Cette dérivation vit désormais
là où elle a du sens : dans le collecteur, qui lit l'état directement chez
l'outil qui mesure (collector/merge.py). Le backend ne le recalcule plus,
il l'affiche.

CE QUE LE BACKEND AJOUTE ENCORE, parce que les outils sources l'ignorent :
le marquage « maintenance planifiée » et le décompte des interventions de
terrain en cours.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import NODE_STATES
from app.models import FieldIntervention, MaintenanceWindow
from app.services import live_service

logger = logging.getLogger(__name__)

# Ordre d'affichage : le plus dégradé d'abord. C'est l'ordre dans lequel un
# exploitant veut voir son parc — pas l'ordre alphabétique.
_STATE_RANK = {state: index for index, state in enumerate(NODE_STATES)}

_SORTS = {
    "state": lambda n: (_STATE_RANK.get(n.get("state"), 9), -n.get("alerts", 0), n.get("name", "").lower()),
    "name": lambda n: n.get("name", "").lower(),
    "site": lambda n: (n.get("site") or "￿", n.get("name", "").lower()),
    "alerts": lambda n: (-n.get("alerts", 0), n.get("name", "").lower()),
    "tools": lambda n: (-len(n.get("sources") or {}), n.get("name", "").lower()),
}


def _active_windows(db: Session, at: datetime) -> list[MaintenanceWindow]:
    return list(
        db.execute(
            select(MaintenanceWindow).where(
                MaintenanceWindow.starts_at <= at, MaintenanceWindow.ends_at >= at
            )
        ).scalars()
    )


def _maintenance_for(windows, node: dict) -> MaintenanceWindow | None:
    for window in windows:
        if window.node_key and window.node_key == node.get("id"):
            return window
        if window.site and node.get("site") and window.site == node["site"]:
            return window
    return None


async def list_nodes(
    db: Session,
    state: str | None = None,
    site: str | None = None,
    tool: str | None = None,
    search: str | None = None,
    sort: str = "state",
    limit: int = 200,
    offset: int = 0,
) -> dict:
    nodes = await live_service.get_nodes()
    windows = _active_windows(db, datetime.now(timezone.utc))

    enriched = []
    for node in nodes:
        window = _maintenance_for(windows, node)
        enriched.append(
            {
                **node,
                # La maintenance PRIME sur l'état mesuré : un équipement
                # éteint pour entretien est « en maintenance », pas « en
                # panne ». Le distinguer évite qu'un exploitant parte en
                # intervention sur une coupure programmée.
                "state": "maintenance" if window else node.get("state", "unknown"),
                "measured_state": node.get("state", "unknown"),
                "maintenance_reason": window.reason if window else None,
                "maintenance_until": window.ends_at.isoformat() if window else None,
                "tools": sorted((node.get("sources") or {}).keys()),
            }
        )

    def keep(node: dict) -> bool:
        if state and node.get("state") != state:
            return False
        if site and node.get("site") != site:
            return False
        if tool and tool not in (node.get("sources") or {}):
            return False
        if search:
            needle = search.strip().lower()
            haystack = " ".join(
                str(node.get(field) or "")
                for field in ("name", "hostname", "ip", "site", "organisation")
            ).lower()
            if needle not in haystack:
                return False
        return True

    filtered = [n for n in enriched if keep(n)]
    filtered.sort(key=_SORTS.get(sort, _SORTS["state"]))

    return {
        "nodes": filtered[offset : offset + limit],
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def get_node(db: Session, node_id: str) -> dict | None:
    """Fiche d'un équipement.

    Ne contient AUCUNE courbe : les séries sont servies par une route
    séparée (`/api/nodes/{id}/metrics`), parce qu'elles demandent un appel
    vers l'outil source et qu'ouvrir une fiche ne doit pas dépendre de la
    disponibilité de Zabbix.
    """
    node = await live_service.get_node(node_id)
    if node is None:
        return None

    window = _maintenance_for(_active_windows(db, datetime.now(timezone.utc)), node)

    interventions = list(
        db.execute(
            select(FieldIntervention)
            .where(
                FieldIntervention.node_key == node_id,
                FieldIntervention.status.in_(("scheduled", "in_progress")),
            )
            .order_by(FieldIntervention.scheduled_at)
        ).scalars()
    )

    alerts = [
        alert
        for alert in await live_service.get_alerts()
        if (node.get("sources") or {}).get(alert["tool"]) == alert.get("node_ref")
    ]

    return {
        **node,
        "state": "maintenance" if window else node.get("state", "unknown"),
        "measured_state": node.get("state", "unknown"),
        "maintenance_reason": window.reason if window else None,
        "maintenance_until": window.ends_at.isoformat() if window else None,
        "tools": sorted((node.get("sources") or {}).keys()),
        "active_alerts": alerts,
        "field_interventions": [
            {
                "id": row.id,
                "status": row.status,
                "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
                "agent_user_id": row.agent_user_id,
            }
            for row in interventions
        ],
    }


async def state_counts() -> dict[str, int]:
    """Décompte par état, pour les tuiles du tableau de bord.

    Tous les états du vocabulaire sont présents, y compris à zéro : une
    tuile qui disparaît quand son compteur tombe à zéro fait sauter la mise
    en page et laisse croire à une panne d'affichage.
    """
    nodes = await live_service.get_nodes()
    counts = {state: 0 for state in NODE_STATES}
    for node in nodes:
        counts[node.get("state", "unknown")] = counts.get(node.get("state", "unknown"), 0) + 1
    return counts


async def coverage_by_tool() -> list[dict]:
    """Couverture de supervision, outil par outil.

    Répond à la question que se pose le responsable du NOC : « combien
    d'équipements ne sont vus que par un seul outil ? » Un équipement vu par
    un seul outil est un point de rupture — si cet outil tombe, on le perd
    de vue sans le savoir.
    """
    nodes = await live_service.get_nodes()
    by_tool: dict[str, int] = {}
    single = 0
    for node in nodes:
        sources = node.get("sources") or {}
        if len(sources) == 1:
            single += 1
        for tool in sources:
            by_tool[tool] = by_tool.get(tool, 0) + 1

    total = len(nodes)
    return [
        {
            "tool": tool,
            "nodes": count,
            "coverage_pct": round(100.0 * count / total, 1) if total else 0.0,
        }
        for tool, count in sorted(by_tool.items(), key=lambda item: -item[1])
    ] + [
        {
            "tool": "_single_source",
            "nodes": single,
            "coverage_pct": round(100.0 * single / total, 1) if total else 0.0,
        }
    ]
