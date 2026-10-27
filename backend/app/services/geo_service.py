"""
Lecture territoriale du parc : région -> province -> site -> nœud.

UN SEUL PÉRIMÈTRE POUR TOUS LES ÉCRANS. Chaque tableau de bord accepte les
mêmes filtres — recherche libre, région, province, site — et ce module est le
seul à les appliquer. Le même équipement ne peut donc pas être compté dans
une région sur la vue d'ensemble et dans une autre sur l'écran SLA.

D'OÙ VIENT LE DÉCOUPAGE. Le collecteur rattache chaque équipement à son site,
sa province et sa région à partir des outils sources (référentiel de l'agence
dans NetXMS, groupes « Province/… » et « Region/… » ailleurs ; voir
collector/merge.py). Ce module ne devine rien : un équipement sans région est
compté sous « Région non renseignée », visible et cliquable, jamais réparti
au hasard.

ALERTES ET INCIDENTS. Les ALERTES viennent des outils de supervision
(Zabbix, Centreon, NetXMS, Nagios, NSP). Les INCIDENTS viennent d'iTop, et
d'iTop seulement. Les deux sont rattachés à l'équipement par la même règle :
la référence source, puis le nom technique quand aucune référence commune
n'existe.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.services import live_service, node_service
from integrations.normalize import locality_key

LEVELS = ("region", "province", "site", "node")

UNKNOWN = {
    "region": "Région non renseignée",
    "province": "Province non renseignée",
    "site": "Localité non renseignée",
}

# Les sources d'ALERTES. iTop n'en fait pas partie : il produit des incidents.
INCIDENT_TOOL = "itop"


def locality_of(node: dict, level: str) -> str:
    return node.get(level) or UNKNOWN[level]


def _same_place(value: str | None, wanted: str, level: str) -> bool:
    if wanted == UNKNOWN[level]:
        return not value
    return locality_key(value) == locality_key(wanted)


def _coordinates(node: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(node["latitude"]), float(node["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return lat, lon


def position(node: dict | None, nodes: list[dict]) -> dict | None:
    """Où placer un équipement sur une carte.

    Ses propres coordonnées s'il en a ; sinon le barycentre des
    équipements situés de son site, puis de sa province, puis de sa région.
    `precision` dit lequel : une carte ne doit pas présenter une position
    approchée comme l'emplacement exact de l'équipement.
    """
    if node is None:
        return None
    own = _coordinates(node)
    if own:
        return {"latitude": own[0], "longitude": own[1], "precision": "node",
                "label": node.get("name")}
    for level in ("site", "province", "region"):
        name = node.get(level)
        if not name:
            continue
        points = [
            point for other in nodes
            if _same_place(other.get(level), name, level) and (point := _coordinates(other))
        ]
        if points:
            return {
                "latitude": round(sum(p[0] for p in points) / len(points), 6),
                "longitude": round(sum(p[1] for p in points) / len(points), 6),
                "precision": level,
                "label": name,
            }
    return None


def scope_nodes(
    nodes: list[dict],
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Équipements du périmètre demandé.

    La recherche porte sur ce qu'un exploitant tape spontanément : nom,
    nom technique, adresse IP, site, province, région, organisation.
    """
    needle = (search or "").strip().casefold()
    kept = []
    for node in nodes:
        if region and not _same_place(node.get("region"), region, "region"):
            continue
        if province and not _same_place(node.get("province"), province, "province"):
            continue
        if site and not _same_place(node.get("site"), site, "site"):
            continue
        if needle:
            haystack = " ".join(
                str(node.get(field) or "")
                for field in (
                    "name", "hostname", "ip", "site", "province", "region", "organisation",
                )
            ).casefold()
            if needle not in haystack:
                continue
        kept.append(node)
    return kept


