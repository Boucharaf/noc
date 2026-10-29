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

from sqlalchemy.orm import Session

from app.core.config import NODE_STATES
from app.services import live_service
from collector.operations import window_is_active

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


MAINTENANCE_SOURCE = {"change": "Changement iTop", "maintenance": "Maintenance Zabbix"}


async def active_windows(at: datetime | None = None) -> list[dict]:
    """Maintenances en cours, lues dans les outils (voir live_service)."""
    at = at or datetime.now(timezone.utc)
    return [
        window for window in await live_service.get_maintenance()
        if window.get("node_keys") and window_is_active(window, at)
    ]


def maintenance_label(window: dict) -> str:
    source = MAINTENANCE_SOURCE.get(window.get("kind"), "Maintenance")
    ref = f" {window['ref']}" if window.get("ref") and window.get("kind") == "change" else ""
    return f"{source}{ref} — {window.get('title') or ''}".strip(" —")


def apply_maintenance_windows(nodes: list[dict], windows: list[dict]) -> list[dict]:
    """Marque « maintenance » les équipements visés par une maintenance en
    cours, sur une COPIE de l'instantané. Un équipement que son outil
    déclare déjà en maintenance (hôte Zabbix, downtime Nagios) l'est resté
    dans l'instantané."""
    by_node: dict[str, dict] = {}
    for window in windows:
        for key in window.get("node_keys") or []:
            by_node.setdefault(key, window)
    enriched = []
    for node in nodes:
        window = by_node.get(node.get("id"))
        enriched.append(
            {
                **node,
                "state": "maintenance" if window else node.get("state", "unknown"),
                "measured_state": node.get("state", "unknown"),
                "maintenance_reason": maintenance_label(window) if window else None,
                "maintenance_until": window.get("end") if window else None,
            }
        )
    return enriched


async def nodes_with_maintenance(
    db: Session | None = None, at: datetime | None = None
) -> list[dict]:
    nodes = await live_service.get_nodes()
    return apply_maintenance_windows(nodes, await active_windows(at))


async def list_nodes(
    db: Session,
    state: str | None = None,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    tool: str | None = None,
    search: str | None = None,
    organisation: str | None = None,
    node_type: str | None = None,
    sort: str = "state",
    limit: int = 200,
    offset: int = 0,
) -> dict:
    # Import local : geo_service dépend lui-même de ce module.
    from app.services.geo_service import scope_nodes

    enriched = []
    for node in scope_nodes(await nodes_with_maintenance(db), region, province, site):
        enriched.append(
            {
                **node,
                "tools": sorted((node.get("sources") or {}).keys()),
            }
        )

    def keep(node: dict) -> bool:
        if state and node.get("state") != state:
            return False
        if tool and tool not in (node.get("sources") or {}):
            return False
        if organisation and node.get("organisation") != organisation:
            return False
        if node_type and node.get("node_type") != node_type:
            return False
        if search:
            needle = search.strip().lower()
            haystack = " ".join(
                str(node.get(field) or "")
                for field in (
                    "name", "hostname", "ip", "site", "province", "region", "organisation",
                )
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
    nodes = await nodes_with_maintenance(db)
    node = next((item for item in nodes if item.get("id") == node_id), None)
    if node is None:
        return None

    records = [
        alert
        for alert in await live_service.get_alerts()
        if (node.get("sources") or {}).get(alert["tool"]) == alert.get("node_ref")
    ]
    alerts = [
        record for record in records
        if record.get("kind", "technical") == "technical"
    ]
    itsm_tickets = [record for record in records if record.get("kind") == "itsm_ticket"]

    from app.services import geo_service  # geo_service importe ce module

    facts = [item for item in (node.get("details") or {}).values() if isinstance(item, dict)]
    down_since = next((item["down_since"] for item in facts if item.get("down_since")), None)
    return {
        **node,
        # Heure de la panne, quand l'outil la date (NetXMS). Montrée seulement
        # si l'équipement n'est pas en service : un « hors service depuis »
        # sur un équipement disponible serait une contradiction à l'écran.
        "down_since": down_since if node.get("measured_state", node.get("state"))
        in ("down", "unknown") else None,
        "boot_time": next((item["boot_time"] for item in facts if item.get("boot_time")), None),
        "position": geo_service.position(node, nodes),
        "tools": sorted((node.get("sources") or {}).keys()),
        "active_alerts": alerts,
        "itsm_tickets": itsm_tickets,
        # Interventions et maintenances : ordres de travail et changements
        # iTop (et maintenances Zabbix) qui visent cet équipement.
        "work_orders": [
            order for order in await live_service.get_work_orders()
            if node_id in (order.get("node_keys") or [])
        ],
        "maintenances": [
            window for window in await live_service.get_maintenance()
            if node_id in (window.get("node_keys") or [])
        ],
    }


async def state_counts(db: Session, nodes: list[dict] | None = None) -> dict[str, int]:
    """Décompte par état, pour les tuiles du tableau de bord.

    Tous les états du vocabulaire sont présents, y compris à zéro : une
    tuile qui disparaît quand son compteur tombe à zéro fait sauter la mise
    en page et laisse croire à une panne d'affichage.
    """
    nodes = await nodes_with_maintenance(db) if nodes is None else nodes
    counts = {state: 0 for state in NODE_STATES}
    for node in nodes:
        counts[node.get("state", "unknown")] = counts.get(node.get("state", "unknown"), 0) + 1
    return counts


async def coverage_by_tool(nodes: list[dict] | None = None) -> list[dict]:
    """Couverture de supervision, outil par outil.

    Répond à la question que se pose le responsable du NOC : « combien
    d'équipements ne sont vus que par un seul outil ? » Un équipement vu par
    un seul outil est un point de rupture — si cet outil tombe, on le perd
    de vue sans le savoir.
    """
    nodes = await live_service.get_nodes() if nodes is None else nodes
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
