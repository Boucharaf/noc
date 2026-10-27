"""
Suggestions des barres de recherche.

Tout se lit dans l'instantané (Redis, déjà en mémoire du backend) : aucune
requête vers les outils sources à chaque frappe. Les correspondances
ignorent accents et casse (« kuilse » trouve « Kuilsé ») et sont classées :
le texte en tête du libellé, puis en tête d'un mot, puis n'importe où.
"""
from __future__ import annotations

import re
from collections import Counter

from sqlalchemy.orm import Session

from app.services import geo_service, live_service
from integrations.normalize import locality_key

KINDS = ("region", "province", "site", "node", "incident", "alert", "maintenance", "intervention")
_WORD = re.compile(r"[\s\-_./·,()']+")


def _rank(text: str | None, needle: str) -> int | None:
    """0 = commence par, 1 = un mot commence par, 2 = contient ; None sinon."""
    key = locality_key(text)
    if not key or needle not in key:
        return None
    if key.startswith(needle):
        return 0
    if any(word.startswith(needle) for word in _WORD.split(key)):
        return 1
    return 2


def _best(needle: str, *texts: str | None) -> int | None:
    ranks = [rank for rank in (_rank(text, needle) for text in texts) if rank is not None]
    return min(ranks) if ranks else None


async def suggest(db: Session, q: str, kinds: tuple[str, ...] = KINDS, limit: int = 8) -> list[dict]:
    needle = locality_key(q)
    if len(needle) < 2:
        return []
    nodes, alerts, incidents, _index = await geo_service.snapshot(db)
    found: list[tuple[int, int, str, dict]] = []  # (rang, ordre du type, libellé, suggestion)
    order = {kind: i for i, kind in enumerate(KINDS)}

    def add(rank, kind, item):
        if rank is not None:
            found.append((rank, order[kind], item["label"].casefold(), item))

    # Localités, avec leur effectif : on sait avant de cliquer ce qu'on verra.
    for level in ("region", "province", "site"):
        if level not in kinds:
            continue
        counts = Counter(node.get(level) for node in nodes if node.get(level))
        parents = {}
        for node in nodes:
            name = node.get(level)
            if name and name not in parents:
                parents[name] = {
                    "region": node.get("region"),
                    "province": node.get("province") if level == "site" else None,
                }
        for name, count in counts.items():
            parent = parents[name]
            add(_rank(name, needle), level, {
                "kind": level,
                "label": name,
                "detail": " · ".join(filter(None, [parent.get("province"),
                                                   parent.get("region") if level != "region" else None,
                                                   f"{count} équip."])),
                "value": name,
                "scope": {
                    "region": name if level == "region" else parent.get("region"),
                    "province": name if level == "province" else parent.get("province"),
                    "site": name if level == "site" else None,
                },
            })

    if "node" in kinds:
        for node in nodes:
            add(_best(needle, node.get("name"), node.get("hostname"), node.get("ip")), "node", {
                "kind": "node",
                "label": node.get("name") or node.get("hostname") or node["id"],
                "detail": " · ".join(filter(None, [node.get("ip"), node.get("site"), node.get("region")])),
                "value": node.get("name") or node.get("hostname"),
                "id": node["id"],
                "state": node.get("state"),
            })

    if "incident" in kinds:
        for record in incidents:
            ref = record.get("ticket_ref") or record.get("ref")
            add(_best(needle, ref, record.get("message"), record.get("node_name")), "incident", {
                "kind": "incident",
                "label": f"{ref} — {record.get('message') or ''}".strip(" —"),
                "detail": " · ".join(filter(None, [record.get("node_name"), record.get("site")])),
                "value": ref,
                "id": record["key"],
                "severity": record.get("severity"),
            })

    if "alert" in kinds:
        seen = set()
        for record in alerts:
            label = record.get("node_name") or ""
            if not label or label in seen:
                continue
            rank = _best(needle, label, record.get("message"))
            if rank is not None:
                seen.add(label)
            add(rank, "alert", {
                "kind": "alert",
                "label": label,
                "detail": f"{record.get('message') or ''}"[:80],
                "value": label,
                "id": record["key"],
                "severity": record.get("severity"),
            })

    for kind, records in (
        ("maintenance", await live_service.get_maintenance() if "maintenance" in kinds else []),
        ("intervention", await live_service.get_work_orders() if "intervention" in kinds else []),
    ):
        for record in records:
            names = [ci.get("name") for ci in record.get("cis") or []]
            add(_best(needle, record.get("ref"), record.get("title"), *names), kind, {
                "kind": kind,
                "label": record.get("title") or record.get("ref") or "",
                "detail": " · ".join(filter(None, [record.get("ref"), *names[:2]])),
                "value": record.get("ref") or record.get("title"),
                "id": record.get("key"),
            })

    found.sort(key=lambda item: item[:3])
    return [item for *_ignored, item in found[:limit]]
