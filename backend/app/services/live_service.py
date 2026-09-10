"""
Lecture de l'état courant — l'unique source des écrans « maintenant ».

Ce module ne parle qu'à Redis. Aucune requête SQL, aucun appel vers un outil
source : le chemin chaud du tableau de bord doit rester à quelques dizaines
de microsecondes, quel que soit le nombre d'opérateurs connectés.

LA DISTINCTION QUI COMPTE. `read_*` peut rendre trois choses, et les
confondre serait le pire bogue de ce tableau de bord :

    None  -> la collecte ne tourne plus (clé expirée) ;
    []    -> la collecte tourne et ne trouve rien ;
    [...] -> la collecte tourne et a trouvé.

`SnapshotUnavailable` matérialise le premier cas. Les routes le transforment
en 503 accompagné de l'heure du dernier instantané connu, ce qui donne à
l'exploitant l'information dont il a besoin — « la collecte est arrêtée
depuis 14 h 07 » — au lieu d'un parc vide qui ressemble à un réseau en pleine
forme.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import COLLECT_INTERVAL_S, SUPERVISION_TOOLS
from app.db.redis_client import get_store

logger = logging.getLogger(__name__)


class SnapshotUnavailable(RuntimeError):
    """L'instantané est absent ou périmé : le collecteur ne publie plus."""

    def __init__(self, detail: str = "Collecte interrompue — aucun instantané récent"):
        self.detail = detail
        super().__init__(detail)


async def get_meta() -> dict:
    """Métadonnées du dernier cycle. Lève si la collecte est arrêtée."""
    meta = await get_store().read_meta()
    if meta is None:
        raise SnapshotUnavailable()
    return meta


async def get_nodes() -> list[dict]:
    nodes = await get_store().read_nodes()
    if nodes is None:
        raise SnapshotUnavailable()
    return nodes


async def get_alerts() -> list[dict]:
    alerts = await get_store().read_alerts()
    if alerts is None:
        raise SnapshotUnavailable()
    return alerts


async def get_node(node_id: str) -> dict | None:
    """Un équipement par son identifiant de fusion.

    Une recherche linéaire sur la liste, et non un index Redis par
    équipement : le parc tient en quelques milliers d'entrées, la liste est
    déjà en mémoire du processus après la désérialisation, et maintenir un
    index séparé ajouterait un chemin par lequel les deux représentations
    pourraient diverger.
    """
    for node in await get_nodes():
        if node.get("id") == node_id:
            return node
    return None


async def get_tools_health() -> list[dict]:
    """État de chaque outil configuré.

    Les outils sont énumérés depuis la CONFIGURATION et non depuis les clés
    Redis présentes : un outil configuré dont le collecteur n'a jamais réussi
    à joindre l'API doit apparaître comme « jamais collecté », pas disparaître
    de la page. C'est exactement le cas qu'un exploitant a besoin de voir.
    """
    store = get_store()
    rows = []
    for tool in SUPERVISION_TOOLS:
        health = await store.read_tool_health(tool)
        if health is None:
            rows.append(
                {
                    "tool": tool,
                    "reachable": False,
                    "never_collected": True,
                    "error": "Aucune collecte enregistrée pour cet outil",
                }
            )
        else:
            rows.append({**health, "never_collected": False})
    return rows


async def snapshot_age_s() -> float | None:
    """Âge de l'instantané, en secondes. None si aucun instantané.

    Utilisé par la barre d'état du tableau de bord : au-delà de deux
    intervalles de collecte, l'interface affiche un avertissement plutôt que
    de laisser croire à des données fraîches.
    """
    meta = await get_store().read_meta()
    if not meta or not meta.get("collected_at"):
        return None
    try:
        collected = datetime.fromisoformat(meta["collected_at"])
    except (TypeError, ValueError):
        return None
    if collected.tzinfo is None:
        collected = collected.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - collected).total_seconds()


async def is_stale() -> bool:
    age = await snapshot_age_s()
    return age is None or age > COLLECT_INTERVAL_S * 2


# ---------------------------------------------------------------------------
# Agrégats sur l'instantané
# ---------------------------------------------------------------------------
# Calculés à la volée sur une liste déjà en mémoire, sans cache. Sur quelques
# milliers d'équipements, un décompte coûte moins qu'une lecture Redis
# supplémentaire ; mettre en cache ajouterait une seconde source de vérité
# pour économiser des microsecondes.
async def fleet_summary() -> dict:
    nodes = await get_nodes()
    alerts = await get_alerts()

    by_state: dict[str, int] = {}
    for node in nodes:
        state = node.get("state", "unknown")
        by_state[state] = by_state.get(state, 0) + 1

    by_severity: dict[str, int] = {}
    for alert in alerts:
        severity = alert.get("severity", "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1

    total = len(nodes)
    up = by_state.get("up", 0)
    return {
        "nodes_total": total,
        "nodes_by_state": by_state,
        "alerts_total": len(alerts),
        "alerts_by_severity": by_severity,
        "alerts_unacknowledged": sum(
            1 for a in alerts if not a.get("acknowledged")
        ),
        # Proportion d'équipements joignables. Ce n'est PAS une disponibilité
        # au sens du SLA d'un équipement donné — c'est un indicateur de santé
        # du parc à l'instant présent, et il est nommé pour qu'on ne les
        # confonde pas.
        "fleet_health_pct": round(100.0 * up / total, 2) if total else None,
    }


async def sites_summary() -> list[dict]:
    """Synthèse par site, triée du plus dégradé au plus sain."""
    nodes = await get_nodes()
    sites: dict[str, dict] = {}
    for node in nodes:
        # Les équipements sans localité connue sont regroupés explicitement
        # plutôt qu'écartés : leur nombre est le meilleur indicateur de la
        # qualité des conventions de nommage côté outils sources.
        key = node.get("site") or "Localité non renseignée"
        bucket = sites.setdefault(
            key, {"site": key, "nodes": 0, "down": 0, "degraded": 0, "alerts": 0}
        )
        bucket["nodes"] += 1
        if node.get("state") == "down":
            bucket["down"] += 1
        elif node.get("state") == "degraded":
            bucket["degraded"] += 1
        bucket["alerts"] += node.get("alerts", 0)

    rows = list(sites.values())
    rows.sort(key=lambda r: (-r["down"], -r["degraded"], -r["alerts"], r["site"]))
    return rows
