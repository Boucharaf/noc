import logging
import os
from datetime import date, timedelta

import psycopg2

from celery_app import app
from config import HTTP_TIMEOUT_S, NOC_API_KEY, NOC_API_URL, REPORTS_DIR, build_dsn
from extract import enabled_collectors, enabled_extra_collectors
from load.api_client import NocApiClient
from pipelines.collector import load_active_nodes
from pipelines.status import publish_collector_status
from transform.normalize import (
    to_asset_payload,
    to_ingest_payload,
    to_maintenance_window_payload,
    to_metric_payload,
)

logger = logging.getLogger(__name__)

api_client = NocApiClient(base_url=NOC_API_URL, api_key=NOC_API_KEY, timeout=HTTP_TIMEOUT_S)

# Signal names from extract/__init__.py's _EXTRA_COLLECTORS that feed
# fact_metric — operational_metrics reports real performance numbers,
# host_availability/service_availability report an up/down reading that
# normalize.to_metric_payload() folds onto the same "availability" metric
# type (see that function's docstring).
_METRIC_SIGNALS = ("operational_metrics", "host_availability", "service_availability")


def _nodes_for_tool(all_nodes: list[dict], tool: str) -> list[dict]:
    """Same subsetting collect_supervision uses: iTop's signals reference CIs
    across the whole park, every other tool only ever reports on nodes it is
    itself the source for."""
    if tool == "itop":
        return all_nodes
    return [n for n in all_nodes if n["source_tool"] == tool]


@app.task(name="etl.collect_supervision", bind=True, max_retries=0)
def collect_supervision(self):
    """
    One batch collection pass (every 5 minutes):
    ask every *configured* supervision tool which problems are open right now,
    map each onto a dim_node, and POST them to /api/incidents/ingest/bulk — one
    request per tool per pass. The backend deduplicates on
    (source_tool, external_id), so re-reporting a still-open problem is a no-op
    — which is what makes a missed pass, a failed ingest or a worker restart
    cost nothing: the next pass sees the same state.

    Note that the bulk endpoint does not notify: a pass reconciling a whole
    active set must not page the permanence once per alarm. Single-incident
    webhooks still arrive on /ingest and still notify.

    A tool is configured when its *_API_URL env var is set (see etl/config.py);
    tools without an endpoint are skipped. Failures are isolated per tool — one
    unreachable supervision system, or one failed/malformed ingest response,
    never blocks collection from the others. This isolation covers the whole
    per-tool block (fetch AND ingest): an earlier version only wrapped
    fetch_events() in the try/except below, so a bulk-ingest response missing
    an expected key raised an uncaught KeyError that killed the pass for every
    tool the loop hadn't reached yet, and skipped publish_collector_status()
    entirely. NocApiClient.ingest_incidents_bulk() now also guarantees a safe
    contract on its own (None on any failure, real dict otherwise) — this
    try/except is a second line of defense, not the only one.
    """
    collectors = enabled_collectors()
    if not collectors:
        logger.info(
            "No supervision tool configured (set ZABBIX_API_URL / NAGIOS_API_URL / "
            "NETXMS_API_URL / CENTREON_API_URL) — nothing to collect"
        )
        # Still published, so the dashboard distinguishes "no tool configured"
        # from "the worker has stopped running".
        publish_collector_status({})
        return {"configured": 0}

    all_nodes = load_active_nodes(build_dsn())
    stats = {}
    for tool, fetch_events in collectors.items():
        # iTop tickets reference CIs across every monitored node, not one
        # source_tool's subset — unlike the monitoring-tool collectors it
        # needs the full active-node list to match on.
        nodes = (
            all_nodes
            if tool == "itop"
            else [n for n in all_nodes if n["source_tool"] == tool]
        )
        try:
            events = fetch_events(nodes)

            # One request for the whole pass. Posting incident-by-incident costs
            # a unit of the ingest rate limit each, which a real active-alarm
            # set (NetXMS reports ~1500) exhausts in the first six.
            result = api_client.ingest_incidents_bulk(
                [to_ingest_payload(event) for event in events]
            )
            if result is None:
                ingested = 0
                resolved = 0
                failed = len(events)
            else:
                ingested = result["created"]
                # Alerts the tool stopped reporting: the backend treats the
                # batch as a snapshot and closes them.
                resolved = result["resolved"]
                # Already-open incidents are not failures: every collector
                # re-reports its whole active set each pass, so on a steady
                # system nearly every event is a duplicate of one already
                # recorded.
                failed = result["unknown_node"]
        except Exception as exc:
            logger.error("[%s] collection failed: %s", tool, exc)
            stats[tool] = {"error": str(exc)}
            continue

        # No cursor to hold back: every collector reports the problems that are
        # open right now, so whatever failed here is offered again next pass.
        if failed:
            logger.warning(
                "[%s] %d of %d incident(s) failed to ingest — retried next poll",
                tool,
                failed,
                len(events),
            )
        stats[tool] = {
            "fetched": len(events),
            "ingested": ingested,
            "resolved": resolved,
            "failed": failed,
        }
        logger.info(
            "[%s] fetched=%d ingested=%d resolved=%d",
            tool,
            len(events),
            ingested,
            resolved,
        )

    publish_collector_status(stats)

    return stats


