"""
Dédoublonnage API <-> BDD restaurée, pour un même outil.

Règle (voir architecture, section 3.4) : l'API est toujours prioritaire.
La BDD restaurée n'ajoute que ce que l'API n'a pas donné — jamais
d'écrasement, jamais de fusion de champs entre les deux sources pour une
même clé.

Clé de dédoublonnage :
    - incidents / nœuds : (source_tool, external_id ou external_ref)
    - métriques : (source_tool, node_external_ref, metric_type, time)
      -- le timestamp fait partie de la clé car une métrique est une
      série, pas une entité identifiable autrement.
"""
from __future__ import annotations


def dedup_incidents(api_incidents: list[dict], db_incidents: list[dict]) -> list[dict]:
    api_keys = {(i["source_tool"], i["external_id"]) for i in api_incidents}
    extra = [i for i in db_incidents if (i["source_tool"], i["external_id"]) not in api_keys]
    return api_incidents + extra


def dedup_nodes(api_nodes: list[dict], db_nodes: list[dict]) -> list[dict]:
    api_keys = {(n["source_tool"], n["external_ref"]) for n in api_nodes}
    extra = [n for n in db_nodes if (n["source_tool"], n["external_ref"]) not in api_keys]
    return api_nodes + extra


def dedup_metrics(api_metrics: list[dict], db_metrics: list[dict]) -> list[dict]:
    api_keys = {
        (m["source_tool"], m["node_external_ref"], m["metric_type"], m["time"])
        for m in api_metrics
    }
    extra = [
        m
        for m in db_metrics
        if (m["source_tool"], m["node_external_ref"], m["metric_type"], m["time"]) not in api_keys
    ]
    return api_metrics + extra
