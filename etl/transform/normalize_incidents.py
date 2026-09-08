"""
Normalise les incidents bruts de chaque outil vers le schéma commun
`fact_incident` (voir sql/schema_facts.sql), calcule MTTA/MTTR, et
applique la classification de cause (causes.py).

Cas particulier Centreon : l'API temps réel ne donne que des services en
état non-OK, sans date de résolution (voir extract/api/centreon_client.py).
La clôture est déduite ici par comparaison entre deux collectes
successives : un incident Centreon "open" qui n'apparaît plus dans le lot
courant est considéré résolu à l'heure de cette collecte.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .causes import classify


def _minutes_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60, 1)


def normalize(raw_incidents: list[dict]) -> list[dict]:
    normalized = []
    for inc in raw_incidents:
        detected = inc.get("detected_at")
        acked = inc.get("acknowledged_at")
        resolved = inc.get("resolved_at")
        normalized.append(
            {
                "source_tool": inc["source_tool"],
                "external_id": str(inc["external_id"]),
                "node_external_ref": (
                    str(inc["node_external_ref"]) if inc.get("node_external_ref") else None
                ),
                "itop_ticket_ref": inc.get("itop_ticket_ref"),
                "status": inc.get("status", "open"),
                "severity": inc.get("severity"),
                "detected_at": detected,
                "acknowledged_at": acked,
                "resolved_at": resolved,
                "mtta_minutes": _minutes_between(detected, acked),
                "mttr_minutes": _minutes_between(detected, resolved),
                "downtime_minutes": _minutes_between(detected, resolved),
                "description": inc.get("description"),
                "cause_category": classify(inc.get("description", "")),
            }
        )
    return normalized


def close_stale_centreon_incidents(
    previous_open_external_ids: set[str], current_raw_incidents: list[dict], now: datetime
) -> list[dict]:
    """Produit les mises à jour de clôture pour les incidents Centreon qui
    étaient ouverts lors du run précédent et ont disparu du lot courant
    (= repassés à l'état OK)."""
    current_ids = {str(i["external_id"]) for i in current_raw_incidents}
    closed_ids = previous_open_external_ids - current_ids
    return [
        {"source_tool": "centreon", "external_id": cid, "status": "resolved", "resolved_at": now}
        for cid in closed_ids
    ]
