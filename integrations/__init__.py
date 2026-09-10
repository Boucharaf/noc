"""
Connecteurs vers les outils sources du NOC.

Ce paquet est partagé par DEUX consommateurs, et c'\''est la raison de son
existence à la racine du dépôt plutôt que dans collector/ :

  * collector/ l'\''utilise toutes les 300 s pour construire l'\''instantané
    Redis (check / fetch_nodes / fetch_alerts) ;
  * backend/ l'\''utilise à la demande, quand un exploitant ouvre une courbe,
    pour interroger l'\''historique chez l'\''outil source (fetch_history).

Les deux images Docker le copient depuis le contexte racine. Voir
ARCHITECTURE.md, section « L'\''historique — fédéré, jamais recopié ».
"""
from .base import CircuitBreaker, SourceClient, ToolUnavailable
from .config import build_all_clients, build_client, configured_tools, tool_config
from .models import Alert, MetricPoint, Node, ToolHealth, ToolSnapshot, to_jsonable

__all__ = [
    "Alert",
    "CircuitBreaker",
    "MetricPoint",
    "Node",
    "SourceClient",
    "ToolHealth",
    "ToolSnapshot",
    "ToolUnavailable",
    "build_all_clients",
    "build_client",
    "configured_tools",
    "to_jsonable",
    "tool_config",
]
