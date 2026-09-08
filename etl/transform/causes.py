"""
Classification de la cause d'un incident à partir de sa description brute
(champ texte fourni par chaque outil : `name` Zabbix, `message` NetXMS,
`output` Centreon, `description`/`probableCause` NSP...).

Approche par règles regex volontairement simple et transparente : chaque
règle est explicite, testable, et ordonnée (la première qui matche
gagne). Préférée à un modèle de classification pour rester auditable par
les agents NOC (traçabilité = un agent doit pouvoir comprendre pourquoi
un incident a été catégorisé ainsi).
"""
from __future__ import annotations

import re

# (catégorie, motif) — ordre = priorité
_RULES: list[tuple[str, re.Pattern]] = [
    ("lien_down", re.compile(r"\b(link|interface).{0,20}(down|unreachable)\b", re.I)),
    ("perte_paquets", re.compile(r"\b(packet loss|perte de paquets)\b", re.I)),
    ("latence", re.compile(r"\b(latency|latence|round trip|rta)\b", re.I)),
    ("cpu", re.compile(r"\bcpu\b", re.I)),
    ("memoire", re.compile(r"\b(memory|ram|mémoire)\b", re.I)),
    ("alimentation", re.compile(r"\b(power|alimentation|psu)\b", re.I)),
    ("equipement_down", re.compile(r"\b(host down|node down|unreachable|hors service)\b", re.I)),
    ("seuil_trafic", re.compile(r"\b(bandwidth|traffic|bande passante|trafic)\b", re.I)),
]

DEFAULT_CATEGORY = "non_identifie"


def classify(description: str) -> str:
    if not description:
        return DEFAULT_CATEGORY
    for category, pattern in _RULES:
        if pattern.search(description):
            return category
    return DEFAULT_CATEGORY
