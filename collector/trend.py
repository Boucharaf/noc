"""
Historique court de l'état du parc — un point par cycle de collecte.

À QUOI IL SERT. Les mini-courbes des tuiles (« la disponibilité monte ou
baisse depuis ce matin ? ») et les flèches de tendance. Les outils sources
ont des courbes par équipement, pas l'état du PARC dans le temps ; et les
agrégats journaliers (rollup) n'ont qu'un point par jour.

CE QUI EST GARDÉ. Pour le réseau entier, chaque région et chaque province :
équipements, états, disponibilité (même règle que live_service.fleet_summary :
nominaux / équipements hors maintenance), alertes, alertes critiques,
incidents iTop. Pas les sites : des milliers de séries pour un usage rare.
Une liste Redis plafonnée (24 h à la cadence de collecte), jamais recopiée
ailleurs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from integrations.models import Alert

from .merge import MergedNode, _normalise_name

# Abréviations : chaque point est répété ~60 fois par cycle et 288 fois par
# jour ; des clés courtes divisent par trois la taille de la liste.
_STATES = {"up": "up", "down": "down", "degraded": "deg", "silent": "unk", "unknown": "unk",
           "maintenance": "mnt"}


def _empty() -> dict:
    return {"n": 0, "up": 0, "down": 0, "deg": 0, "unk": 0, "mnt": 0, "al": 0, "cr": 0, "inc": 0}


def sample(
    merged: list[MergedNode],
    alerts: list[Alert],
    maintenance_keys: set[str],
    at: datetime,
) -> dict:
    """Un point de l'historique : réseau (`g`), régions (`r`), provinces (`p`)."""
    total = _empty()
    regions: dict[str, dict] = defaultdict(_empty)
    provinces: dict[str, dict] = defaultdict(_empty)

    def buckets(node: MergedNode | None):
        yield total
        if node is not None:
            if node.region:
                yield regions[node.region]
            if node.province:
                yield provinces[node.province]

    for node in merged:
        state = "maintenance" if node.id in maintenance_keys else node.state
        for bucket in buckets(node):
            bucket["n"] += 1
            if state in _STATES:
                bucket[_STATES[state]] += 1

    # Même rattachement que merge.attach_alerts : référence, puis nom.
    by_source = {f"{tool}:{ref}": node for node in merged for tool, ref in node.sources.items()}
    by_name: dict[str, MergedNode] = {}
    for node in merged:
        for label in (node.hostname, node.name):
            key = _normalise_name(label)
            if key:
                by_name.setdefault(key, node)
    for alert in alerts:
        node = by_source.get(f"{alert.tool}:{alert.node_ref}") if alert.node_ref else None
        if node is None and alert.node_name:
            node = by_name.get(_normalise_name(alert.node_name))
        for bucket in buckets(node):
            if alert.kind == "itsm_ticket":
                bucket["inc"] += 1
            else:
                bucket["al"] += 1
                if alert.severity == "critical":
                    bucket["cr"] += 1

    def finish(bucket: dict) -> dict:
        measured = bucket["n"] - bucket["mnt"]
        bucket["av"] = round(100.0 * bucket["up"] / measured, 2) if measured else None
        return bucket

    return {
        "at": at.isoformat(),
        "g": finish(total),
        "r": {name: finish(bucket) for name, bucket in regions.items()},
        "p": {name: finish(bucket) for name, bucket in provinces.items()},
    }
