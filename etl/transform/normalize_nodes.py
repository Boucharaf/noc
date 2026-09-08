"""
Normalise les nœuds bruts (un format par outil, sortie des extracteurs)
vers le schéma commun attendu par `load/load_dimensions.py` :

    {
        "external_refs": [(source_tool, external_ref), ...],  # 1 à N (fusion multi-outils)
        "name": str,
        "ip_address": Optional[str],
        "is_active": bool,
        "ministry_external_ref": Optional[str],   # si connu (généralement via iTop)
        "locality_external_ref": Optional[str],
    }

La fusion multi-outils (un même équipement physique vu par Zabbix ET
NetXMS par ex.) est déléguée à `identity_resolution.py` : ce module se
contente d'homogénéiser les champs, il ne fusionne rien.
"""
from __future__ import annotations


def normalize(raw_nodes: list[dict]) -> list[dict]:
    normalized = []
    for n in raw_nodes:
        normalized.append(
            {
                "source_tool": n["source_tool"],
                "external_ref": str(n["external_ref"]),
                "name": n.get("name") or f"{n['source_tool']}-{n['external_ref']}",
                "ip_address": n.get("ip_address"),
                "is_active": bool(n.get("is_active", True)),
                "ministry_external_ref": n.get("ministry_external_ref"),
                "locality_external_ref": n.get("locality_external_ref"),
                "groups": n.get("groups") or [],
            }
        )
    return normalized
