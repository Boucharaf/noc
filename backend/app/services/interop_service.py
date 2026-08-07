"""State of the supervision-tool integrations, for the Interopérabilité view.

Combines two sources, because neither alone answers the question the page asks:

  * the ETL worker's last collection pass, read from the Redis key it rewrites
    every poll — whether each tool answered, and what it returned;
  * incident counts for the month, grouped by the tool that *reported* them.

The second deliberately groups on fact_incident.source_tool and not
dim_node.source_tool. Those are different facts: the first is who raised the
incident, the second is which tool is nominally responsible for monitoring that
node. They disagree in practice, and only the first one belongs on a card
labelled with a tool's name.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.redis_client import redis_client
from app.models.incident import Incident
from app.services.kpi_service import month_start

logger = logging.getLogger(__name__)

# Written by etl/pipelines/status.py after every collection pass.
STATUS_KEY = "noc:collector:status"

# Every tool the ETL can collect from. Fixed here rather than derived from the
# status payload so a tool that is switched off, or whose collector has never
# run, still appears on the page as "not configured" instead of vanishing.
TOOLS = ("zabbix", "nagios", "netxms", "centreon", "itop")


def _read_status() -> dict | None:
    try:
        raw = redis_client.get(STATUS_KEY)
    except Exception as exc:  # Redis down must not take the page down
        logger.warning("Collector status read failed: %s", exc)
        return None
    return json.loads(raw) if raw else None


def _incidents_by_tool(db: Session, month: int, year: int) -> dict[str, int]:
    period_start = month_start(month, year)
    rows = db.execute(
        select(Incident.source_tool, func.count(Incident.id))
        .where(func.date_trunc("month", Incident.detected_at) == period_start)
        .group_by(Incident.source_tool)
    ).all()
    return {tool: int(count) for tool, count in rows}


def get_interop_status(db: Session, month: int, year: int) -> dict:
    status = _read_status()
    counts = _incidents_by_tool(db, month, year)
    per_tool = (status or {}).get("tools") or {}

    tools = []
    for name in TOOLS:
        entry = per_tool.get(name)
        if status is None:
            # No status key at all: the worker has not published within the
            # key's lifetime, so nothing can be claimed about any tool.
            state, detail = "unknown", "Collecteur inactif ou injoignable"
        elif entry is None:
            state, detail = "not_configured", "Aucun endpoint configuré"
        elif entry.get("error"):
            state, detail = "error", entry["error"]
        elif entry.get("failed"):
            state = "degraded"
            detail = f"{entry['failed']} incident(s) non enregistré(s)"
        else:
            state, detail = "ok", "Collecte réussie"
        tools.append(
            {
                "tool": name,
                "state": state,
                "detail": detail,
                "fetched": (entry or {}).get("fetched"),
                "ingested": (entry or {}).get("ingested"),
                "incidents_this_month": counts.get(name, 0),
            }
        )

    return {
        "collected_at": (status or {}).get("collected_at"),
        "interval_seconds": (status or {}).get("interval_seconds"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tools": tools,
    }
