import os

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Redis Cache Constants
CACHE_TTL = int(os.getenv("CACHE_TTL", 300))  # 5 minutes
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# PostgreSQL Constants
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "noc_db_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "noc_db_password")
DB_NAME = os.getenv("DB_NAME", "noc_db")

# Security
JWT_SECRET = os.getenv("SECRET_KEY", "dev-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

# Static bearer key used by supervision tools (Centreon/Zabbix webhooks) to call /api/incidents/ingest
NOC_API_KEY = os.getenv("NOC_API_KEY", "dev-noc-api-key")

# CORS
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost,http://localhost:5173"
    ).split(",")
    if origin.strip()
]

# External APIs
ITOP_URL = os.getenv("ITOP_URL", "https://itop.anptic.bf/webservices/rest.php")
ITOP_USER = os.getenv("ITOP_USER", "api_user")
ITOP_PASS = os.getenv("ITOP_PASS", "api_password")
# Organization (org_id) tickets are created under — "My Company/Department" (id 1)
# on a fresh iTop install.
ITOP_ORG_ID = os.getenv("ITOP_ORG_ID", "1")

# Notifications (spec §7 step 6 — SMS + email on critical incidents)
NOTIFICATIONS_ENABLED = os.getenv("NOTIFICATIONS_ENABLED", "false").lower() == "true"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
NOC_SMS_RECIPIENTS = [
    n.strip() for n in os.getenv("NOC_SMS_RECIPIENTS", "").split(",") if n.strip()
]
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noc@anptic.bf")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
NOC_EMAIL_RECIPIENTS = [
    e.strip() for e in os.getenv("NOC_EMAIL_RECIPIENTS", "").split(",") if e.strip()
]

# Web Push (browser/PWA push notifications on critical incidents)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "noc@anptic.bf")

# Rate limiting (spec §10.1 — per-IP, per-minute)
RATE_LIMIT_READ_PER_MIN = int(os.getenv("RATE_LIMIT_READ_PER_MIN", 100))
RATE_LIMIT_INGEST_PER_MIN = int(os.getenv("RATE_LIMIT_INGEST_PER_MIN", 10))
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"

# Materialized view refresh: the spec (§2.2/§10.2) refreshes nightly at 02:00 via
# the ETL beat task; the synchronous refresh-on-write below keeps small demo
# datasets interactive. Disable in production.
SYNC_MV_REFRESH = os.getenv("SYNC_MV_REFRESH", "true").lower() == "true"
