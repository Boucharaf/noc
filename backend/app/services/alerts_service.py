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
from urllib.parse import quote, urlencode

from app.core.config import ALERT_OBSOLETE_DAYS, SEVERITIES
from app.services import geo_service, live_service, node_service
from integrations.config import web_url

logger = logging.getLogger(__name__)


def _age_minutes(since: str | None, now: datetime) -> float | None:
    """Âge calculé côté serveur sur UN instant de référence pour toute la
    liste (INC-12 : deux âges différents pour un même horodatage)."""
    if not since:
        return None
    try:
        at = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0.0, round((now - at).total_seconds() / 60.0, 1))


def source_links(alert: dict) -> dict:
    """Actions rapides (AM-07) : où acquitter / assigner l'alerte, et
    comment en faire un ticket iTop.

    LE NOC NE MODIFIE RIEN DANS LES OUTILS (voir l'en-tête du module) :
    l'acquittement et l'affectation se font dans l'outil source, le ticket
    dans iTop. Ces liens y mènent directement, pré-remplis quand l'outil le
    permet. Absents si `<OUTIL>_WEB_URL` n'est pas renseignée.
    """
    tool = alert.get("tool") or ""
    base = web_url(tool)
    acknowledge = None
    if base:
        if tool == "zabbix" and alert.get("node_ref"):
            acknowledge = (
                f"{base}/zabbix.php?action=problem.view&filter_set=1"
                f"&hostids%5B%5D={quote(str(alert['node_ref']))}"
            )
        else:
            acknowledge = base
    itop = web_url("itop")
    ticket = None
    if itop and alert.get("kind", "technical") == "technical":
        title = f"[{tool}] {alert.get('node_name') or ''} — {alert.get('message') or ''}".strip()
        ticket = f"{itop}/pages/UI.php?" + urlencode({
            "operation": "new",
            "class": "Incident",
            "default[title]": title[:250],
            "default[description]": (
                f"Alerte {tool} {alert.get('ref')} détectée le {alert.get('since')}. "
                f"Site : {alert.get('site') or 'non renseigné'}."
            ),
        })
    return {"acknowledge": acknowledge, "ticket": ticket}


def is_obsolete(alert: dict, age_minutes: float | None) -> bool:
    """Active depuis plus de ALERT_OBSOLETE_DAYS jours sans acquittement."""
    return (
        age_minutes is not None
        and age_minutes > ALERT_OBSOLETE_DAYS * 1440
        and not alert.get("acknowledged")
    )


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
    confirmed: bool | None = None,
    include_maintenance: bool = True,
    limit: int = 500,
) -> dict:
    """Le mur d'alertes complet.

    Rend aussi l'âge de l'instantané : l'interface doit pouvoir signaler des
    données vieillissantes plutôt que de les présenter comme fraîches.
    """
    now = datetime.now(timezone.utc)

    live = await live_service.get_all_alerts()
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
        age = _age_minutes(alert.get("since"), now)

        enriched.append(
            {
                **alert,
                "age_minutes": age,
                "obsolete": is_obsolete(alert, age),
                "links": source_links(alert),
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
        if confirmed is not None and bool(alert.get("frozen")) == confirmed:
            return False
        if not include_maintenance and alert.get("is_maintenance"):
            return False
        return True

    filtered = [a for a in enriched if keep(a)]
    # Ordre de traitement de la file (AM-07) : criticité, puis les NON
    # acquittées d'abord, puis les plus ANCIENNES — la durée d'une alerte
    # non traitée est ce qui presse. Une alerte sans date passe en dernier.
    # Deux tris successifs : le tri de Python est stable, le critère
    # secondaire (date) d'abord, puis le principal (gravité, acquittement).
    filtered.sort(key=lambda a: (not a.get("since"), a.get("since") or ""))
    filtered.sort(key=lambda a: (
        # Les alertes confirmées d'abord ; celles d'une source arrêtée ensuite.
        bool(a.get("frozen")),
        _severity_rank(a.get("severity", "unknown")),
        bool(a.get("acknowledged")),
    ))

    return {
        "alerts": filtered[:limit],
        "total": len(filtered),
        "obsolete_total": sum(1 for a in filtered if a["obsolete"]),
        "obsolete_after_days": ALERT_OBSOLETE_DAYS,
        "computed_at": now.isoformat(),
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