@app.task(name="etl.collect_metrics", bind=True, max_retries=0)
def collect_metrics(self):
    """Batch collection pass for performance/availability metrics.

    Separate task and separate beat schedule from collect_supervision on
    purpose: metrics are a much higher-volume, lower-stakes signal (a missed
    CPU reading is a gap in a graph, not an undetected outage), and coupling
    them to the same task would mean one slow tool's metrics poll delays
    incident collection behind it. Same per-tool failure isolation as
    collect_supervision — see that task's docstring.
    """
    extra = enabled_extra_collectors()
    if not extra:
        publish_collector_status({}, key_suffix="metrics")
        return {"configured": 0}

    all_nodes = load_active_nodes(build_dsn())
    stats = {}
    for tool, signals in extra.items():
        fetch = next((signals[name] for name in _METRIC_SIGNALS if name in signals), None)
        if fetch is None:
            continue
        nodes = _nodes_for_tool(all_nodes, tool)
        try:
            events = fetch(nodes)
            payloads = [
                p for p in (to_metric_payload(e) for e in events) if p is not None
            ]
            result = api_client.ingest_metrics_bulk(payloads)
            failed = 0 if result is not None else len(payloads)
        except Exception as exc:
            logger.error("[%s] metrics collection failed: %s", tool, exc)
            stats[tool] = {"error": str(exc)}
            continue
        stats[tool] = {"fetched": len(events), "ingested": len(payloads) - failed, "failed": failed}
        logger.info("[%s] metrics fetched=%d ingested=%d", tool, len(events), len(payloads) - failed)

    publish_collector_status(stats, key_suffix="metrics")
    return stats


@app.task(name="etl.collect_maintenance_windows", bind=True, max_retries=0)
def collect_maintenance_windows(self):
    """Batch import of maintenance windows currently active in each tool.

    Same 5-minute cadence as collect_supervision (a stale maintenance window
    either suppresses alerts too long or not long enough) but kept as its own
    task for the same isolation reason as collect_metrics.
    """
    extra = enabled_extra_collectors()
    if not extra:
        return {"configured": 0}

    all_nodes = load_active_nodes(build_dsn())
    stats = {}
    for tool, signals in extra.items():
        fetch = signals.get("maintenance_windows")
        if fetch is None:
            continue
        nodes = _nodes_for_tool(all_nodes, tool)
        try:
            events = fetch(nodes)
            payloads = [to_maintenance_window_payload(e) for e in events]
            result = api_client.ingest_maintenance_windows_bulk(payloads)
            failed = 0 if result is not None else len(payloads)
        except Exception as exc:
            logger.error("[%s] maintenance-window collection failed: %s", tool, exc)
            stats[tool] = {"error": str(exc)}
            continue
        stats[tool] = {"fetched": len(events), "ingested": len(payloads) - failed, "failed": failed}

    return stats


@app.task(name="etl.sync_asset_inventory", bind=True, max_retries=2, default_retry_delay=300)
def sync_asset_inventory(self):
    """Daily full sync of the CMDB equipment inventory (iTop), for the
    supervision-coverage KPI — see extract/itop.py's fetch_all_assets()
    docstring for why this needs its own referential rather than reusing
    dim_node. Runs once a day, not every poll: the total park size changes on
    the scale of procurement/decommission, not every five minutes, and a
    full-CMDB query is heavier than any other single collector call here.
    """
    extra = enabled_extra_collectors()
    fetch = extra.get("itop", {}).get("asset_inventory")
    if fetch is None:
        logger.info("[itop] asset inventory sync skipped — ITOP_API_URL not configured")
        return {"configured": 0}

    try:
        assets = fetch(None)
        payloads = [to_asset_payload(a) for a in assets]
        result = api_client.sync_assets_bulk(payloads)
    except Exception as exc:
        logger.error("[itop] asset inventory sync failed: %s", exc)
        raise self.retry(exc=exc)

    if result is None:
        raise self.retry(exc=RuntimeError("Asset sync bulk endpoint failed"))

    logger.info("[itop] asset inventory synced: %d asset(s) fetched", len(assets))
    return {"fetched": len(assets), **result}


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
    End-of-month automatic export.
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