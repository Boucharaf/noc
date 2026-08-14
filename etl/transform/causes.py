"""
Cause taxonomy derived from what the supervision tools actually report.

The seeded demo dimension listed causes a human would write on a ticket
("Groupe électrogène en panne", "Coupure fibre optique"). Nothing produces
those: a monitoring alarm says what was *observed*, not why it happened, and no
collector has ever been able to fill them in — every real incident ingested so
far carried a NULL cause.

So the taxonomy here is the observable one, read off the message text NetXMS
actually sends. It is honest about being a symptom rather than a root cause:
"Nœud injoignable (ICMP)" is what the tool knows. Attributing that to a
délestage or a coupure fibre is the NOC's job, on the ticket, in iTop — which
is where the root-cause vocabulary belongs and where a human can be held to it.

RULES is ordered: the first pattern matching the message wins, so put the
specific ones above the general. A message nothing matches stays uncategorised
rather than being forced into a bucket — an "Autre" catch-all would quietly
grow into the largest cause on the dashboard and mean nothing.
"""

import re

# (compiled pattern, category, label). Patterns are matched case-insensitively
# against the alarm message.
RULES = [
    (r"unreachable by ICMP", "Connectivité", "Nœud injoignable (ICMP)"),
    (r"\bNode down\b", "Connectivité", "Nœud hors service"),
    (r"\bNode added\b|\bNode created\b", "Inventaire", "Nœud ajouté"),
    (r"Interface .* changed state to DOWN", "Réseau", "Interface hors service"),
    (r"Interface .* changed state to (UP|TESTING)", "Réseau", "Interface instable"),
    (r"SNMP agent is not responding", "Supervision", "Agent SNMP muet"),
    (r"agent is not responding|agent is unreachable", "Supervision", "Agent injoignable"),
    (r"Notification channel .* is down", "Supervision", "Canal de notification indisponible"),
    (r"Network service .* is not responding", "Service", "Service réseau injoignable"),
    (r"Business service changed state to failed", "Service", "Service métier en échec"),
    (r"Business service changed state to degraded", "Service", "Service métier dégradé"),
    (r"Threshold reached", "Seuil", "Seuil dépassé"),
    (r"Threshold rearmed", "Seuil", "Seuil rétabli"),
    (r"restarted|rebooted", "Équipement", "Redémarrage détecté"),
    (r"power supply|alimentation", "Énergie", "Alimentation en défaut"),
    (r"temperature|surchauffe", "Équipement", "Température anormale"),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), cat, label) for pattern, cat, label in RULES]

# Every (category, label) the rules can produce, in rule order — used to seed
# dim_cause so the dimension exists before the first incident references it.
TAXONOMY = list(dict.fromkeys((cat, label) for _, cat, label in RULES))


def classify(message: str | None) -> tuple[str | None, str | None]:
    """(category, label) for an alarm message, (None, None) when nothing fits."""
    if not message:
        return None, None
    for pattern, category, label in _COMPILED:
        if pattern.search(message):
            return category, label
    return None, None
