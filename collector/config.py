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
CYCLE_TIMEOUT_S = _int("COLLECT_CYCLE_TIMEOUT_S", max(120, COLLECT_INTERVAL_S - 30))

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

DATABASE_URL = os.getenv(
    "NOC_DATABASE_URL",
    os.getenv("NOC_WAREHOUSE_DSN", "postgresql://noc:noc@postgres:5432/noc"),
)

TIMEZONE = os.getenv("TZ", "Africa/Ouagadougou")
