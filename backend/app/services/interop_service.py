"""
Écran Interopérabilité — l'état de la chaîne de collecte, vu par l'exploitant.

C'EST L'ÉCRAN LE PLUS IMPORTANT DU TABLEAU DE BORD, et c'est contre-intuitif.
Tous les autres écrans montrent le réseau ; celui-ci montre si l'on a le
DROIT de croire les autres écrans. Un mur d'alertes vide peut vouloir dire
« tout va bien » ou « le collecteur est mort depuis quatre heures », et
personne ne doit avoir à deviner lequel.

D'où trois règles suivies partout dans ce module :

  * un outil configuré dont le collecteur n'a jamais joint l'API apparaît
    comme « jamais collecté », il ne disparaît pas de la liste ;
  * le message d'erreur brut de l'outil est affiché TEL QUEL — « HTTP 401 »,
    « certificat expiré », « profil REST Services User requis » disent
    chacun quoi faire, là où « intégration en erreur » ne dit rien ;
  * l'âge de l'instantané est toujours rendu, même quand tout va bien.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import COLLECT_INTERVAL_S, SUPERVISION_TOOLS
from app.services import live_service

logger = logging.getLogger(__name__)


def _freshness(checked_at: str | None) -> tuple[float | None, bool]:
    """Âge d'un contrôle et sa péremption.

    Le seuil est de deux cycles : un cycle raté est un incident de parcours,
    deux cycles ratés sont une panne. Alerter au premier ferait clignoter
    l'écran à chaque hoquet réseau, et l'exploitant cesserait de le regarder.
    """
    if not checked_at:
        return None, True
    try:
        at = datetime.fromisoformat(checked_at)
    except (TypeError, ValueError):
        return None, True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - at).total_seconds()
    return age, age > COLLECT_INTERVAL_S * 2


async def status() -> dict:
    """État complet de la chaîne de collecte."""
    tools = await live_service.get_tools_health()

    rows = []
    for tool in tools:
        age, stale = _freshness(tool.get("checked_at"))
        rows.append(
            {
                "tool": tool["tool"],
                "reachable": bool(tool.get("reachable")),
                "never_collected": bool(tool.get("never_collected")),
                "version": tool.get("version"),
                "latency_ms": tool.get("latency_ms"),
                # Message brut de l'outil. Volontairement non reformulé.
                "error": tool.get("error"),
                "checked_at": tool.get("checked_at"),
                "age_s": age,
                "stale": stale,
            }
        )

    # `get_meta` lève si la collecte est arrêtée. Ici on l'attrape : cet
    # écran doit RESTER affichable quand tout le reste ne l'est plus — c'est
    # précisément le moment où l'exploitant en a besoin.
    try:
        meta = await live_service.get_meta()
        collector_running = True
    except live_service.SnapshotUnavailable:
        meta = None
        collector_running = False

    return {
        "collector": {
            "running": collector_running,
            "collected_at": meta.get("collected_at") if meta else None,
            "duration_s": meta.get("duration_s") if meta else None,
            "interval_s": COLLECT_INTERVAL_S,
            "snapshot_age_s": await live_service.snapshot_age_s(),
            "stale": await live_service.is_stale(),
            "nodes": meta.get("nodes") if meta else None,
            "alerts": meta.get("alerts") if meta else None,
        },
        "tools": rows,
        "configured": list(SUPERVISION_TOOLS),
        "merge": (meta or {}).get("merge"),
        "orphan_alerts": (meta or {}).get("orphan_alerts"),
    }


async def merge_report() -> dict:
    """Détail des rapprochements multi-outils.

    Cet écran répond à deux questions du responsable du NOC :
      « le parc affiché est-il le vrai parc, ou compte-t-il des doublons ? »
      « quels équipements ne sont vus que par un seul outil ? »

    La seconde est la plus utile : un équipement vu par un seul outil est un
    point de rupture — si cet outil tombe, on le perd de vue sans le savoir.
    """
    try:
        meta = await live_service.get_meta()
    except live_service.SnapshotUnavailable:
        return {
            "available": False,
            "reason": "Aucun instantané : le collecteur ne publie plus.",
        }

    merge = meta.get("merge") or {}
    raw = merge.get("raw", 0)
    merged = merge.get("merged", 0)
    return {
        "available": True,
        "raw_entries": raw,
        "merged_nodes": merged,
        # Nombre de vues qui ont été repliées sur un équipement existant.
        "duplicates_resolved": max(0, raw - merged),
        "matched_by_ip": merge.get("matched_by_ip", 0),
        "matched_by_name": merge.get("matched_by_name", 0),
        "single_source_nodes": merge.get("single_source", []),
        "orphan_alerts": meta.get("orphan_alerts", 0),
    }