class NodeIndex:
    """Retrouve l'équipement fusionné d'une alerte ou d'un ticket."""

    def __init__(self, nodes: list[dict]):
        self.by_id = {node["id"]: node for node in nodes}
        self.by_source: dict[str, dict] = {}
        names: dict[str, list[dict]] = defaultdict(list)
        for node in nodes:
            for tool, ref in (node.get("sources") or {}).items():
                self.by_source[f"{tool}:{ref}"] = node
            for candidate in {node.get("hostname"), node.get("name")}:
                key = (candidate or "").strip().rstrip(".").casefold()
                if key:
                    names[key].append(node)
        self.names = names
        # Un nom porté par deux équipements différents ne rattache rien :
        # mieux vaut un incident sans équipement qu'un incident sur le mauvais.
        self.by_name = {
            key: members[0]
            for key, members in names.items()
            if len({member["id"] for member in members}) == 1
        }

    def find(self, tool: str | None, node_ref: str | None, node_name: str | None) -> dict | None:
        if node_ref:
            node = self.by_source.get(f"{tool}:{node_ref}")
            if node is not None:
                return node
        key = (node_name or "").strip().rstrip(".").casefold()
        return self.by_name.get(key) if key else None

    def namesakes(self, node: dict) -> list[dict]:
        """Équipements des autres outils qui portent le même nom.

        Un CI iTop non fusionné (pas d'IP commune) désigne souvent la même
        machine qu'un hôte supervisé : c'est par le nom que l'on retrouve les
        alertes techniques qui expliquent l'incident.
        """
        # Ici l'homonymie n'est PAS une ambiguïté : c'est précisément la même
        # machine vue par plusieurs outils sans IP commune pour les fusionner.
        found: dict[str, dict] = {}
        for candidate in {node.get("hostname"), node.get("name")}:
            key = (candidate or "").strip().rstrip(".").casefold()
            for other in self.names.get(key, []) if key else []:
                if other["id"] != node["id"]:
                    found[other["id"]] = other
        return list(found.values())


# Dernier résultat de `snapshot`, réutilisé tant que l'instantané Redis (mêmes
# objets désérialisés, voir live_service._read_cached) et les maintenances en
# cours n'ont pas changé. Un tableau de bord lance une dizaine de requêtes à la
# fois ; recalculer à chacune l'index du parc et le rattachement des alertes
# occupait la boucle du worker au point de faire expirer les lectures Redis.
_snapshot_cache: tuple | None = None


async def snapshot(db: Session) -> tuple[list[dict], list[dict], list[dict], NodeIndex]:
    """Parc (maintenances appliquées), alertes techniques et incidents iTop,
    chacun rattaché à son équipement et à sa localité.

    Les objets rendus sont partagés entre requêtes : ne pas les modifier.
    """
    global _snapshot_cache
    raw_nodes = await live_service.get_nodes()
    raw_records = await live_service.get_alerts()
    windows = await node_service.active_windows()
    signature = tuple((window["key"], window.get("end")) for window in windows)
    cached = _snapshot_cache
    if (
        cached is not None
        and cached[0] is raw_nodes
        and cached[1] is raw_records
        and cached[2] == signature
    ):
        return cached[3]

    nodes = node_service.apply_maintenance_windows(raw_nodes, windows)
    index = NodeIndex(nodes)
    alerts: list[dict] = []
    incidents: list[dict] = []
    for record in raw_records:
        node = index.find(record.get("tool"), record.get("node_ref"), record.get("node_name"))
        enriched = {
            **record,
            "key": f"{record['tool']}:{record['ref']}",
            "node_key": node["id"] if node else None,
            "site": node.get("site") if node else None,
            "province": node.get("province") if node else None,
            "region": node.get("region") if node else None,
        }
        if record.get("kind") == "itsm_ticket" or record.get("tool") == INCIDENT_TOOL:
            incidents.append(enriched)
        else:
            alerts.append(enriched)
    result = (nodes, alerts, incidents, index)
    # Les objets bruts sont gardés en référence : comparés par identité, ils
    # ne doivent pas être libérés (un identifiant réutilisé tromperait le cache).
    _snapshot_cache = (raw_nodes, raw_records, signature, result)
    return result


