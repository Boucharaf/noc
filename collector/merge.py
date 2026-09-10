"""
Fusion des inventaires de plusieurs outils en un parc unique.

LE PROBLÈME. Un même routeur est connu de Zabbix sous `RTR-OUAGA-01`, de
Centreon sous `rtr-ouaga-01.anptic.bf`, et d'iTop sous « Routeur Ouagadougou
principal ». Trois outils, trois identifiants, aucun commun. Affiché tel
quel, le parc compte trois équipements là où il y en a un — et les
statistiques par site sont fausses d'un facteur trois.

LA RÈGLE. On ne rapproche que sur des preuves, dans cet ordre de confiance :

  1. **adresse IP identique** — c'est une preuve ; deux outils qui supervisent
     la même IP supervisent la même machine ;
  2. **nom identique après normalisation** (minuscules, domaine retiré,
     séparateurs unifiés) — c'est une forte présomption ;
  3. rien d'autre. Pas de similarité approximative, pas de distance de
     Levenshtein. Un rapprochement erroné fusionne deux équipements
     DIFFÉRENTS et fait disparaître un site entier de la supervision : le
     coût d'un faux positif est bien supérieur à celui d'un doublon visible.

Les rapprochements retenus sont tracés dans `MergeReport`, que l'écran
Interopérabilité affiche : l'exploitant doit pouvoir contrôler ce que la
machine a décidé, et corriger les conventions de nommage à la source.
"""
from __future__ import annotations

import ipaddress
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from integrations.models import Alert, Node
from integrations.normalize import worst

logger = logging.getLogger(__name__)

# Ordre de préséance des outils pour les champs en conflit. La supervision
# prime sur l'ITSM pour l'ÉTAT (elle mesure, iTop déclare), l'ITSM prime pour
# l'ORGANISATION et le SITE (c'est son métier, et ses données sont saisies).
STATE_PRIORITY = ("zabbix", "centreon", "netxms", "nagios", "nsp", "itop")
REFERENCE_PRIORITY = ("itop", "zabbix", "centreon", "netxms", "nagios", "nsp")

_STATE_RANK = {
    "down": 0,
    "degraded": 1,
    "silent": 2,
    "maintenance": 3,
    "up": 4,
    "unknown": 5,
}


@dataclass
class MergedNode:
    """Un équipement du parc, tel que le NOC l'affiche."""

    id: str                       # identifiant stable, dérivé de l'identité retenue
    name: str                     # libellé affiché
    hostname: str                 # nom technique — celui qui a servi au rapprochement
    ip: str | None
    state: str
    site: str | None
    organisation: str | None
    node_type: str | None
    groups: list[str] = field(default_factory=list)
    # Traçabilité : quels outils voient cet équipement, et sous quelle
    # référence. Affiché sur la fiche d'équipement — un exploitant qui doute
    # doit pouvoir remonter à la source en un clic.
    sources: dict[str, str] = field(default_factory=dict)
    alerts: int = 0
    worst_severity: str = "unknown"


@dataclass
class MergeReport:
    """Ce que la fusion a décidé, pour que ce soit contrôlable."""

    total_raw: int = 0
    total_merged: int = 0
    matched_by_ip: int = 0
    matched_by_name: int = 0
    # Équipements qu'un seul outil connaît : souvent le signe d'un défaut de
    # couverture (supervisé par Zabbix mais absent de la CMDB, ou l'inverse).
    single_source: list[str] = field(default_factory=list)


def _normalise_name(name: str) -> str:
    """Nom réduit à ce qui est comparable.

    On retire le domaine, on unifie les séparateurs et la casse. On ne va PAS
    plus loin : supprimer les chiffres ou les préfixes rapprocherait
    « RTR-01 » et « RTR-02 », deux équipements bien distincts.

    Une ADRESSE IP n'est pas un nom : NetXMS, et Zabbix pour les hôtes sans
    DNS, en mettent une à la place du nom technique. « Retirer le domaine »
    de 192.168.215.41 donnerait « 192 », et tout le plan d'adressage
    fusionnerait en un seul équipement. L'IP a sa propre règle, plus haut.
    """
    try:
        ipaddress.ip_address(name.strip())
        return ""
    except ValueError:
        pass
    base = name.strip().lower().split(".", 1)[0]
    return re.sub(r"[\s_]+", "-", base).strip("-")


def _valid_ip(value: str | None) -> str | None:
    """Adresse IP utilisable comme preuve d'identité.

    Les adresses de bouclage et « 0.0.0.0 » sont écartées : Centreon renseigne
    127.0.0.1 pour tout hôte supervisé localement, et rapprocher sur cette
    base fusionnerait l'intégralité du parc en un seul équipement.
    """
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if address.is_loopback or address.is_unspecified:
        return None
    return str(address)


