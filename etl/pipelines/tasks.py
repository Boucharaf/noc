import logging
import os
from datetime import date, datetime, timedelta, timezone

import psycopg2
import redis

from celery_app import app
from config import (
    COLLECT_INTERVAL_S,
    NOC_API_KEY,
    NOC_API_URL,
    REDIS_HOST,
    REDIS_PORT,
    REPORTS_DIR,
    build_dsn,
)
from extract import enabled_collectors
from load.api_client import NocApiClient
from pipelines.collector import load_active_nodes
from transform.normalize import to_ingest_payload

logger = logging.getLogger(__name__)

api_client = NocApiClient(base_url=NOC_API_URL, api_key=NOC_API_KEY)

# Poll-state (last successful collection per tool) lives in Redis so restarts
# don't re-fetch the whole event history.
state_redis = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2
)
STATE_KEY = "etl:last_poll:{tool}"


def _last_poll(tool: str) -> datetime:
    try:
        raw = state_redis.get(STATE_KEY.format(tool=tool))
        if raw:
            return datetime.fromisoformat(raw)
    except redis.RedisError as exc:
        logger.warning("Poll-state read failed for %s: %s", tool, exc)
    # First run (or Redis unavailable): look back two intervals, not all history.
    return datetime.now(timezone.utc) - timedelta(seconds=COLLECT_INTERVAL_S * 2)


def _set_last_poll(tool: str, at: datetime) -> None:
    try:
        state_redis.set(STATE_KEY.format(tool=tool), at.isoformat())
    except redis.RedisError as exc:
        logger.warning("Poll-state write failed for %s: %s", tool, exc)


@app.task(name="etl.collect_supervision", bind=True, max_retries=0)
def collect_supervision(self):
    """
    One batch collection pass (every 5 minutes):
    poll every *configured* supervision tool for new/active problems, map each
    onto a dim_node, and POST them to /api/incidents/ingest. The backend
    deduplicates on (source_tool, external_id), so re-reporting a still-open
    problem is a no-op.

    A tool is configured when its *_API_URL env var is set (see etl/config.py);
    tools without an endpoint are skipped. Failures are isolated per tool — one
    unreachable supervision system never blocks collection from the others.
    """
    collectors = enabled_collectors()
    if not collectors:
        logger.info(
            "No supervision tool configured (set ZABBIX_API_URL / NAGIOS_API_URL / "
            "NETXMS_API_URL / CENTREON_API_URL) — nothing to collect"
        )
        return {"configured": 0}

    all_nodes = load_active_nodes(build_dsn())
    stats = {}
    for tool, fetch_events in collectors.items():
        # iTop tickets reference CIs across every monitored node, not one
        # source_tool's subset — unlike the monitoring-tool collectors it
        # needs the full active-node list to match on.
        nodes = all_nodes if tool == "itop" else [
            n for n in all_nodes if n["source_tool"] == tool
        ]
        started_at = datetime.now(timezone.utc)
        try:
            events = fetch_events(nodes, since=_last_poll(tool))
        except Exception as exc:
            logger.error("[%s] collection failed: %s", tool, exc)
            stats[tool] = {"error": str(exc)}
            continue

        ingested = 0
        for event in events:
            result = api_client.ingest_incident(to_ingest_payload(event))
            if result is not None:
                ingested += 1
        _set_last_poll(tool, started_at)
        stats[tool] = {"fetched": len(events), "ingested": ingested}
        logger.info("[%s] fetched=%d ingested=%d", tool, len(events), ingested)

    return stats


@app.task(name="etl.refresh_kpi_view", bind=True, max_retries=2, default_retry_delay=60)
def refresh_kpi_view(self):
    """
    Nightly 02:00 batch: recompute the monthly KPI materialized view.
    CONCURRENTLY so dashboard reads are never blocked (the view has the unique
    index on (month, node_id) that CONCURRENTLY requires).
    """
    try:
        conn = psycopg2.connect(build_dsn())
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_node_monthly")
        conn.close()
        logger.info("mv_kpi_node_monthly refreshed")
    except psycopg2.Error as exc:
        raise self.retry(exc=exc)


@app.task(
    name="etl.generate_monthly_report",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def generate_monthly_report(self):
    """
    End-of-month automatic export (spec §1.2 « Rapport mensuel », P1).
    Runs on the 1st at 02:30, right after the nightly KPI refresh, and archives
    the previous month's report in PDF and DOCX under REPORTS_DIR.
    """
    last_month = date.today().replace(day=1) - timedelta(days=1)
    month, year = last_month.month, last_month.year

    os.makedirs(REPORTS_DIR, exist_ok=True)
    written = []
    for fmt in ("pdf", "docx"):
        content = api_client.download_monthly_report(month, year, fmt)
        if content is None:
            raise self.retry(exc=RuntimeError(f"Report {fmt} download failed"))
        path = os.path.join(REPORTS_DIR, f"rapport-noc-{year}-{month:02d}.{fmt}")
        with open(path, "wb") as fh:
            fh.write(content)
        written.append(path)

    logger.info("Monthly report archived: %s", ", ".join(written))
    return written
