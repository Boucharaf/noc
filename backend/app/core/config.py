"""
Configuration du backend NOC.

TROIS SOURCES DE DONNÉES, ET UNE SEULE VARIABLE PAR SOURCE :

  REDIS_URL          — l'instantané publié par le collecteur, et le cache
                       d'historique. C'est de LOIN le chemin le plus
                       fréquenté : tous les écrans « maintenant » n'en
                       sortent pas.
  NOC_DATABASE_URL   — la petite base PostgreSQL des données propres au
                       NOC (comptes, acquittements, maintenances, agrégats
                       journaliers). Voir backend/sql/schema.sql.
  <OUTIL>_API_URL    — les outils sources, interrogés à la demande pour
                       l'historique (integrations/config.py).

L'ancienne variable NOC_WAREHOUSE_DSN reste acceptée en repli pour ne pas
casser un déploiement existant, mais elle ne désigne plus un entrepôt : la
base ne contient plus ni métriques ni faits. Voir ARCHITECTURE.md.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _csv(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ---------------------------------------------------------------------------
# Base de données du NOC
# ---------------------------------------------------------------------------
def _database_url() -> str:
    for name in ("NOC_DATABASE_URL", "NOC_WAREHOUSE_DSN"):
        value = os.getenv(name)
        if value:
            return value
    from urllib.parse import quote_plus

    user = quote_plus(os.getenv("POSTGRES_USER", "noc"))
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "noc"))
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "noc")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _database_url()

# Un pool modeste : la base ne sert plus le chemin chaud du tableau de bord,
# seulement les écritures d'exploitation et les agrégats. Dimensionner à
# trente connexions comme l'ancien entrepôt reviendrait à réserver de la
# mémoire côté PostgreSQL pour des connexions qui resteraient inactives.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))


# ---------------------------------------------------------------------------
# Redis — instantané et cache
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# DOIT valoir la même chose que pour le collecteur : c'est cette valeur qui
# fixe la durée de vie des clés d'instantané (trois cycles). Si le backend
# la croit plus courte que le collecteur, il déclarera la collecte
# interrompue alors qu'elle tourne.
COLLECT_INTERVAL_S = int(os.getenv("COLLECT_INTERVAL_S", "300"))

# Outils du périmètre, énumérés ici plutôt que déduits des clés Redis
# présentes : un outil configuré dont le collecteur n'a jamais joint l'API
# doit apparaître comme « jamais collecté », pas disparaître de la page
# Interopérabilité.
SUPERVISION_TOOLS = tuple(
    _csv("SUPERVISION_TOOLS", "zabbix,centreon,itop,netxms,nagios,nsp")
)


# ---------------------------------------------------------------------------
# Sécurité
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRATION_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "7"))

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# `secure=True` par défaut : c'est le comportement correct derrière le
# reverse proxy TLS. Ne passer à false que pour un développement local servi
# en http:// — sinon le navigateur refuse le cookie et la session tombe au
# bout de trente minutes sans explication.
REFRESH_COOKIE_SECURE = _bool("REFRESH_COOKIE_SECURE", True)

CORS_ORIGINS = _csv("CORS_ORIGINS", "http://localhost,http://localhost:5173")

RATE_LIMIT_ENABLED = _bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_READ_PER_MIN = int(os.getenv("RATE_LIMIT_READ_PER_MIN", "100"))
RATE_LIMIT_WRITE_PER_MIN = int(os.getenv("RATE_LIMIT_WRITE_PER_MIN", "30"))


# ---------------------------------------------------------------------------
# Diffusion temps réel
# ---------------------------------------------------------------------------
# Le backend s'abonne au canal Redis que le collecteur alimente, et
# retransmet vers les navigateurs par WebSocket. Il n'interroge plus aucune
# table : l'ancien « veilleur » qui relisait fact_incident toutes les 30 s
# n'a plus de raison d'être, le collecteur sait déjà ce qui est nouveau.
REALTIME_ENABLED = _bool("REALTIME_ENABLED", True)

# Sévérités normalisées qui déclenchent une notification sortante.
# « info » et « unknown » n'en font jamais partie : réveiller l'astreinte
# pour une alerte dont on n'a pas su lire la gravité est le meilleur moyen
# de faire couper les notifications.
NOTIFY_SEVERITIES = tuple(_csv("NOTIFY_SEVERITIES", "critical,high"))


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
# STARTTLS : connexion d'abord en clair, chiffrement négocié ensuite (587).
SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)
# TLS implicite (SMTPS, 465) : chiffré dès la connexion. Déduit du port
# quand la variable est vide — un serveur sur 465 ne parle QUE ce mode, et
# y tenter STARTTLS se solde par un délai d'attente sans message clair.
SMTP_USE_SSL = (
    _bool("SMTP_USE_SSL") if os.getenv("SMTP_USE_SSL", "").strip() else SMTP_PORT == 465
)
# À false uniquement pour un relais interne à certificat auto-signé.
SMTP_VERIFY_SSL = _bool("SMTP_VERIFY_SSL", True)
# Listes de diffusion FIXES (astreinte, direction technique). S'y ajoutent
# les comptes abonnés depuis l'interface — voir notification_service.
NOC_EMAIL_RECIPIENTS = _csv("NOC_EMAIL_RECIPIENTS")

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "noc@anptic.bf")


# ---------------------------------------------------------------------------
# Rapports
# ---------------------------------------------------------------------------
REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "/reports")
REPORT_ORGANISATION = os.getenv("REPORT_ORGANISATION", "ANPTIC — RESINA")


# ---------------------------------------------------------------------------
# Métier
# ---------------------------------------------------------------------------
VALID_ROLES = ("directeur", "chef_noc", "technicien", "agent_terrain")

# Vocabulaire normalisé, miroir exact de integrations/models.py. Toute
# divergence entre les deux ferait disparaître des alertes des décomptes.
SEVERITIES = ("critical", "high", "medium", "low", "info", "unknown")
NODE_STATES = ("down", "degraded", "silent", "maintenance", "up", "unknown")
METRIC_TYPES = (
    "latency_ms",
    "packet_loss_pct",
    "bandwidth_in_mbps",
    "bandwidth_out_mbps",
    "cpu_pct",
    "ram_pct",
    "availability_pct",
)

# Heures ouvrées du NOC : sert au KPI « alertes détectées hors heures ».
NOC_BUSINESS_HOURS = (
    int(os.getenv("NOC_HOUR_START", "6")),
    int(os.getenv("NOC_HOUR_END", "21")),
)
TIMEZONE = os.getenv("TZ", "Africa/Ouagadougou")
