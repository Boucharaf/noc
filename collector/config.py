"""Configuration du collecteur."""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Cadence de collecte. C'est LE paramètre qui détermine la charge imposée aux
# outils sources : une requête par outil et par intervalle, quel que soit le
# nombre d'opérateurs connectés. Le descendre en dessous de 60 s n'apporte
# rien au NOC (les sondes elles-mêmes tournent rarement plus vite) et
# multiplie la charge sur la production.
COLLECT_INTERVAL_S = max(60, _int("COLLECT_INTERVAL_S", 300))

# Délai maximal d'un cycle complet. Au-delà, le cycle est abandonné et le
# suivant démarre à l'heure : mieux vaut un instantané manquant qu'une file
# de cycles qui se chevauchent et saturent les outils sources.
CYCLE_TIMEOUT_S = _int("COLLECT_CYCLE_TIMEOUT_S", max(45, COLLECT_INTERVAL_S - 30))

# Outils interrogés moins souvent que le cycle : iTop (tickets, CMDB) ne dit
# pas si un équipement répond, et ses lectures sont les plus lourdes. Entre
# deux lectures, sa dernière réponse est reprise.
SLOW_TOOLS = frozenset(
    item.strip().lower() for item in os.getenv("COLLECT_SLOW_TOOLS", "itop").split(",")
    if item.strip()
)
SLOW_INTERVAL_S = max(COLLECT_INTERVAL_S, _int("COLLECT_SLOW_INTERVAL_S", 300))

# Sans observation au-delà de ce délai, le temps devient « non observé ».
# Jamais moins de 5 min : à une minute, trois cycles seraient trop courts pour
# absorber un outil lent.
OBSERVATION_GAP_S = max(3 * COLLECT_INTERVAL_S, 300)

# Une source dont la dernière donnée est plus ancienne que ce délai est
# ARRÊTÉE (dump restauré, export, serveur stoppé) : ses états deviennent
# « inconnu » et ses alertes « non confirmées ». 0 = jamais.
SOURCE_FROZEN_HOURS = max(0, _int("SOURCE_FROZEN_HOURS", 24))

# Agrégats journaliers écrits en base (voir collector/rollup.py). Désactivables
# pour un déploiement qui n'aurait pas besoin des tendances long terme.
ROLLUP_ENABLED = _bool("ROLLUP_ENABLED", True)
ROLLUP_HOUR = _int("ROLLUP_HOUR", 1)
# Bilan non écrit (base indisponible) : nouvel essai à cet intervalle.
ROLLUP_RETRY_S = max(60, _int("ROLLUP_RETRY_S", 900))
# Journal historique (collector/history.py) : périodes d'état des équipements
# et des liens, vie des alertes. Écrit à chaque cycle dans la base du NOC.
HISTORY_ENABLED = _bool("HISTORY_ENABLED", True)
# Jours de conservation de ce qui est clos. 0 (défaut) = indéfiniment : la
# disponibilité sur plusieurs années est un besoin, et le journal ne garde
# que les changements (quelques Mo par mois).
HISTORY_RETENTION_DAYS = _int("HISTORY_RETENTION_DAYS", 0)
# Délai de garde de l'écriture d'un cycle : au-delà, le cycle n'attend plus.
HISTORY_TIMEOUT_S = _int("HISTORY_TIMEOUT_S", 60)  # heure locale d'écriture du bilan de la veille

# Pannes enregistrées par NetXMS (table downtime_log, collector/downtime.py) :
# source maître de la disponibilité des équipements NetXMS. Désactivé par
# défaut ; demande une connexion en lecture seule à la BASE NetXMS, même
# quand l'inventaire est lu par l'API Web.
NETXMS_DOWNTIME_ENABLED = _bool("NETXMS_DOWNTIME_ENABLED", False)
_netxms_url = os.getenv("NETXMS_API_URL", "").strip()
NETXMS_DOWNTIME_DSN = os.getenv("NETXMS_DOWNTIME_DSN", "").strip() or (
    _netxms_url if _netxms_url.startswith(("postgresql://", "postgres://")) else ""
)
NETXMS_DOWNTIME_USER = os.getenv("NETXMS_DOWNTIME_USER", "").strip() or os.getenv(
    "NETXMS_API_USER", ""
).strip()
NETXMS_DOWNTIME_PASSWORD = os.getenv("NETXMS_DOWNTIME_PASSWORD", "") or os.getenv(
    "NETXMS_API_PASSWORD", ""
)
# Étiquettes (colonne tag) retenues ; vide = toutes.
NETXMS_DOWNTIME_TAGS = frozenset(
    item.strip() for item in os.getenv("NETXMS_DOWNTIME_TAGS", "").split(",") if item.strip()
)
# Profondeur de la première lecture, puis fréquence des relectures.
NETXMS_DOWNTIME_BACKFILL_DAYS = max(1, _int("NETXMS_DOWNTIME_BACKFILL_DAYS", 400))
NETXMS_DOWNTIME_SYNC_S = max(60, _int("NETXMS_DOWNTIME_SYNC_S", 900))
NETXMS_DOWNTIME_TIMEOUT_S = float(_int("NETXMS_DOWNTIME_TIMEOUT_S", 30))
# Pannes des hôtes Centreon (changements d'état HARD, API REST v2 : un appel
# par hôte — d'où une relecture horaire par défaut). Même règle que NetXMS,
# pour les équipements que NetXMS ne supervise pas.
CENTREON_DOWNTIME_ENABLED = _bool("CENTREON_DOWNTIME_ENABLED", False)
CENTREON_DOWNTIME_BACKFILL_DAYS = max(1, _int("CENTREON_DOWNTIME_BACKFILL_DAYS", 90))
CENTREON_DOWNTIME_SYNC_S = max(300, _int("CENTREON_DOWNTIME_SYNC_S", 3600))
# Zabbix (événements des déclencheurs de disponibilité, une requête) et
# Nagios (changements d'état HARD des hôtes ; relecture comme Centreon).
ZABBIX_DOWNTIME_ENABLED = _bool("ZABBIX_DOWNTIME_ENABLED", False)
ZABBIX_DOWNTIME_BACKFILL_DAYS = max(1, _int("ZABBIX_DOWNTIME_BACKFILL_DAYS", 90))
ZABBIX_DOWNTIME_SYNC_S = max(60, _int("ZABBIX_DOWNTIME_SYNC_S", 900))
NAGIOS_DOWNTIME_ENABLED = _bool("NAGIOS_DOWNTIME_ENABLED", False)

# Conservation (collector/retention.py). Désactivée : rien n'est supprimé.
RETENTION_ENABLED = _bool("RETENTION_ENABLED", False)
RETENTION_DAYS = {
    name: _int(name, 0)
    for name in (
        "RETENTION_AUDIT_DAYS", "RETENTION_NOTIFICATION_DAYS",
        "RETENTION_TOOL_HEALTH_DAYS", "RETENTION_KPI_DAYS",
    )
}
# Le registre d'identité est lu AVANT la publication : une base lente ne doit
# pas retarder le tableau de bord (collector/identity.py).
IDENTITY_TIMEOUT_S = _int("IDENTITY_TIMEOUT_S", 10)

DATABASE_URL = os.getenv(
    "NOC_DATABASE_URL",
    os.getenv("NOC_WAREHOUSE_DSN", "postgresql://noc:noc@postgres:5432/noc"),
)

TIMEZONE = os.getenv("TZ", "Africa/Ouagadougou")