def merge_nodes(nodes: list[Node]) -> tuple[list[MergedNode], MergeReport]:
    """Rapproche les équipements vus par plusieurs outils."""
    report = MergeReport(total_raw=len(nodes))

    # Chaque équipement brut commence dans son propre groupe, puis les groupes
    # fusionnent par IP puis par nom. Une union-find serait plus élégante ;
    # deux dictionnaires suffisent ici et se relisent sans effort.
    groups: dict[str, list[Node]] = {}
    by_ip: dict[str, str] = {}
    by_name: dict[str, str] = {}

    for node in nodes:
        ip = _valid_ip(node.ip)
        # Le rapprochement porte sur le nom TECHNIQUE, pas sur le libellé.
        # Zabbix affiche « noc-backend — Application NOC » là où la CMDB dit
        # « noc-backend » : sur le libellé, les deux ne se rejoindraient
        # jamais. Voir integrations/models.py::Node.hostname.
        name_key = _normalise_name(node.hostname or node.name)

        target = None
        if ip and ip in by_ip:
            target = by_ip[ip]
            report.matched_by_ip += 1
        elif name_key and name_key in by_name:
            target = by_name[name_key]
            report.matched_by_name += 1

        # On ne rapproche que des outils DIFFÉRENTS. Deux objets d'un même
        # outil sont deux équipements pour lui (même IP dans deux zones NetXMS,
        # homonymes dans deux groupes Zabbix) : les fondre effacerait la
        # référence de l'un dans `sources`, et ses alertes deviendraient
        # orphelines.
        if target is not None and any(m.tool == node.tool for m in groups[target]):
            if ip and by_ip.get(ip) == target:
                report.matched_by_ip -= 1
            else:
                report.matched_by_name -= 1
            target = None

        if target is None:
            target = node.key()
            groups[target] = []

        groups[target].append(node)
        if ip:
            by_ip.setdefault(ip, target)
        if name_key:
            by_name.setdefault(name_key, target)

    merged = [_fold(group_id, members) for group_id, members in groups.items()]
    merged.sort(key=lambda n: (_STATE_RANK.get(n.state, 9), n.name.lower()))

    report.total_merged = len(merged)
    report.single_source = [n.name for n in merged if len(n.sources) == 1]
    return merged, report


def _fold(group_id: str, members: list[Node]) -> MergedNode:
    """Réduit les vues d'un même équipement à une seule.

    Le choix de chaque champ est explicite plutôt que « le premier gagne » :
    ce sont ces règles qui décident ce que l'exploitant voit à l'écran.
    """
    by_tool = {node.tool: node for node in members}

    # ÉTAT : celui de l'outil de supervision le plus prioritaire qui ait un
    # avis. iTop est exclu — un référentiel ne mesure rien.
    state = "unknown"
    for tool in STATE_PRIORITY:
        node = by_tool.get(tool)
        if node is not None and node.state != "unknown":
            state = node.state
            break

    # NOM et SITE : la source de référence prime (iTop d'abord). Le nom d'un
    # équipement dans la CMDB est celui que l'organisation a choisi ; celui
    # d'un outil de supervision est souvent un identifiant technique.
    name = None
    site = None
    organisation = None
    node_type = None
    for tool in REFERENCE_PRIORITY:
        node = by_tool.get(tool)
        if node is None:
            continue
        name = name or node.name
        site = site or node.site
        organisation = organisation or node.organisation
        node_type = node_type or node.node_type

    ip = next((_valid_ip(n.ip) for n in members if _valid_ip(n.ip)), None)
    groups = sorted({g for node in members for g in node.groups if g})
    hostname = next(
        (n.hostname for n in members if n.hostname), members[0].name
    )

    return MergedNode(
        id=group_id,
        name=name or members[0].name,
        hostname=hostname,
        ip=ip,
        state=state,
        site=site,
        organisation=organisation,
        node_type=node_type,
        groups=groups,
        sources={node.tool: node.ref for node in members},
    )


def attach_alerts(
    merged: list[MergedNode], alerts: list[Alert]
) -> tuple[list[MergedNode], list[Alert]]:
    """Rattache chaque alerte à son équipement et compte.

    Rend aussi les alertes ORPHELINES — celles dont l'équipement n'est dans
    aucun inventaire. Elles ne sont pas jetées : une alerte sur un équipement
    inconnu du parc est le signal qu'un outil supervise quelque chose que la
    CMDB ignore, ce qui intéresse directement le responsable du NOC.
    """
    index: dict[str, MergedNode] = {}
    for node in merged:
        for tool, ref in node.sources.items():
            index[f"{tool}:{ref}"] = node

    # Repli par nom normalisé, pour les outils qui ne donnent pas
    # d'identifiant d'équipement sur leurs alertes (iTop rattache un CI par
    # son nom, Nagios n'a que le nom d'hôte).
    by_name = {}
    for node in merged:
        by_name[_normalise_name(node.hostname)] = node
        by_name.setdefault(_normalise_name(node.name), node)

    severities: dict[str, list[str]] = defaultdict(list)
    orphans: list[Alert] = []

    for alert in alerts:
        node = None
        if alert.node_ref:
            node = index.get(f"{alert.tool}:{alert.node_ref}")
        if node is None and alert.node_name:
            node = by_name.get(_normalise_name(alert.node_name))
        if node is None:
            orphans.append(alert)
            continue
        severities[node.id].append(alert.severity)

    for node in merged:
        found = severities.get(node.id, [])
        node.alerts = len(found)
        node.worst_severity = worst(found) if found else "unknown"

    return merged, orphans
