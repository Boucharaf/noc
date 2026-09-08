"""
Résolution d'identité inter-outils : construit `dim_node_source_map` en
regroupant les nœuds normalisés (sortie de normalize_nodes.normalize) qui
désignent le même équipement physique vu par plusieurs outils.

Stratégie de correspondance, par ordre de priorité :
    1. Adresse IP identique (la plus fiable — un équipement a une IP de
       gestion stable, indépendante de l'outil qui le supervise).
    2. Nom normalisé identique (minuscules, espaces/tirets réduits) — repli
       si l'IP est absente d'un des deux côtés.

Toute correspondance ambiguë (plusieurs candidats possibles) n'est PAS
fusionnée automatiquement : elle est renvoyée dans `unresolved` pour
validation manuelle plutôt que de risquer une fusion incorrecte qui
fausserait les KPI de couverture de supervision.
"""
from __future__ import annotations

import re
from collections import defaultdict


def _norm_name(name: str) -> str:
    return re.sub(r"[\s\-_]+", "", (name or "").strip().lower())


def resolve(normalized_nodes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Retourne (groupes_fusionnés, non_résolus).

    groupes_fusionnés : liste de groupes, chaque groupe = liste de nœuds
    (dicts source_tool/external_ref) désignant le même équipement.
    non_résolus : nœuds qu'on ne peut rattacher à aucun groupe avec
    certitude -> traités comme équipement isolé (pas d'erreur, juste pas
    de fusion).
    """
    by_ip: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    no_key: list[dict] = []

    for node in normalized_nodes:
        if node.get("ip_address"):
            by_ip[node["ip_address"]].append(node)
        elif node.get("name"):
            by_name[_norm_name(node["name"])].append(node)
        else:
            no_key.append(node)

    groups: list[dict] = []
    unresolved: list[dict] = list(no_key)

    for ip, nodes in by_ip.items():
        tools = {n["source_tool"] for n in nodes}
        if len(tools) == len(nodes):  # un seul nœud par outil pour cette IP -> fusion sûre
            groups.append({"key": f"ip:{ip}", "nodes": nodes})
        else:
            unresolved.extend(nodes)  # plusieurs nœuds du même outil partagent l'IP -> ambigu

    for name, nodes in by_name.items():
        tools = {n["source_tool"] for n in nodes}
        if len(nodes) > 1 and len(tools) == len(nodes):
            groups.append({"key": f"name:{name}", "nodes": nodes})
        else:
            unresolved.extend(nodes)

    return groups, unresolved
