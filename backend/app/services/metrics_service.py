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
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import METRIC_TYPES
from app.services import history_service, live_service, node_service

logger = logging.getLogger(__name__)


async def network_snapshot(
    db: Session, nodes: list[dict] | None = None, records: list[dict] | None = None
) -> dict:
    """Santé du réseau à l'instant présent, sur le périmètre fourni."""
    nodes = await node_service.nodes_with_maintenance(db) if nodes is None else nodes
    summary = await live_service.fleet_summary(nodes, records)

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
        "nodes_unknown": summary["nodes_by_state"].get("unknown", 0),
        "fleet_health_pct": summary["fleet_health_pct"],
        "fleet_availability_pct": summary["fleet_availability_pct"],
        "alerts_total": summary["alerts_total"],
        "alerts_critical": summary["alerts_by_severity"].get("critical", 0),
        "tools_covering": len(
            {tool for node in nodes for tool in (node.get("sources") or {})}
        ),
        # Latence, pertes, débits, CPU… : dernières valeurs relevées par le
        # collecteur, moyennées sur le périmètre.
        **_fleet_averages(nodes, await live_service.get_latest()),
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


# Ordre de préférence quand plusieurs outils mesurent le même équipement —
# le même que history_service.fetch_node_series.
_LATEST_ORDER = ("zabbix", "centreon", "netxms", "nagios", "nsp")

# Moyennes du parc publiées dans l'instantané réseau : champ de la réponse
# pour chaque type de métrique.
_FLEET_AVERAGES = {
    "latency_ms": "avg_latency_ms",
    "packet_loss_pct": "packet_loss_pct",
    "bandwidth_in_mbps": "avg_bandwidth_in_mbps",
    "bandwidth_out_mbps": "avg_bandwidth_out_mbps",
    "cpu_pct": "avg_cpu_pct",
    "ram_pct": "avg_ram_pct",
    "disk_pct": "avg_disk_pct",
    "uptime": "avg_uptime",
}


def _fleet_averages(nodes: list[dict], latest: dict[str, dict[str, float]]) -> dict:
    """Moyennes des dernières valeurs sur le périmètre.

    Chaque équipement compte UNE fois par métrique (premier outil qui la
    mesure, dans l'ordre de préférence) ; la moyenne porte sur les seuls
    équipements qui la mesurent, et ce nombre est publié à côté
    (`metric_nodes`) : une latence moyenne sur 6 équipements d'un parc de
    1 300 ne se lit pas comme une latence du parc.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    reporting = 0
    for node in nodes:
        sources = node.get("sources") or {}
        seen: dict[str, float] = {}
        for tool in _LATEST_ORDER:
            ref = sources.get(tool)
            values = latest.get(f"{tool}:{ref}") if ref else None
            for metric, value in (values or {}).items():
                seen.setdefault(metric, value)
        if seen:
            reporting += 1
        for metric, value in seen.items():
            if metric in _FLEET_AVERAGES:
                sums[metric] = sums.get(metric, 0.0) + value
                counts[metric] = counts.get(metric, 0) + 1
    result = {
        field: (round(sums[metric] / counts[metric], 3) if counts.get(metric) else None)
        for metric, field in _FLEET_AVERAGES.items()
    }
    result["metric_types_available"] = sorted(counts)
    result["metric_nodes"] = counts
    result["nodes_measured"] = reporting
    return result


async def nodes_down(db: Session, nodes: list[dict] | None = None) -> list[dict]:
    """Équipements en panne ou muets, les plus critiques d'abord."""
    nodes = await node_service.nodes_with_maintenance(db) if nodes is None else nodes
    affected = [n for n in nodes if n.get("state") in ("down", "degraded", "unknown")]
    order = {"down": 0, "degraded": 1, "unknown": 2}
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


async def top_nodes(limit: int, db: Session, nodes: list[dict] | None = None) -> list[dict]:
    """Équipements les plus alertants.

    Classement fait sur l'instantané et non sur un historique : la question
    posée est « qui me pose problème MAINTENANT », pas « qui m'a posé
    problème ce mois-ci » — celle-là est dans les KPI.
    """
    nodes = await node_service.nodes_with_maintenance(db) if nodes is None else nodes
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


async def node_latest(node_id: str) -> dict:
    node = await live_service.get_node(node_id)
    if node is None:
        return {"error": "Équipement inconnu de l'instantané courant", "latest": {}}
    result = await history_service.fetch_node_latest(node)
    return {
        "node_id": node_id,
        "node_name": node.get("name"),
        **result,
    }


