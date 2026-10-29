"""
Le mur d'alertes — les alertes actives de l'instantané Redis (Zabbix,
Centreon, NetXMS, Nagios, NSP, et les tickets iTop), rattachées à leur
équipement et marquées de leur maintenance.

TOUT VIENT DES OUTILS. Le NOC ne crée ni ne traite d'alerte : acquittement,
affectation et clôture se font dans l'outil source ou dans iTop, et c'est
ce que l'outil en dit qui est affiché.

LA MAINTENANCE PLANIFIÉE ne supprime pas une alerte, elle la MARQUE. La
distinction compte : un exploitant doit pouvoir voir qu'un site est en
coupure programmée — sinon il croit à un trou de supervision et lance une
intervention pour rien. En revanche, une alerte marquée est exclue des
indicateurs, parce qu'une coupure voulue n'est pas une panne.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import SEVERITIES
from app.services import geo_service, live_service, node_service

logger = logging.getLogger(__name__)


def _severity_rank(severity: str) -> int:
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return len(SEVERITIES)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def _covered_by_maintenance(windows: list[dict], node_key: str | None) -> dict | None:
    """Maintenance en cours (changement iTop, maintenance Zabbix) visant
    l'équipement de cette alerte, s'il y en a une."""
    if not node_key:
        return None
    return next((w for w in windows if node_key in (w.get("node_keys") or [])), None)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
async def list_alerts(
    severity: str | None = None,
    tool: str | None = None,
    kind: str | None = None,
    site: str | None = None,
    organisation: str | None = None,
    region: str | None = None,
    province: str | None = None,
    search: str | None = None,
    node_type: str | None = None,
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
                "province": node.get("province") if node else None,
                "region": node.get("region") if node else None,
            }
        )

    # -- maintenance ------------------------------------------------------
    windows = await node_service.active_windows(now)

    enriched: list[dict] = []
    for alert in alerts:
        window = _covered_by_maintenance(windows, alert.get("node_key"))

        enriched.append(
            {
                **alert,
                "kind": alert.get("kind", "technical"),
                # Acquittement tel que l'outil source le publie.
                "acknowledged": bool(alert.get("acknowledged")),
                "acknowledged_at": alert.get("acknowledged_at"),
                "is_maintenance": window is not None,
                "maintenance_reason": node_service.maintenance_label(window) if window else None,
            }
        )

    # -- filtres ----------------------------------------------------------
    # Périmètre territorial : la même règle que tous les écrans
    # (geo_service.scope_nodes). Une alerte sans équipement connu sort du
    # périmètre dès qu'une localité est demandée.
    from app.services.geo_service import scope_nodes

    scoped_ids = (
        {node["id"] for node in scope_nodes(list(nodes.values()), region, province, site)}
        if (region or province or site)
        else None
    )
    needle = (search or "").strip().casefold()

    def keep(alert: dict) -> bool:
        if scoped_ids is not None and alert.get("node_key") not in scoped_ids:
            return False
        if needle and needle not in " ".join(
            str(alert.get(field) or "")
            for field in ("message", "node_name", "site", "province", "region", "tool", "ref")
        ).casefold():
            return False
        if severity and alert.get("severity") != severity:
            return False
        if tool and alert.get("tool") != tool:
            return False
        if kind and alert.get("kind", "technical") != kind:
            return False
        if organisation or node_type:
            node = nodes.get(alert.get("node_key") or "") or {}
            if organisation and node.get("organisation") != organisation:
                return False
            if node_type and node.get("type") != node_type and node.get("node_type") != node_type:
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


async def get_alert(alert_key: str) -> dict | None:
    """Fiche d'une alerte active, avec les caractéristiques de son équipement.

    Une alerte qui a quitté l'instantané est close à la source : son
    historique se lit dans l'outil, le NOC n'en garde pas de copie.
    """
    result = await list_alerts(limit=100000)
    alert = next((a for a in result["alerts"] if a["key"] == alert_key), None)
    if alert is None:
        return None
    nodes = await live_service.get_nodes()
    return {
        **alert,
        "node": _node_facts(nodes, alert.get("node_key")),
        "position": geo_service.position(
            next((n for n in nodes if n.get("id") == alert.get("node_key")), None), nodes
        ),
    }


def _node_facts(nodes: list[dict], node_key: str | None) -> dict | None:
    """Caractéristiques techniques de l'équipement d'une alerte."""
    node = next((item for item in nodes if item.get("id") == node_key), None)
    if node is None:
        return None
    return {
        "id": node["id"],
        "name": node.get("name"),
        "hostname": node.get("hostname"),
        "ip": node.get("ip"),
        "state": node.get("state"),
        "node_type": node.get("node_type"),
        "organisation": node.get("organisation"),
        "site": node.get("site"),
        "province": node.get("province"),
        "region": node.get("region"),
        "sources": node.get("sources") or {},
        "state_conflict": node.get("state_conflict") or {},
        "alerts": node.get("alerts", 0),
        "worst_severity": node.get("worst_severity"),
    }
