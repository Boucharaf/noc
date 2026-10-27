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

import unicodedata
from datetime import datetime, timezone, tzinfo

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
    "2": "medium",    # Warning
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
    "1": "medium",
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
    "warning": "medium",
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


# Gravité D'ORIGINE, dans le vocabulaire de chaque outil, traduite en clair :
# le NOC l'affiche telle quelle (« Désastre » pour Zabbix, « Majeure » pour
# NetXMS) au lieu d'un code (« 5 », « 3 »). La couleur suit l'échelle commune
# (`severity`), pour que les outils restent comparables entre eux.
_SOURCE_LABELS = {
    "zabbix": {"0": "Non classée", "1": "Information", "2": "Avertissement",
               "3": "Moyenne", "4": "Haute", "5": "Désastre"},
    "centreon_service": {"1": "Avertissement", "2": "Critique", "3": "Inconnu"},
    "centreon_host": {"1": "Hôte arrêté", "2": "Hôte injoignable"},
    "itop": {"1": "Critique", "2": "Haute", "3": "Moyenne", "4": "Basse"},
    "netxms": {"0": "Normale", "1": "Avertissement", "2": "Mineure",
               "3": "Majeure", "4": "Critique"},
}
_SOURCE_TEXTUAL = {
    "critical": "Critique", "disaster": "Désastre", "down": "Hôte arrêté",
    "major": "Majeure", "high": "Haute", "unreachable": "Hôte injoignable",
    "minor": "Mineure", "medium": "Moyenne", "average": "Moyenne",
    "warning": "Avertissement", "low": "Basse", "information": "Information",
    "informational": "Information", "info": "Information",
    "indeterminate": "Indéterminée", "cleared": "Levée", "unknown": "Inconnu",
}


def source_severity(scale: str, raw) -> str | None:
    """Gravité telle que l'outil la classe, en clair. None si illisible."""
    if raw is None or str(raw).strip() == "":
        return None
    key = str(raw).strip().lower()
    table = _SOURCE_LABELS.get(scale)
    if table is not None and key in table:
        return table[key]
    return _SOURCE_TEXTUAL.get(key, str(raw).strip())


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


def sql_to_dt(value, tz: tzinfo | None = None) -> datetime | None:
    """Date au format « AAAA-MM-JJ HH:MM:SS » (iTop) vers datetime UTC.

    iTop rend ses dates dans le fuseau de SA configuration (paramètre
    `timezone` de config-itop.php, « Europe/Paris » à l'installation), sans
    indicateur. Les lire comme UTC décalait chaque date d'une à deux heures —
    ouvertures, résolutions et donc délais SLA. `tz` est ce fuseau
    (ITOP_TIMEZONE) ; sans lui, la date est prise en UTC.
    """
    if not value or str(value).startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=tz or timezone.utc).astimezone(timezone.utc)
    return None


# ---------------------------------------------------------------------------
# Séries temporelles
# ---------------------------------------------------------------------------
# Comment combiner plusieurs séries sources (interfaces, systèmes de fichiers,
# sondes) en UNE courbe par équipement. La moyenne ne convient pas partout :
# le trafic d'un routeur est la SOMME de ses interfaces, et un disque plein
# se lit sur le système de fichiers le plus rempli, pas sur la moyenne qui le
# masquerait derrière un /boot vide.
_SERIES_COMBINE = {
    "bandwidth_in_mbps": "sum",
    "bandwidth_out_mbps": "sum",
    "if_errors": "sum",
    "disk_pct": "max",
    "packet_loss_pct": "max",
    "temp_cpu": "max",
}


def combine_series(series: list, metric_type: str, bucket_s: int) -> list:
    """Fusionne des séries `[(datetime, valeur), …]` en une liste de points.

    Les sondes d'un même équipement ne tournent pas à la même seconde :
    regrouper sur l'horodatage exact juxtaposerait les séries au lieu de les
    combiner, et la courbe alternerait d'un item à l'autre. Les points sont
    donc ramenés à des intervalles de `bucket_s` secondes ; chaque série
    contribue au plus une valeur (sa moyenne) par intervalle, puis les
    séries sont combinées selon la nature de la métrique.
    """
    from .models import MetricPoint

    mode = _SERIES_COMBINE.get(metric_type, "avg")
    bucket_s = max(1, int(bucket_s))
    combined: dict[int, list[float]] = {}
    for points in series:
        per_bucket: dict[int, list[float]] = {}
        for at, value in points:
            bucket = int(at.timestamp()) // bucket_s * bucket_s
            per_bucket.setdefault(bucket, []).append(value)
        for bucket, values in per_bucket.items():
            combined.setdefault(bucket, []).append(sum(values) / len(values))

    result = []
    for bucket, values in sorted(combined.items()):
        if mode == "sum":
            value = sum(values)
        elif mode == "max":
            value = max(values)
        else:
            value = sum(values) / len(values)
        result.append(
            MetricPoint(at=datetime.fromtimestamp(bucket, tz=timezone.utc), value=value)
        )
    return result


def combine_latest(values: list[float], metric_type: str) -> float:
    """Même règle que `combine_series`, pour les dernières valeurs."""
    mode = _SERIES_COMBINE.get(metric_type, "avg")
    if mode == "sum":
        return sum(values)
    if mode == "max":
        return max(values)
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------
# Convention retenue avec l'agence pour les outils sans référentiel
# géographique (Zabbix, Centreon, Nagios) : un groupe d'hôtes par niveau.
#     Site/<nom>   Province/<nom>   Region/<nom> (ou Région/<nom>)
_LOCALITY_PREFIXES = {
    "site": ("site/", "site:", "localité/", "localite/"),
    "province": ("province/", "province:"),
    "region": ("region/", "région/", "region:", "région:"),
}


def locality_from_groups(groups) -> dict[str, str | None]:
    """Site, province et région déclarés par les groupes d'un équipement."""
    found: dict[str, str | None] = {"site": None, "province": None, "region": None}
    for group in groups:
        name = str(group).strip()
        lowered = name.lower()
        for level, prefixes in _LOCALITY_PREFIXES.items():
            if found[level]:
                continue
            for prefix in prefixes:
                if lowered.startswith(prefix):
                    found[level] = name[len(prefix):].strip() or None
                    break
    return found


def locality_key(name: str | None) -> str:
    """Clé de comparaison d'un nom de lieu : sans accents ni casse.

    « KUILSÉ », « Kuilsé » et « KUILSE » désignent la même région selon la
    source (base NetXMS, fond de carte, saisie manuelle).
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(name))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip().upper()


def display_locality(name: str | None) -> str | None:
    """Nom de région ou de province pour l'affichage : « KUILSÉ » -> « Kuilsé »."""
    if not name or not str(name).strip():
        return None
    return " ".join(
        "-".join(part.capitalize() for part in word.split("-"))
        for word in str(name).strip().split()
    )