async def scoped(
    db: Session,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Équipements, alertes des outils et incidents iTop DU PÉRIMÈTRE.

    Point d'entrée commun de toutes les routes « maintenant » : un écran
    filtré sur une province ne doit montrer, dans AUCUN de ses panneaux,
    d'élément situé ailleurs. Une alerte ou un incident sans équipement
    connu sort du périmètre dès qu'une localité est demandée.
    """
    nodes, alerts, incidents, _index = await snapshot(db)
    if not (region or province or site or (search or "").strip()):
        return nodes, alerts, incidents
    kept = scope_nodes(nodes, region, province, site, search)
    ids = {node["id"] for node in kept}
    return kept, _records_in(alerts, ids), _records_in(incidents, ids)


def _records_in(records: list[dict], node_ids: set[str]) -> list[dict]:
    return [record for record in records if record.get("node_key") in node_ids]


def kpis(nodes: list[dict], alerts: list[dict], incidents: list[dict]) -> dict:
    """Indicateurs d'un ensemble d'équipements.

    Disponibilité : équipements « up » sur équipements suivis hors
    maintenance planifiée. Un état inconnu, muet ou dégradé ne prouve pas
    que l'équipement est disponible : il compte au dénominateur (même règle
    que live_service.sites_summary et collector/rollup.py).
    """
    states: dict[str, int] = defaultdict(int)
    for node in nodes:
        states[node.get("state") or "unknown"] += 1
    measured = len(nodes) - states["maintenance"]
    coordinates = [
        (float(node["latitude"]), float(node["longitude"]))
        for node in nodes
        if node.get("latitude") is not None and node.get("longitude") is not None
    ]
    return {
        "nodes": len(nodes),
        "up": states["up"],
        "down": states["down"],
        "degraded": states["degraded"],
        "silent": states["silent"],
        "maintenance": states["maintenance"],
        "unknown": states["unknown"],
        "availability_pct": round(100.0 * states["up"] / measured, 2) if measured else None,
        "alerts": len(alerts),
        "alerts_critical": sum(1 for a in alerts if a.get("severity") == "critical"),
        "alerts_unacknowledged": sum(1 for a in alerts if not a.get("acknowledged")),
        "incidents": len(incidents),
        "incidents_critical": sum(1 for i in incidents if i.get("severity") == "critical"),
        "incidents_unassigned": sum(
            1 for i in incidents if not (i.get("details") or {}).get("agent")
        ),
        # Barycentre des équipements situés : position d'une région ou d'une
        # province sur la carte. Absent si aucun équipement n'est situé.
        "latitude": (
            round(sum(c[0] for c in coordinates) / len(coordinates), 6) if coordinates else None
        ),
        "longitude": (
            round(sum(c[1] for c in coordinates) / len(coordinates), 6) if coordinates else None
        ),
        "located_nodes": len(coordinates),
    }


def _child_level(region: str | None, province: str | None, site: str | None) -> str:
    if site:
        return "node"
    if province:
        return "site"
    if region:
        return "province"
    return "region"


async def breakdown(
    db: Session,
    region: str | None = None,
    province: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> dict:
    """Le périmètre courant et ses subdivisions immédiates.

    National -> régions ; région -> provinces ; province -> sites ;
    site -> équipements. C'est la désagrégation de l'écran Territoire : un
    clic sur une ligne descend d'un niveau.
    """
    nodes, alerts, incidents, _index = await snapshot(db)
    scoped = scope_nodes(nodes, region, province, site, search)
    ids = {node["id"] for node in scoped}
    scoped_alerts = _records_in(alerts, ids)
    scoped_incidents = _records_in(incidents, ids)

    level = _child_level(region, province, site)
    rows: list[dict] = []
    if level == "node":
        alerts_by_node: dict[str, list[dict]] = defaultdict(list)
        for alert in scoped_alerts:
            alerts_by_node[alert["node_key"]].append(alert)
        incidents_by_node: dict[str, list[dict]] = defaultdict(list)
        for incident in scoped_incidents:
            incidents_by_node[incident["node_key"]].append(incident)
        for node in scoped:
            node_alerts = alerts_by_node.get(node["id"], [])
            node_incidents = incidents_by_node.get(node["id"], [])
            rows.append(
                {
                    "level": "node",
                    "key": node["id"],
                    "name": node.get("name"),
                    "hostname": node.get("hostname"),
                    "ip": node.get("ip"),
                    "state": node.get("state"),
                    "node_type": node.get("node_type"),
                    "tools": sorted((node.get("sources") or {}).keys()),
                    "latitude": node.get("latitude"),
                    "longitude": node.get("longitude"),
                    "alerts": len(node_alerts),
                    "alerts_critical": sum(
                        1 for a in node_alerts if a.get("severity") == "critical"
                    ),
                    "incidents": len(node_incidents),
                    "worst_severity": node.get("worst_severity"),
                }
            )
        state_rank = {
            "down": 0, "degraded": 1, "silent": 2, "unknown": 3, "maintenance": 4, "up": 5,
        }
        rows.sort(
            key=lambda r: (state_rank.get(r["state"], 9), -r["alerts"], (r["name"] or "").lower())
        )
    else:
        groups: dict[str, list[dict]] = defaultdict(list)
        for node in scoped:
            groups[locality_of(node, level)].append(node)
        for name, members in groups.items():
            member_ids = {node["id"] for node in members}
            row = {
                "level": level,
                "key": name,
                "name": name,
                # « unlocated » et non « unknown » : `kpis` publie déjà un
                # champ `unknown` (équipements à l'état inconnu).
                "unlocated": name == UNKNOWN[level],
                **kpis(
                    members,
                    _records_in(scoped_alerts, member_ids),
                    _records_in(scoped_incidents, member_ids),
                ),
            }
            if level in ("region", "province"):
                row["sites"] = len({locality_of(node, "site") for node in members})
            if level == "region":
                row["provinces"] = len({locality_of(node, "province") for node in members})
            rows.append(row)
        # Le plus en souffrance d'abord ; les « non renseignés » en dernier.
        rows.sort(
            key=lambda r: (
                r["unlocated"],
                -(r["down"] + r["incidents_critical"]),
                r["availability_pct"] if r["availability_pct"] is not None else 101,
                r["name"].lower(),
            )
        )

    return {
        "scope": {"region": region, "province": province, "site": site, "search": search},
        "level": level,
        "totals": kpis(scoped, scoped_alerts, scoped_incidents),
        "rows": rows,
        "snapshot_age_s": await live_service.snapshot_age_s(),
        "stale": await live_service.is_stale(),
    }


async def options(db: Session) -> dict:
    """Arbre des localités pour les sélecteurs en cascade.

    Construit sur le parc RÉEL : une région sans aucun équipement n'est pas
    proposée, parce qu'elle mènerait à un écran vide.
    """
    nodes, _alerts, _incidents, _index = await snapshot(db)
    tree: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for node in nodes:
        tree[locality_of(node, "region")][locality_of(node, "province")][
            locality_of(node, "site")
        ] += 1

    def ordered(names):
        return sorted(names, key=lambda name: (name in UNKNOWN.values(), name.lower()))

    return {
        "regions": [
            {
                "name": region,
                "nodes": sum(sum(sites.values()) for sites in provinces.values()),
                "provinces": [
                    {
                        "name": province,
                        "nodes": sum(sites.values()),
                        "sites": [
                            {"name": site, "nodes": sites[site]} for site in ordered(sites)
                        ],
                    }
                    for province, sites in ((p, provinces[p]) for p in ordered(provinces))
                ],
            }
            for region, provinces in ((r, tree[r]) for r in ordered(tree))
        ]
    }


async def site_detail(db: Session, site: str) -> dict | None:
    """Fiche d'un site : indicateurs, position, équipements, alertes, incidents."""
    nodes, alerts, incidents, _index = await snapshot(db)
    members = scope_nodes(nodes, site=site)
    if not members:
        return None
    ids = {node["id"] for node in members}
    site_alerts = _records_in(alerts, ids)
    site_incidents = _records_in(incidents, ids)
    first = members[0]
    return {
        "site": site,
        "province": first.get("province"),
        "region": first.get("region"),
        "organisations": sorted({n["organisation"] for n in members if n.get("organisation")}),
        "kpis": kpis(members, site_alerts, site_incidents),
        "nodes": (await breakdown(db, site=site))["rows"],
        "alerts": sorted(site_alerts, key=lambda a: a.get("since") or "", reverse=True)[:50],
        "incidents": sorted(site_incidents, key=lambda i: i.get("since") or "", reverse=True)[:50],
    }
