"""
État des intégrations, pour la page Interopérabilité.

C'est le point d'intégration le plus direct avec l'ETL, et celui qui
changeait de format entre l'ancienne et la nouvelle version.

L'ancien backend lisait UNE clé Redis `noc:collector:status` contenant un
dictionnaire `{"tools": {...}}`. Le nouvel ETL écrit UNE CLÉ PAR OUTIL,
`noc:etl:status:<outil>`, chacune contenant un objet plat :

    {"tool": "zabbix", "ok": true, "last_run_at": "...",
     "nb_nodes": 128, "nb_incidents": 12, "nb_metrics": 640}

(voir etl/pipelines/status.py::publish_status). Ce module lit ce
nouveau format.

Un statut est jugé périmé si `last_run_at` remonte à plus de trois fois
l'intervalle de collecte : deux cycles peuvent être manqués sans que ce
soit une panne (redémarrage du worker, collecte longue), trois signalent
un problème réel.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import (
    ETL_COLLECT_INTERVAL_S,
    ETL_STATUS_KEY_PREFIX,
    SUPERVISION_TOOLS,
)
from app.db.redis_client import redis_client
from app.services.periods import month_bounds

logger = logging.getLogger(__name__)

STALE_FACTOR = 3


def _read_all_status() -> dict[str, dict]:
    """Lit toutes les clés de statut publiées par l'ETL.

    Retourne un dictionnaire vide si Redis est injoignable — la page doit
    s'afficher en indiquant que le collecteur est inconnu, pas renvoyer
    une erreur 500.
    """
    try:
        keys = redis_client.keys(f"{ETL_STATUS_KEY_PREFIX}*")
    except Exception as exc:
        logger.warning("Lecture du statut ETL impossible : %s", exc)
        return {}

    statuses: dict[str, dict] = {}
    for key in keys:
        tool = key[len(ETL_STATUS_KEY_PREFIX):]
        try:
            raw = redis_client.get(key)
            if raw:
                statuses[tool] = json.loads(raw)
        except Exception as exc:
            logger.warning("Statut illisible pour %s : %s", tool, exc)
    return statuses


def _incidents_by_tool(db: Session, month: int, year: int) -> dict[str, int]:
    """Incidents du mois, groupés par outil AYANT REMONTÉ l'incident.

    On groupe sur `fact_incident.source_tool`, pas sur l'outil qui
    supervise l'équipement (`dim_node_source_map`) : un même équipement
    est souvent vu par plusieurs outils, et seule la première réponde à
    la question posée par une carte portant le nom d'un outil.
    """
    start, end = month_bounds(month, year)
    rows = db.execute(
        text(
            """
            SELECT source_tool, count(*) AS nb
            FROM fact_incident
            WHERE detected_at >= :start AND detected_at < :end
            GROUP BY source_tool
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()
    return {r["source_tool"]: int(r["nb"]) for r in rows}


def _nodes_by_tool(db: Session) -> dict[str, int]:
    """Équipements supervisés par chaque outil (dim_node_source_map)."""
    rows = db.execute(
        text(
            """
            SELECT source_tool, count(DISTINCT node_id) AS nb
            FROM dim_node_source_map
            GROUP BY source_tool
            """
        )
    ).mappings().all()
    return {r["source_tool"]: int(r["nb"]) for r in rows}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def get_interop_status(db: Session, month: int, year: int) -> dict:
    statuses = _read_all_status()
    incident_counts = _incidents_by_tool(db, month, year)
    node_counts = _nodes_by_tool(db)

    now = datetime.now(UTC)
    stale_after = timedelta(seconds=ETL_COLLECT_INTERVAL_S * STALE_FACTOR)

    tools = []
    for name in SUPERVISION_TOOLS:
        entry = statuses.get(name)
        last_run = _parse_dt((entry or {}).get("last_run_at"))

        if entry is None:
            # Aucune clé publiée : soit l'outil est désactivé dans la
            # configuration de l'ETL (etl/config.py), soit son connecteur
            # n'a jamais tourné. On ne peut pas distinguer les deux ici,
            # d'où un libellé qui couvre les deux cas.
            state = "not_configured"
            detail = "Jamais collecté — outil désactivé ou connecteur non exécuté"
        elif last_run is None:
            state, detail = "unknown", "Statut publié sans horodatage exploitable"
        elif now - last_run > stale_after:
            minutes = int((now - last_run).total_seconds() // 60)
            state = "stale"
            detail = f"Dernière collecte il y a {minutes} min — collecteur probablement arrêté"
        elif not entry.get("ok"):
            state = "error"
            detail = "Dernier cycle en échec — voir les journaux du worker Celery"
        else:
            state, detail = "ok", "Collecte réussie"

        tools.append(
            {
                "tool": name,
                "state": state,
                "detail": detail,
                "ok": bool((entry or {}).get("ok")) if entry else None,
                "last_run_at": last_run.isoformat() if last_run else None,
                "nb_nodes": (entry or {}).get("nb_nodes"),
                "nb_incidents": (entry or {}).get("nb_incidents"),
                "nb_metrics": (entry or {}).get("nb_metrics"),
                "nodes_supervised": node_counts.get(name, 0),
                "incidents_this_month": incident_counts.get(name, 0),
            }
        )

    healthy = sum(1 for t in tools if t["state"] == "ok")
    return {
        "generated_at": now.isoformat(),
        "interval_seconds": ETL_COLLECT_INTERVAL_S,
        "tools_total": len(tools),
        "tools_healthy": healthy,
        "tools": tools,
    }
