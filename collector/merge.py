"""Consolidate inventories conservatively and report ambiguous identities."""
from __future__ import annotations

import ipaddress
import math
from collections import defaultdict
from dataclasses import dataclass, field

from integrations.models import Alert, Node
from integrations.normalize import locality_key, worst

# Ordre de préférence pour les seuls champs de contexte métier.
# Les états techniques ne suivent pas de priorité d'outil.
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
    latitude: float | None
    longitude: float | None
    organisation: str | None
    node_type: str | None
    groups: list[str] = field(default_factory=list)
    province: str | None = None
    region: str | None = None
    # Traçabilité : quels outils voient cet équipement, et sous quelle
    # référence. Affiché sur la fiche d'équipement — un exploitant qui doute
    # doit pouvoir remonter à la source en un clic.
    sources: dict[str, str] = field(default_factory=dict)
    alerts: int = 0
    worst_severity: str = "unknown"
    state_conflict: dict[str, str] = field(default_factory=dict)
    last_known_states: dict[str, str] = field(default_factory=dict)
    stale_sources: list[str] = field(default_factory=list)


@dataclass
class MergeReport:
    """Ce que la fusion a décidé, pour que ce soit contrôlable."""

    total_raw: int = 0
    total_merged: int = 0
    matched_by_ip: int = 0
    matched_by_name: int = 0
    matched_by_verified_identity: int = 0
    ambiguous_total: int = 0
    ambiguities: list[dict[str, str]] = field(default_factory=list)
    state_conflicts: list[dict[str, object]] = field(default_factory=list)
    # Équipements qu'un seul outil connaît : souvent le signe d'un défaut de
    # couverture (supervisé par Zabbix mais absent de la CMDB, ou l'inverse).
    single_source: list[str] = field(default_factory=list)


def _normalise_name(name: str) -> str:
    """Normalize case and a terminal DNS dot, preserving the full hostname."""
    if not isinstance(name, str):
        return ""
    try:
        ipaddress.ip_address(name.strip())
        return ""
    except ValueError:
        pass
    return name.strip().rstrip(".").casefold()


