"""
Maintenances planifiées et ordres de travail : rattachement au parc et
fenêtres actives.

Sans dépendance (ni base, ni Redis) : partagé par le collecteur, qui
rattache les CI aux équipements à chaque cycle, et par le backend, qui en
déduit l'état « maintenance » d'un équipement et le marquage des alertes.
"""
from __future__ import annotations

from datetime import datetime


# Statuts iTop d'un changement qui ne neutralise PAS ses équipements : refusé,
# non approuvé, ou clos (terminé, même si sa fenêtre court encore).
_INACTIVE_CHANGE_STATES = {"rejected", "notapproved", "closed"}


def window_is_active(window: dict, at: datetime) -> bool:
    """La fenêtre neutralise-t-elle ses équipements à l'instant `at` ?"""
    if window.get("status") in _INACTIVE_CHANGE_STATES:
        return False
    try:
        start = datetime.fromisoformat(window["start"]) if window.get("start") else None
        end = datetime.fromisoformat(window["end"]) if window.get("end") else None
    except ValueError:
        return False
    return bool(start and start <= at and (end is None or at <= end))


def active_maintenance_keys(windows: list[dict], at: datetime) -> set[str]:
    keys: set[str] = set()
    for window in windows:
        if window_is_active(window, at):
            keys.update(window.get("node_keys") or [])
    return keys


def link_operations(merged: list, *collections: list[dict]) -> None:
    """Rattache les CI des maintenances et ordres de travail au parc.

    Par référence d'abord (identifiant iTop du CI, hostid Zabbix), puis par
    nom technique ou nom affiché — même règle que pour les incidents.
    """
    by_source: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for node in merged:
        for tool, ref in node.sources.items():
            by_source[f"{tool}:{ref}"] = node.id
        for label in (node.hostname, node.name):
            if label:
                by_name.setdefault(label.strip().casefold(), node.id)
    for records in collections:
        for record in records:
            tool = record.get("tool") or "itop"
            keys: list[str] = []
            for ci in record.get("cis") or []:
                key = by_source.get(f"{tool}:{ci.get('ref')}") if ci.get("ref") else None
                if key is None and ci.get("name"):
                    key = by_name.get(str(ci["name"]).strip().casefold())
                if key and key not in keys:
                    keys.append(key)
            record["node_keys"] = keys