async def network_series(
    metric_type: str,
    period: str | None = None,
    sample: int = 12,
    site: str | None = None,
    organisation: str | None = None,
    node_type: str | None = None,
    nodes: list[dict] | None = None,
) -> dict:
    """Courbe agrégée du réseau, sur un ÉCHANTILLON d'équipements.

    Interroger tout le parc produirait autant d'appels qu'il y a
    d'équipements — exactement ce que cette architecture évite. On échantillonne
    un échantillon stable réparti sans privilégier les équipements en alerte.
    L'écran indique la taille de l'échantillon et combien d'équipements ont
    réellement fourni des mesures; ce résultat ne prétend pas être le parc
    entier.
    """
    # `nodes` : le périmètre déjà filtré (région, province, site, recherche).
    nodes = await live_service.get_nodes() if nodes is None else nodes
    if site:
        nodes = [node for node in nodes if node.get("site") == site]
    if organisation:
        nodes = [node for node in nodes if node.get("organisation") == organisation]
    if node_type:
        nodes = [node for node in nodes if node.get("node_type") == node_type]
    window_start, window_end = history_service.resolve_window(period, None, None)
    population = len(nodes)
    # On n'échantillonne que les équipements qu'un outil À COURBES voit : la
    # base NetXMS, Nagios et iTop n'en fournissent pas. Tirer parmi tout le
    # parc rendait des courbes vides sur un périmètre dominé par NetXMS, même
    # quand Zabbix y mesurait des équipements.
    measurable_tools = {
        tool
        for node in nodes
        for tool in (node.get("sources") or {})
    }
    measurable_tools = {tool for tool in measurable_tools if history_service.serves_history(tool)}
    candidates = [
        node for node in nodes
        if measurable_tools.intersection((node.get("sources") or {}).keys())
    ]
    ranked = sorted(
        candidates,
        key=lambda node: hashlib.sha256(
            f"{period or '24h'}|{metric_type}|{node.get('id', '')}".encode()
        ).digest(),
    )[:sample]

    results = await asyncio.gather(
        *(
            history_service.fetch_node_series(node, metric_type, window_start, window_end)
            for node in ranked
        ),
        return_exceptions=True,
    )

    # Moyenne par minute et par équipement, puis entre équipements. Sans
    # cette étape, une source qui publie plus de points pèse davantage dans
    # la moyenne qu'une source moins fréquente.
    buckets: dict[str, dict[str, list[float]]] = {}
    contributing = 0
    node_ranking = []
    source_errors = []
    for node, result in zip(ranked, results):
        if isinstance(result, BaseException):
            source_errors.append(
                {"node_id": node["id"], "error": str(result)}
            )
            continue
        for error in result.get("errors", []):
            source_errors.append({"node_id": node["id"], **error})
        if not result.get("points"):
            continue
        contributing += 1
        values = [float(point["value"]) for point in result["points"]]
        node_ranking.append(
            {
                "node_id": node["id"],
                "node_name": node.get("name"),
                "site": node.get("site"),
                "avg_value": round(sum(values) / len(values), 3),
                "max_value": round(max(values), 3),
                "nb_points": len(values),
            }
        )
        for point in result["points"]:
            at = datetime.fromisoformat(point["at"]).astimezone(timezone.utc)
            minute = at.replace(second=0, microsecond=0).isoformat()
            buckets.setdefault(minute, {}).setdefault(node["id"], []).append(
                float(point["value"])
            )

    points = [
        {
            "at": minute,
            "contributing_nodes": len(node_values),
            "value": round(
                sum(sum(values) / len(values) for values in node_values.values())
                / len(node_values),
                3,
            ),
        }
        for minute, node_values in sorted(buckets.items())
    ]

    return {
        "metric_type": metric_type,
        "points": points,
        "sampled_nodes": len(ranked),
        "population_nodes": population,
        # Équipements du périmètre vus par un outil qui fournit des courbes.
        "measurable_nodes": len(candidates),
        "contributing_nodes": contributing,
        "sample_coverage_pct": (
            round(100.0 * len(ranked) / len(candidates), 1) if candidates else 0.0
        ),
        "sampled_contribution_pct": (
            round(100.0 * contributing / len(ranked), 1) if ranked else 0.0
        ),
        "sampling_method": "stable_hash_sample",
        "source_errors": source_errors,
        "node_ranking": node_ranking,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
    }