def _valid_ip(value: str | None) -> str | None:
    """Return a canonical IP hint; an IP alone is never identity proof."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if address.is_loopback or address.is_unspecified:
        return None
    return str(address)


def _valid_coordinates(
    latitude: float | None, longitude: float | None
) -> tuple[float, float] | None:
    if latitude is None or longitude is None:
        return None
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return None
    return latitude, longitude


def merge_nodes(nodes: list[Node]) -> tuple[list[MergedNode], MergeReport]:
    """Merge only unique cross-source matches with the same full hostname and IP.

    IPs can be shared by virtual services and hostnames can be reused across
    domains. Requiring both, preserving the full hostname, and rejecting
    duplicate identities within a source favors a visible duplicate over a
    destructive false merge.
    """
    report = MergeReport(total_raw=len(nodes))
    by_identity: dict[tuple[str, str], list[Node]] = defaultdict(list)
    by_ip: dict[str, list[Node]] = defaultdict(list)
    by_name: dict[str, list[Node]] = defaultdict(list)

    for node in sorted(nodes, key=lambda item: (item.tool, item.ref)):
        name = _normalise_name(node.hostname or node.name)
        ip = _valid_ip(node.ip)
        if name:
            by_name[name].append(node)
        if ip:
            by_ip[ip].append(node)
        if name and ip:
            by_identity[(name, ip)].append(node)

    def record_ambiguity(reason: str, members: list[Node], identity: str) -> None:
        report.ambiguous_total += 1
        if len(report.ambiguities) < 50:
            report.ambiguities.append(
                {
                    "reason": reason,
                    "identity": identity,
                    "sources": ", ".join(sorted({node.tool for node in members})),
                }
            )

    for ip, members in by_ip.items():
        names = {_normalise_name(node.hostname or node.name) for node in members}
        if len(names) > 1:
            record_ambiguity("shared_ip_with_different_hostnames", members, ip)
    for name, members in by_name.items():
        ips = {_valid_ip(node.ip) for node in members}
        if len(ips) > 1:
            record_ambiguity("hostname_with_different_ips", members, name)

    groups: list[list[Node]] = []
    identity_node_ids: set[int] = set()
    for (name, ip), members in sorted(by_identity.items()):
        identity_node_ids.update(id(node) for node in members)
        source_counts: dict[str, int] = defaultdict(int)
        for node in members:
            source_counts[node.tool] += 1
        if any(count > 1 for count in source_counts.values()):
            record_ambiguity(
                "duplicate_identity_within_source",
                members,
                f"{name}@{ip}",
            )
            groups.extend([[node] for node in members])
        elif len(source_counts) > 1:
            groups.append(members)
            matches = len(members) - 1
            report.matched_by_verified_identity += matches
        else:
            groups.extend([[node] for node in members])

    groups.extend([[node] for node in nodes if id(node) not in identity_node_ids])
    merged = [_fold(members[0].key(), members) for members in groups]
    _inherit_locality(merged)
    merged.sort(key=lambda n: (_STATE_RANK.get(n.state, 9), n.name.lower()))

    report.total_merged = len(merged)
    report.single_source = [n.name for n in merged if len(n.sources) == 1]
    report.state_conflicts = [
        {"id": node.id, "states": node.state_conflict}
        for node in merged
        if node.state_conflict
    ]
    return merged, report


def _fold(group_id: str, members: list[Node]) -> MergedNode:
    """Réduit les vues d'un même équipement à une seule.

    Le choix de chaque champ est explicite plutôt que « le premier gagne » :
    ce sont ces règles qui décident ce que l'exploitant voit à l'écran.
    """
    by_tool = {node.tool: node for node in members}

    # Conflicting observations must not be hidden behind a fixed tool order.
    fresh_states = {
        node.tool: node.state
        for node in members
        if node.tool != "itop" and not node.stale and node.state != "unknown"
    }
    stale_states = {
        node.tool: node.state
        for node in members
        if node.tool != "itop" and node.stale and node.state != "unknown"
    }
    # Le conflit se juge entre observations FRAÎCHES. Un état mémorisé d'un
    # outil momentanément injoignable n'est pas une observation actuelle : le
    # laisser contredire un outil qui répond rendrait « inconnu » chaque
    # équipement couvert par l'outil tombé.
    observed_states = fresh_states or stale_states
    distinct_states = set(observed_states.values())
    state_conflict = observed_states if len(distinct_states) > 1 else {}
    if len(distinct_states) > 1:
        state = "unknown"
    elif fresh_states:
        state = next(iter(fresh_states.values()))
    elif stale_states:
        state = "silent"
    else:
        state = "unknown"

    # NOM et SITE : la source de référence prime (iTop d'abord). Le nom d'un
    # équipement dans la CMDB est celui que l'organisation a choisi ; celui
    # d'un outil de supervision est souvent un identifiant technique.
    name = None
    site = None
    province = None
    region = None
    organisation = None
    node_type = None
    coordinates = None
    for tool in REFERENCE_PRIORITY:
        node = by_tool.get(tool)
        if node is None:
            continue
        name = name or node.name
        site = site or node.site
        province = province or node.province
        region = region or node.region
        coordinates = coordinates or _valid_coordinates(node.latitude, node.longitude)
        organisation = organisation or node.organisation
        node_type = node_type or node.node_type

    latitude, longitude = coordinates or (None, None)
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
        province=province,
        region=region,
        latitude=latitude,
        longitude=longitude,
        organisation=organisation,
        node_type=node_type,
        groups=groups,
        sources={node.tool: node.ref for node in members},
        state_conflict=state_conflict,
        last_known_states=stale_states if not fresh_states else {},
        stale_sources=[node.tool for node in members if node.stale],
    )


def _inherit_locality(merged: list[MergedNode]) -> None:
    """Province et région d'un site connu ailleurs dans le parc.

    Seul le référentiel NetXMS rattache un site à sa province ; un hôte
    Zabbix rangé dans « Site/Ouagadougou — DGI » ne connaît que le site. Si
    ce nom de site est rattaché sans ambiguïté à une seule province par une
    autre source, l'équipement en hérite. Un site rattaché à deux provinces
    différentes n'est pas tranché : mieux vaut « non renseignée » qu'une
    région fausse dans les statistiques territoriales.
    """
    by_site: dict[str, set[tuple[str | None, str | None]]] = defaultdict(set)
    for node in merged:
        if node.site and (node.province or node.region):
            by_site[locality_key(node.site)].add((node.province, node.region))
    for node in merged:
        if not node.site or (node.province and node.region):
            continue
        candidates = by_site.get(locality_key(node.site), set())
        if len(candidates) == 1:
            province, region = next(iter(candidates))
            node.province = node.province or province
            node.region = node.region or region


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
    by_name: dict[str, MergedNode] = {}
    ambiguous_names: set[str] = set()
    for node in merged:
        for candidate in (node.hostname, node.name):
            key = _normalise_name(candidate)
            if not key or key in ambiguous_names:
                continue
            previous = by_name.get(key)
            if previous is not None and previous.id != node.id:
                ambiguous_names.add(key)
                by_name.pop(key)
            else:
                by_name[key] = node

    severities: dict[str, list[str]] = defaultdict(list)
    orphans: list[Alert] = []

    for alert in alerts:
        node = None
        if alert.node_ref:
            node = index.get(f"{alert.tool}:{alert.node_ref}")
        if node is None and alert.node_name:
            name = _normalise_name(alert.node_name)
            if name not in ambiguous_names:
                node = by_name.get(name)
        if node is None:
            orphans.append(alert)
            continue
        if alert.kind == "technical":
            severities[node.id].append(alert.severity)

    for node in merged:
        found = severities.get(node.id, [])
        node.alerts = len(found)
        node.worst_severity = worst(found) if found else "unknown"

    return merged, orphans
