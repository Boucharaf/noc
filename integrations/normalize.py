"""
Traduction des vocabulaires propres à chaque outil vers celui du NOC.

Tout est ici et nulle part ailleurs. C'est délibéré : le jour où l'agence
ajoute un septième outil, la question « comment se traduit sa sévérité ? » a
un seul endroit où se poser, et les correspondances existantes servent de
référence pour trancher.

Les tables sont écrites à partir de la documentation de chaque éditeur ; les
sources sont citées en commentaire, parce qu'une correspondance de sévérité
sans justification devient indiscutable pour la personne qui la relira.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import SEVERITIES

_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Sévérités
# ---------------------------------------------------------------------------
# Zabbix — « Trigger severity », 0 à 5.
# https://www.zabbix.com/documentation/7.0/en/manual/config/triggers/severity
_ZABBIX = {
    "5": "critical",  # Disaster
    "4": "high",      # High
    "3": "medium",    # Average
    "2": "low",       # Warning
    "1": "info",      # Information
    "0": _UNKNOWN,    # Not classified
}

# Centreon — état d'un SERVICE : 0 OK, 1 WARNING, 2 CRITICAL, 3 UNKNOWN.
# Un service en WARNING n'est pas « faible » : c'est un seuil franchi qui
# appelle un regard, d'où « medium » et non « low ».
_CENTREON_SERVICE = {
    "1": "medium",
    "2": "critical",
    "3": _UNKNOWN,
}

# Centreon — état d'un HÔTE : 0 UP, 1 DOWN, 2 UNREACHABLE.
# UNREACHABLE veut dire « je ne peux pas savoir, le chemin est coupé en
# amont » : c'est grave, mais moins directement actionnable qu'un DOWN
# constaté, d'où « high » plutôt que « critical ».
_CENTREON_HOST = {
    "1": "critical",
    "2": "high",
}

# iTop — priorité d'un ticket : 1 critique, 2 haute, 3 moyenne, 4 basse.
_ITOP = {
    "1": "critical",
    "2": "high",
    "3": "medium",
    "4": "low",
}

# NetXMS — sévérité d'un événement : 0 normal, 1 warning, 2 minor,
# 3 major, 4 critical.
_NETXMS = {
    "4": "critical",
    "3": "high",
    "2": "medium",
    "1": "low",
    "0": "info",
}

# Nokia NSP et Nagios expriment déjà leur sévérité en toutes lettres ; on se
# contente d'aligner le vocabulaire.
_TEXTUAL = {
    "critical": "critical",
    "disaster": "critical",
    "down": "critical",
    "major": "high",
    "high": "high",
    "unreachable": "high",
    "minor": "medium",
    "medium": "medium",
    "average": "medium",
    "warning": "low",
    "low": "low",
    "information": "info",
    "informational": "info",
    "info": "info",
    "indeterminate": _UNKNOWN,
    "cleared": _UNKNOWN,
    "unknown": _UNKNOWN,
}

_TABLES = {
    "zabbix": _ZABBIX,
    "centreon_service": _CENTREON_SERVICE,
    "centreon_host": _CENTREON_HOST,
    "itop": _ITOP,
    "netxms": _NETXMS,
}


def severity(scale: str, raw) -> str:
    """Traduit une sévérité brute vers le vocabulaire du NOC.

    Une valeur inconnue devient « unknown » et non « info » : afficher en
    information une alerte dont on n'a pas su lire la gravité reviendrait à
    la faire disparaître de l'écran d'un exploitant.
    """
    if raw is None:
        return _UNKNOWN
    key = str(raw).strip().lower()
    table = _TABLES.get(scale)
    if table is not None and key in table:
        return table[key]
    return _TEXTUAL.get(key, _UNKNOWN)


def worst(severities) -> str:
    """La plus grave d'un ensemble. Sert à résumer l'état d'un équipement
    couvert par plusieurs alertes, ou vu par plusieurs outils."""
    ranked = [s for s in severities if s in SEVERITIES]
    if not ranked:
        return _UNKNOWN
    return min(ranked, key=SEVERITIES.index)


def is_actionable(sev: str) -> bool:
    """Une sévérité qui justifie qu'on réveille quelqu'un.

    Utilisé pour le décompte du mur d'alertes et pour les notifications
    sortantes : « info » et « unknown » ne doivent jamais déclencher un SMS.
    """
    return sev in ("critical", "high")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def epoch_to_dt(value) -> datetime | None:
    """Horodatage UNIX (Zabbix, Nagios) vers datetime UTC."""
    if value in (None, "", "0", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def iso_to_dt(value) -> datetime | None:
    """Chaîne ISO 8601 (Centreon, NSP) vers datetime UTC."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sql_to_dt(value) -> datetime | None:
    """Date au format « AAAA-MM-JJ HH:MM:SS » (iTop) vers datetime UTC.

    iTop rend ses dates dans le fuseau configuré de l'application, sans
    indicateur. On les considère UTC : le conteneur et l'application partagent
    la variable TZ, donc l'écart éventuel est le même partout, et le déclarer
    explicitement vaut mieux qu'une date naïve qui sera réinterprétée
    différemment à chaque relecture.
    """
    if not value or str(value).startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
