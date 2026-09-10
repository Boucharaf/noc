"""
Métriques — état instantané depuis Redis, courbes depuis les outils sources.

DEUX CHEMINS TRÈS DIFFÉRENTS, et il faut savoir lequel on emprunte :

  `network_snapshot()`, `top_nodes()`  — lisent l'instantané Redis. Quelques
      microsecondes, jamais en échec tant que le collecteur tourne. Ce sont
      eux qui alimentent le mur et les tuiles.

  `node_series()`, `network_series()`  — interrogent l'OUTIL SOURCE, avec
      cache. Quelques centaines de millisecondes au premier appel, et
      dépendantes de la disponibilité de Zabbix ou Centreon. Ils
      n'alimentent que les écrans qu'un exploitant ouvre explicitement.

Ne jamais mettre le second chemin sur un écran qui se rafraîchit tout seul :
ce serait rendre au parc de production la charge qu'on vient de lui retirer.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.config import METRIC_TYPES
from app.services import history_service, live_service

logger = logging.getLogger(__name__)


async def network_snapshot() -> dict:
    """Santé du réseau à l'instant présent, depuis l'instantané."""
    summary = await live_service.fleet_summary()
    nodes = await live_service.get_nodes()

    return {
        "nodes_total": summary["nodes_total"],
        "nodes_up": summary["nodes_by_state"].get("up", 0),
        "nodes_down": summary["nodes_by_state"].get("down", 0),
        "nodes_degraded": summary["nodes_by_state"].get("degraded", 0),
        # « silent » n'est pas « up ». Un équipement dont l'outil ne dit plus
        # rien est un trou de supervision, et le compter comme sain est la
        # façon la plus sûre de rater une panne.
        "nodes_silent": summary["nodes_by_state"].get("silent", 0),
        "nodes_maintenance": summary["nodes_by_state"].get("maintenance", 0),
        "fleet_health_pct": summary["fleet_health_pct"],
        "alerts_total": summary["alerts_total"],
        "alerts_critical": summary["alerts_by_severity"].get("critical", 0),
        "tools_covering": len(
            {tool for node in nodes for tool in (node.get("sources") or {})}
        ),
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def nodes_down() -> list[dict]:
    """Équipements en panne ou muets, les plus critiques d'abord."""
    nodes = await live_service.get_nodes()
    affected = [n for n in nodes if n.get("state") in ("down", "degraded", "silent")]
    order = {"down": 0, "degraded": 1, "silent": 2}
    affected.sort(
        key=lambda n: (order.get(n.get("state"), 9), -n.get("alerts", 0), n.get("name", ""))
    )
    return [
        {
            "id": node["id"],
            "name": node["name"],
            "hostname": node.get("hostname"),
            "ip": node.get("ip"),
            "state": node.get("state"),
            "site": node.get("site"),
            "alerts": node.get("alerts", 0),
            "worst_severity": node.get("worst_severity"),
            "tools": sorted((node.get("sources") or {}).keys()),
        }
        for node in affected
    ]


async def top_nodes(limit: int = 10) -> list[dict]:
    """Équipements les plus alertants.

    Classement fait sur l'instantané et non sur un historique : la question
    posée est « qui me pose problème MAINTENANT », pas « qui m'a posé
    problème ce mois-ci » — celle-là est dans les KPI.
    """
    nodes = await live_service.get_nodes()
    ranked = sorted(nodes, key=lambda n: -n.get("alerts", 0))
    return [
        {
            "id": node["id"],
            "name": node["name"],
            "site": node.get("site"),
            "state": node.get("state"),
            "alerts": node.get("alerts", 0),
            "worst_severity": node.get("worst_severity"),
        }
        for node in ranked[:limit]
        if node.get("alerts", 0) > 0
    ]


async def node_series(
    node_id: str,
    metric_type: str,
    period: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Courbe d'un équipement, lue chez son outil source."""
    node = await live_service.get_node(node_id)
    if node is None:
        return {"error": "Équipement inconnu de l'instantané courant", "points": []}

    window_start, window_end = history_service.resolve_window(period, start, end)
    result = await history_service.fetch_node_series(
        node, metric_type, window_start, window_end
    )
    return {
        **result,
        "node_id": node_id,
        "node_name": node.get("name"),
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
    }


async def node_all_series(
    node_id: str, period: str | None = None
) -> dict:
    """Toutes les métriques d'un équipement, en parallèle.

    Les sept types sont demandés en même temps et non l'un après l'autre :
    en série, ouvrir une fiche d'équipement coûterait sept allers-retours
    vers Zabbix, soit plusieurs secondes d'attente pour l'exploitant.
    """
    node = await live_service.get_node(node_id)
    if node is None:
        return {"error": "Équipement inconnu de l'instantané courant", "series": {}}

    window_start, window_end = history_service.resolve_window(period, None, None)
    results = await asyncio.gather(
        *(
            history_service.fetch_node_series(node, metric, window_start, window_end)
            for metric in METRIC_TYPES
        ),
        return_exceptions=True,
    )

    series: dict[str, dict] = {}
    for metric, result in zip(METRIC_TYPES, results):
        if isinstance(result, BaseException):
            logger.warning("Série %s de %s en échec : %s", metric, node_id, result)
            series[metric] = {"points": [], "source": None, "errors": [str(result)]}
        else:
            series[metric] = result

    return {
        "node_id": node_id,
        "node_name": node.get("name"),
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "series": series,
    }


async def network_series(
    metric_type: str, period: str | None = None, sample: int = 12
) -> dict:
    """Courbe agrégée du réseau, sur un ÉCHANTILLON d'équipements.

    Interroger tout le parc produirait autant d'appels qu'il y a
    d'équipements — exactement ce que cette architecture évite. On échantillonne
    les équipements les plus significatifs (ceux qui portent des alertes,
    puis les autres), et l'écran indique sur combien d'équipements la courbe
    porte. Une moyenne sur douze équipements annoncée comme telle vaut mieux
    qu'une moyenne sur tout le parc qui met une minute à s'afficher.
    """
    nodes = await live_service.get_nodes()
    ranked = sorted(nodes, key=lambda n: -n.get("alerts", 0))[:sample]
    window_start, window_end = history_service.resolve_window(period, None, None)

    results = await asyncio.gather(
        *(
            history_service.fetch_node_series(node, metric_type, window_start, window_end)
            for node in ranked
        ),
        return_exceptions=True,
    )

    # Moyenne par horodatage. Les points ne tombent pas forcément aux mêmes
    # instants d'un équipement à l'autre : on regroupe à la minute, ce qui
    # est plus fin que le pas de collecte de n'importe quelle sonde.
    buckets: dict[str, list[float]] = {}
    contributing = 0
    for result in results:
        if isinstance(result, BaseException) or not result.get("points"):
            continue
        contributing += 1
        for point in result["points"]:
            minute = str(point["at"])[:16]
            buckets.setdefault(minute, []).append(float(point["value"]))

    points = [
        {"at": minute, "value": round(sum(values) / len(values), 3)}
        for minute, values in sorted(buckets.items())
    ]

    return {
        "metric_type": metric_type,
        "points": points,
        "sampled_nodes": len(ranked),
        "contributing_nodes": contributing,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
    }
