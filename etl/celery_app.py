import logging
import os

from celery import Celery
from celery.schedules import crontab

from config import COLLECT_INTERVAL_S, METRICS_COLLECT_INTERVAL_S, broker_url

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [etl] %(levelname)s %(message)s",
)

app = Celery("etl", broker=broker_url(), include=["pipelines.tasks"])

app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # Bound one collection pass (4 tools × login+fetch+ingest) and drop a tick
    # instead of piling them up if a supervision API or the backend is down.
    task_time_limit=240,
    beat_schedule={
        # batch poll of the configured supervision-tool APIs
        # (Zabbix/Nagios/NetXMS/Centreon) every 5 minutes by default.
        "collect-supervision-events": {
            "task": "etl.collect_supervision",
            "schedule": float(COLLECT_INTERVAL_S),
            "options": {"expires": COLLECT_INTERVAL_S},
        },
        # nightly recompute of the monthly KPI materialized view.
        "refresh-kpi-view-nightly": {
            "task": "etl.refresh_kpi_view",
            "schedule": crontab(hour=2, minute=0),
        },
        # automatic end-of-month report, archived after the refresh.
        "generate-monthly-report": {
            "task": "etl.generate_monthly_report",
            "schedule": crontab(day_of_month=1, hour=2, minute=30),
        },
        # performance/availability metrics — own cadence, see
        # config.METRICS_COLLECT_INTERVAL_S for why it's not tighter by default.
        "collect-metrics": {
            "task": "etl.collect_metrics",
            "schedule": float(METRICS_COLLECT_INTERVAL_S),
            "options": {"expires": METRICS_COLLECT_INTERVAL_S},
        },
        # maintenance windows currently active in each tool, same cadence as
        # incident collection (see collect_maintenance_windows docstring).
        "collect-maintenance-windows": {
            "task": "etl.collect_maintenance_windows",
            "schedule": float(COLLECT_INTERVAL_S),
            "options": {"expires": COLLECT_INTERVAL_S},
        },
        # full CMDB equipment inventory (iTop) for the coverage KPI — once a
        # day, well off the incident-collection cadence (see task docstring).
        "sync-asset-inventory-daily": {
            "task": "etl.sync_asset_inventory",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
