"""
Maintenances planifiées et interventions — lues dans les outils, en
lecture seule.

D'OÙ ELLES VIENNENT. Le NOC ne tient plus son propre registre :
  * une maintenance planifiée est un CHANGEMENT iTop (dates de début et de
    fin, CI impactés), ou une maintenance déclarée dans Zabbix ;
  * une intervention est un ORDRE DE TRAVAIL iTop (équipe, agent, dates),
    rattaché au ticket qui l'a motivée.
Le collecteur les relit à chaque cycle et rattache leurs CI aux équipements
du parc (collector/operations.py). Les planifier, les affecter, les clore :
cela se fait dans iTop (ou Zabbix), qui reste la référence — comme pour les
incidents.

CE QU'UNE MAINTENANCE EN COURS FAIT DANS LE NOC. Elle ne masque pas
l'alerte : elle la MARQUE, et l'équipement passe à l'état « maintenance »
(node_service.apply_maintenance_windows). Une coupure voulue n'est pas une
panne : elle est exclue de la disponibilité et des SLA.

Les anciennes tables ops_maintenance_window et ops_field_intervention ne
sont plus lues ; elles sont conservées en base le temps d'en exporter le
contenu.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import geo_service, live_service
from collector.operations import window_is_active


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _timing(record: dict, now: datetime) -> str:
    """`active`, `upcoming` ou `past` — calculé ici, une fois pour tous les
    écrans, plutôt que redéduit de deux dates par chaque client."""
    if record.get("kind") in ("change", "maintenance") and window_is_active(record, now):
        return "active"
    start, end = _parse(record.get("start")), _parse(record.get("end"))
    if start and start > now:
        return "upcoming"
    if end and end < now:
        return "past"
    if record.get("kind") is None:  # ordre de travail
        return "past" if record.get("status") == "closed" else "active"
    return "past" if record.get("status") == "closed" else "active"


def _enrich(record: dict, nodes_by_id: dict[str, dict], now: datetime) -> dict:
    nodes = [nodes_by_id[key] for key in record.get("node_keys") or [] if key in nodes_by_id]
    return {
        **record,
        "timing": _timing(record, now),
        "nodes": [
            {
                "id": node["id"],
                "name": node.get("name"),
                "state": node.get("state"),
                "site": node.get("site"),
                "province": node.get("province"),
                "region": node.get("region"),
            }
            for node in nodes[:50]
        ],
        "nodes_total": len(nodes),
        "sites": sorted({node["site"] for node in nodes if node.get("site")}),
        "unmatched_cis": [
            ci for ci in record.get("cis") or []
            if not record.get("node_keys")
        ],
    }


async def _filtered(records: list[dict], region, province, site, search) -> tuple[list[dict], dict]:
    nodes = await live_service.get_nodes()
    nodes_by_id = {node["id"]: node for node in nodes}
    scoped = (
        {n["id"] for n in geo_service.scope_nodes(nodes, region, province, site)}
        if (region or province or site)
        else None
    )
    needle = (search or "").strip().casefold()
    kept = []
    for record in records:
        keys = set(record.get("node_keys") or [])
        if scoped is not None and not keys & scoped:
            continue
        if needle:
            haystack = " ".join(
                str(value or "")
                for value in (
                    record.get("ref"), record.get("title"), record.get("agent"),
                    record.get("team"), (record.get("ticket") or {}).get("ref"),
                    *(ci.get("name") for ci in record.get("cis") or []),
                )
            ).casefold()
            if needle not in haystack:
                continue
        kept.append(record)
    return kept, nodes_by_id


async def list_windows(
    scope: str = "all",
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> dict:
    """Maintenances planifiées (changements iTop, maintenances Zabbix)."""
    now = datetime.now(timezone.utc)
    records, nodes_by_id = await _filtered(
        await live_service.get_maintenance(), region, province, site, search
    )
    windows = [_enrich(record, nodes_by_id, now) for record in records]
    counts = {timing: sum(1 for w in windows if w["timing"] == timing)
              for timing in ("active", "upcoming", "past")}
    if scope != "all":
        windows = [w for w in windows if w["timing"] == scope]
    order = {"active": 0, "upcoming": 1, "past": 2}
    windows.sort(key=lambda w: (order[w["timing"]], w.get("start") or ""))
    return {
        "windows": windows,
        "counts": counts,
        "nodes_in_maintenance": len({
            key for w in windows if w["timing"] == "active" for key in w.get("node_keys") or []
        }),
    }


async def list_work_orders(
    status: str = "all",
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> dict:
    """Interventions : ordres de travail iTop, ouverts et récents."""
    now = datetime.now(timezone.utc)
    records, nodes_by_id = await _filtered(
        await live_service.get_work_orders(), region, province, site, search
    )
    orders = [_enrich(record, nodes_by_id, now) for record in records]
    counts = {
        "open": sum(1 for o in orders if o.get("status") != "closed"),
        "closed": sum(1 for o in orders if o.get("status") == "closed"),
        "unassigned": sum(1 for o in orders if o.get("status") != "closed" and not o.get("agent")),
    }
    if status == "open":
        orders = [o for o in orders if o.get("status") != "closed"]
    elif status == "closed":
        orders = [o for o in orders if o.get("status") == "closed"]
    orders.sort(key=lambda o: (o.get("status") == "closed", o.get("start") or ""), reverse=False)
    return {"work_orders": orders, "counts": counts}
