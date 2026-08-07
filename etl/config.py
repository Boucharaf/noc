import os


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


NOC_API_URL = os.getenv("NOC_API_URL", "http://backend:8000")
NOC_API_KEY = os.getenv("NOC_API_KEY", "dev-noc-api-key")
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
