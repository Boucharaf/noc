import logging
import os

logger = logging.getLogger(__name__)


def build_dsn() -> str:
    return (
        f"host={os.getenv('DB_HOST', 'postgres')} "
        f"port={os.getenv('DB_PORT', 5432)} "
        f"dbname={os.getenv('DB_NAME', 'noc_db')} "
        f"user={os.getenv('DB_USER', 'noc_db_user')} "
        f"password={os.getenv('DB_PASSWORD', '')}"
    )


def broker_url() -> str:
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    # DB 1: the backend cache uses the default DB 0 on the same Redis instance.
    db = os.getenv("CELERY_BROKER_DB", "1")
    return f"redis://{host}:{port}/{db}"


def netxms_dsn() -> str:
    """The NetXMS database, read directly — not by a collector.

    Only rebuild_geography.py uses this. The administrative reference data it
    needs (the donnebase schema: régions, provinces, communes, villes, sites
    administratifs) exists nowhere else: the REST API exposes a node's postal
    address but not the reference tables behind it, and the ANPTIC columns on
    object_properties were added straight to the table. Collectors still go
    through the API and must keep doing so.
    """
    return (
        f"host={os.getenv('NETXMS_DB_HOST', 'netxms-db')} "
        f"port={os.getenv('NETXMS_DB_PORT', 5432)} "
        f"dbname={os.getenv('NETXMS_DB_NAME', 'netxms')} "
        f"user={os.getenv('NETXMS_DB_USER', 'netxms')} "
        f"password={os.getenv('NETXMS_DB_PASSWORD', '')}"
    )


# development is the only environment allowed to fall back to a known,
# documented API key (see NOC_API_KEY below) — every other value, including
# an unset/misspelled one, is treated as production and fails closed instead
# of silently authenticating with a key anyone reading this file also has.
ETL_ENV = os.getenv("ETL_ENV", "production").strip().lower()

NOC_API_URL = os.getenv("NOC_API_URL", "http://backend:8000")

NOC_API_KEY = os.getenv("NOC_API_KEY", "").strip()
if not NOC_API_KEY:
    if ETL_ENV == "development":
        NOC_API_KEY = "dev-noc-api-key"
        logger.warning(
            "NOC_API_KEY not set — using the local dev-only default because "
            "ETL_ENV=development. Never rely on this outside a local compose."
        )
    else:
        # Raised at import time, i.e. on worker startup (celery_app.py imports
        # this module) — the previous version instead defaulted NOC_API_KEY to
        # "dev-noc-api-key" unconditionally, so a forgotten env var in prod
        # authenticated successfully with a key documented in this very file,
        # and nothing here would ever have told you.
        raise RuntimeError(
            "NOC_API_KEY is required outside ETL_ENV=development. Set it "
            "before starting the worker — refusing to start with a known "
            "default key."
        )

# How often every configured supervision API is polled. Five minutes is the
# contracted reporting granularity for this dashboard; it is also about as
# often as these tools can be polled without the request itself becoming a
# load problem on the monitoring servers. Raising it delays detection by the
# same amount, since nothing else drives collection.
COLLECT_INTERVAL_S = int(os.getenv("ETL_COLLECT_INTERVAL_S", "300"))
# Where the scheduled end-of-month exports are written (mounted volume).
REPORTS_DIR = os.getenv("REPORTS_DIR", "/reports")

# Redis DB 0 — the backend's cache database, not the broker's DB 1. The
# collector-status key written after each pass is read by the backend to answer
# GET /api/interop/status, so both sides must agree on the database.
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

HTTP_TIMEOUT_S = int(os.getenv("ETL_HTTP_TIMEOUT_S", "15"))

# How long a NetXMS object's identity (name, primary IP, class) is trusted
# without re-asking the server. See extract/netxms.py for why this cache exists;
# the trade is that a node renamed or re-addressed in NetXMS keeps its old
# identity here for up to this long, which only matters for matching it to a
# dim_node. A day is well inside how often that happens.
NETXMS_OBJECT_CACHE_TTL_S = int(os.getenv("NETXMS_OBJECT_CACHE_TTL_S", str(24 * 3600)))

# ── Supervision tool endpoints ──────────────────────────────────────────────
# A collector runs only when its *_API_URL is set; unset tools are skipped
# silently. That is the intended way to turn a tool off — there is no separate
# enable flag — so an endpoint accidentally left blank looks exactly like a
# tool that was never meant to run. Check the startup log, which names the
# collectors it activated, before concluding a tool has nothing to report.

ZABBIX_API_URL = os.getenv(
    "ZABBIX_API_URL", ""
).strip()  # e.g. https://zabbix.anptic.bf/api_jsonrpc.php
ZABBIX_USER = os.getenv("ZABBIX_USER", "")
ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD", "")
ZABBIX_API_TOKEN = os.getenv(
    "ZABBIX_API_TOKEN", ""
)  # Zabbix ≥ 5.4 API token (skips user.login)

NAGIOS_API_URL = os.getenv(
    "NAGIOS_API_URL", ""
).strip()  # e.g. https://nagios.anptic.bf/nagios
NAGIOS_USER = os.getenv("NAGIOS_USER", "")
NAGIOS_PASSWORD = os.getenv("NAGIOS_PASSWORD", "")
NAGIOS_API_KEY = os.getenv("NAGIOS_API_KEY", "")  # sent as X-Auth-Token if set

NETXMS_API_URL = os.getenv(
    "NETXMS_API_URL", ""
).strip()  # e.g. http://netxms.anptic.bf:8000 — base URL, no trailing /v1
NETXMS_USER = os.getenv("NETXMS_USER", "")
NETXMS_PASSWORD = os.getenv("NETXMS_PASSWORD", "")

CENTREON_API_URL = os.getenv(
    "CENTREON_API_URL", ""
).strip()  # e.g. https://centreon.anptic.bf/centreon/api/latest
CENTREON_USER = os.getenv("CENTREON_USER", "")
CENTREON_PASSWORD = os.getenv("CENTREON_PASSWORD", "")
CENTREON_API_KEY = os.getenv(
    "CENTREON_API_KEY", ""
)  # static X-AUTH-TOKEN, alternative to user/password login

ITOP_API_URL = os.getenv(
    "ITOP_API_URL", ""
).strip()  # e.g. https://itop.anptic.bf/webservices/rest.php?version=1.0
ITOP_USER = os.getenv("ITOP_USER", "")
ITOP_PASSWORD = os.getenv("ITOP_PASSWORD", "")