"""
Orchestration de la collecte pour un outil donné : API (obligatoire) +
BDD restaurée (optionnelle) -> dédoublonnage -> normalisation -> chargement.

Ne connaît aucun détail spécifique à un outil : il manipule uniquement
l'interface commune (fetch_nodes/fetch_incidents/fetch_metrics) exposée
par extract/api/*.py et extract/db/*.py. Ajouter un 7e outil demain ne
touche à aucune ligne de ce fichier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import psycopg2

from ..config import ToolConfig, settings
from ..transform import dedup, identity_resolution, normalize_incidents, normalize_metrics, normalize_nodes
from ..load import load_dimensions, load_facts, load_metrics_timescale
from .status import publish_status

logger = logging.getLogger("noc_etl.collector")


@dataclass
class ToolConnectors:
    name: str
    api_client: Optional[object]  # expose fetch_nodes/fetch_incidents/fetch_metrics/health_check
    db_reader_module: Optional[object]  # module avec les mêmes fonctions, prenant un dsn en 1er argument
    tool_config: ToolConfig


def collect_tool(conn: "psycopg2.extensions.connection", connectors: ToolConnectors, since: datetime):
    """Collecte un seul outil. Toute erreur est capturée et publiée dans
    Redis (status.py) : un outil en panne ne doit jamais interrompre les
    autres, ni faire échouer la tâche Celery globale."""
    name = connectors.name
    try:
        api_ok = connectors.api_client.health_check() if connectors.api_client else False
        if not api_ok:
            logger.warning("Outil %s : API indisponible, cycle ignoré pour l'API", name)

        raw_nodes = connectors.api_client.fetch_nodes() if api_ok else []
        raw_incidents = connectors.api_client.fetch_incidents(since) if api_ok else []
        raw_metrics = connectors.api_client.fetch_metrics(since) if api_ok else []

        if connectors.tool_config.db_restore_enabled and connectors.db_reader_module:
            dsn = connectors.tool_config.db_dsn
            db_nodes = connectors.db_reader_module.fetch_nodes(dsn)
            db_incidents = connectors.db_reader_module.fetch_incidents(dsn, since)
            db_metrics = connectors.db_reader_module.fetch_metrics(dsn, since)
            raw_nodes = dedup.dedup_nodes(raw_nodes, db_nodes)
            raw_incidents = dedup.dedup_incidents(raw_incidents, db_incidents)
            raw_metrics = dedup.dedup_metrics(raw_metrics, db_metrics)

        nodes = normalize_nodes.normalize(raw_nodes)
        incidents = normalize_incidents.normalize(raw_incidents)
        metrics = normalize_metrics.normalize(raw_metrics)

        merge_groups, _unresolved = identity_resolution.resolve(nodes)

        load_dimensions.load_nodes(conn, nodes, merge_groups)
        load_facts.load_incidents(conn, incidents)
        load_metrics_timescale.load_metrics(conn, metrics)

        publish_status(name, ok=True, nb_nodes=len(nodes), nb_incidents=len(incidents), nb_metrics=len(metrics))
    except Exception:  # noqa: BLE001 - isolation volontaire, voir docstring
        logger.exception("Échec de la collecte pour %s", name)
        publish_status(name, ok=False)


def collect_all(conn: "psycopg2.extensions.connection", connectors_by_tool: dict[str, ToolConnectors]):
    since = datetime.now(timezone.utc) - timedelta(seconds=settings.collect_interval_s * 2)
    for connectors in connectors_by_tool.values():
        collect_tool(conn, connectors, since)
