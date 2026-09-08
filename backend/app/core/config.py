"""
Configuration du backend NOC.

Point d'alignement principal avec l'ETL : le backend lit la MÊME base que
celle où l'ETL écrit, via la MÊME variable d'environnement
`NOC_WAREHOUSE_DSN` (voir etl/config.py::WarehouseConfig et etl/.env.example).
Il n'y a plus de base `noc_db` distincte : l'entrepôt est la source unique.

Idem pour Redis : `REDIS_URL` est la variable que l'ETL utilise déjà pour
publier son statut de collecte (etl/pipelines/status.py). Le backend s'y
connecte avec la même URL pour lire ces clés.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _csv(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Journalisation
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ---------------------------------------------------------------------------
# Entrepôt (partagé avec l'ETL)
# ---------------------------------------------------------------------------
# Priorité à NOC_WAREHOUSE_DSN pour n'avoir qu'une seule variable à régler
# pour l'ETL et le backend. Les variables DB_* restent acceptées en repli
# pour les déploiements Docker qui composent l'URL morceau par morceau.
def _warehouse_dsn() -> str:
    dsn = os.getenv("NOC_WAREHOUSE_DSN")
    if dsn:
        return dsn
    from urllib.parse import quote_plus

    user = quote_plus(os.getenv("DB_USER", "noc"))
    password = quote_plus(os.getenv("DB_PASSWORD", "noc"))
    host = os.getenv("DB_HOST", "postgres")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "noc_warehouse")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


WAREHOUSE_DSN = _warehouse_dsn()

DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))


# ---------------------------------------------------------------------------
# Redis (partagé avec l'ETL)
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

# Préfixe exact des clés écrites par etl/pipelines/status.py. Toute
# modification de cette constante côté ETL doit être répercutée ici, sinon
# la page Interopérabilité affichera tous les outils comme injoignables.
ETL_STATUS_KEY_PREFIX = os.getenv("ETL_STATUS_KEY_PREFIX", "noc:etl:status:")

# Intervalle de collecte de l'ETL (etl/config.py::collect_interval_s). Sert
# à décider à partir de quand un statut publié est considéré comme périmé.
ETL_COLLECT_INTERVAL_S = int(os.getenv("COLLECT_INTERVAL_S", "300"))

# Outils du périmètre. Fixés ici plutôt que déduits des clés Redis : un
# outil dont le collecteur n'a jamais tourné doit apparaître comme
# « jamais collecté », pas disparaître de la page.
SUPERVISION_TOOLS = tuple(
    _csv("SUPERVISION_TOOLS", "zabbix,itop,netxms,centreon,nagios,nsp")
)


# ---------------------------------------------------------------------------
# Sécurité
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("SECRET_KEY", "dev-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRATION_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "7"))

# Clé statique présentée par l'ETL sur les routes /api/internal/*.
# Sans valeur, ces routes répondent 503 : mieux vaut une intégration
# visiblement non configurée qu'un endpoint interne ouvert.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# Cookie du refresh token. `secure=True` par défaut, ce qui est le
# comportement correct derrière le reverse proxy TLS. Ne passer à false que
# pour un dev local servi en http://.
REFRESH_COOKIE_SECURE = _bool("REFRESH_COOKIE_SECURE", True)

CORS_ORIGINS = _csv("CORS_ORIGINS", "http://localhost,http://localhost:5173")

RATE_LIMIT_ENABLED = _bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_READ_PER_MIN = int(os.getenv("RATE_LIMIT_READ_PER_MIN", "100"))
RATE_LIMIT_WRITE_PER_MIN = int(os.getenv("RATE_LIMIT_WRITE_PER_MIN", "30"))


# ---------------------------------------------------------------------------
# Veilleur d'incidents (remplace l'ancienne ingestion par webhook)
# ---------------------------------------------------------------------------
# Les incidents n'arrivent plus par HTTP : l'ETL les écrit directement dans
# fact_incident. Le backend les découvre en interrogeant périodiquement la
# table, et c'est ce veilleur qui déclenche notifications et WebSocket.
WATCHER_ENABLED = _bool("WATCHER_ENABLED", True)
WATCHER_INTERVAL_S = int(os.getenv("WATCHER_INTERVAL_S", "30"))
# Sévérités normalisées qui déclenchent une notification sortante.
WATCHER_NOTIFY_SEVERITIES = tuple(_csv("WATCHER_NOTIFY_SEVERITIES", "critical,high"))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
NOTIFICATIONS_ENABLED = _bool("NOTIFICATIONS_ENABLED", False)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_API_KEY_SID = os.getenv("TWILIO_API_KEY_SID", "")
TWILIO_API_KEY_SECRET = os.getenv("TWILIO_API_KEY_SECRET", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_CONTENT_SID = os.getenv("TWILIO_CONTENT_SID", "")
NOC_SMS_RECIPIENTS = _csv("NOC_SMS_RECIPIENTS")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noc@anptic.bf")
SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)
NOC_EMAIL_RECIPIENTS = _csv("NOC_EMAIL_RECIPIENTS")

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "noc@anptic.bf")


# ---------------------------------------------------------------------------
# Rapports
# ---------------------------------------------------------------------------
REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "/tmp/noc-reports")
REPORT_ORGANISATION = os.getenv("REPORT_ORGANISATION", "ANPTIC — RESINA")


# ---------------------------------------------------------------------------
# Métier
# ---------------------------------------------------------------------------
VALID_ROLES = ("directeur", "chef_noc", "technicien", "agent_terrain")

# Vocabulaire de sévérité normalisée, miroir exact de noc_norm_severity()
# dans sql/01_backend_extensions.sql.
SEVERITIES = ("critical", "high", "medium", "low", "info", "unknown")
STATUSES = ("open", "acknowledged", "resolved", "closed")

# Types de métriques produits par l'ETL, miroir de
# etl/transform/normalize_metrics.py::_VALID_METRIC_TYPES.
METRIC_TYPES = (
    "latency_ms",
    "packet_loss_pct",
    "bandwidth_in_mbps",
    "bandwidth_out_mbps",
    "cpu_pct",
    "ram_pct",
    "availability_pct",
)

# Heures ouvrées du NOC : sert au KPI « incidents détectés hors heures ».
NOC_BUSINESS_HOURS = (int(os.getenv("NOC_HOUR_START", "6")), int(os.getenv("NOC_HOUR_END", "21")))
TIMEZONE = os.getenv("TZ", "Africa/Ouagadougou")
