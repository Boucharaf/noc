"""
Lecture de l'état courant — l'unique source des écrans « maintenant ».

Ce module ne parle qu'à Redis. Aucune requête SQL, aucun appel vers un outil
source : le chemin chaud du tableau de bord doit rester à quelques dizaines
de microsecondes, quel que soit le nombre d'opérateurs connectés.

LA DISTINCTION QUI COMPTE. `read_*` peut rendre trois choses, et les
confondre serait le pire bogue de ce tableau de bord :

    None  -> la collecte ne tourne plus (clé expirée) ;
    []    -> la collecte tourne et ne trouve rien ;
    [...] -> la collecte tourne et a trouvé.

`SnapshotUnavailable` matérialise le premier cas. Les routes le transforment
en 503 accompagné de l'heure du dernier instantané connu, ce qui donne à
l'exploitant l'information dont il a besoin — « la collecte est arrêtée
depuis 14 h 07 » — au lieu d'un parc vide qui ressemble à un réseau en pleine
forme.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.core.config import COLLECT_INTERVAL_S, CORE_GROUPS, NODE_STATES, SUPERVISION_TOOLS
from app.db.redis_client import get_store
from collector.state import (
    KEY_ALERTS,
    KEY_LATEST,
    KEY_MAINTENANCE,
    KEY_META,
    KEY_NODES,
    KEY_TREND,
    KEY_WORK_ORDERS,
)
from integrations.config import tool_config

logger = logging.getLogger(__name__)


class SnapshotUnavailable(RuntimeError):
    """L'instantané est absent ou périmé : le collecteur ne publie plus."""

    def __init__(self, detail: str = "Collecte interrompue — aucun instantané récent"):
        self.detail = detail
        super().__init__(detail)


# Instantané désérialisé, gardé en mémoire du processus tant qu'il n'a pas
# changé. Un écran comme la vue Direction lance une vingtaine de requêtes à la
# fois ; chacune re-téléchargeait et re-désérialisait plusieurs mégaoctets de
# JSON (≈ 0,8 s à froid), la boucle du worker restait occupée, et les lectures
# Redis des requêtes voisines expiraient (HTTP 500/502).
#
# La VERSION de l'instantané est le contenu de la petite clé `noc:live:meta`,
# écrite dans la même transaction que les équipements et les alertes
# (collector/state.py::write_snapshot) : tant qu'elle n'a pas changé, rien
# n'est relu. Le verrou garantit qu'une rafale ne désérialise l'instantané
# qu'UNE fois. Les objets rendus sont PARTAGÉS entre requêtes : les appelants
# ne doivent pas les modifier en place (ils copient : {**node}).
_parsed: dict[str, tuple[str, object]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def _read_cached(key: str):
    store = get_store()
    version = await store.redis.get(KEY_META)
    if version is None:
        _parsed.pop(key, None)
        return None
    cached = _parsed.get(key)
    if cached is not None and cached[0] == version:
        return cached[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _parsed.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        raw = await store.redis.get(key)
        if raw is None:
            _parsed.pop(key, None)
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            logger.error("Instantané illisible sous %s — clé ignorée", key)
            return None
        _parsed[key] = (version, value)
        return value


async def get_meta() -> dict:
    """Métadonnées du dernier cycle. Lève si la collecte est arrêtée."""
    meta = await get_store().read_meta()
    if meta is None:
        raise SnapshotUnavailable()
    return meta


async def get_nodes() -> list[dict]:
    nodes = await _read_cached(KEY_NODES)
    if nodes is None:
        raise SnapshotUnavailable()
    return nodes


async def get_latest() -> dict[str, dict[str, float]]:
    """Dernières valeurs du dernier cycle, clé « outil:ref ». Vide si aucun
    outil branché ne les fournit (ce n'est pas une panne)."""
    return await _read_cached(KEY_LATEST) or {}


async def get_maintenance() -> list[dict]:
    """Maintenances planifiées lues dans les outils (changements iTop,
    maintenances Zabbix), rattachées au parc par le collecteur."""
    return await _read_cached(KEY_MAINTENANCE) or []


async def get_work_orders() -> list[dict]:
    """Ordres de travail iTop (interventions), rattachés au parc."""
    return await _read_cached(KEY_WORK_ORDERS) or []


_trend_cache: tuple[str, list[dict]] | None = None


async def get_trend() -> list[dict]:
    """Historique court (un point par cycle, 24 h), du plus ancien au plus
    récent. Relu une fois par cycle : il ne change qu'avec l'instantané."""
    global _trend_cache
    store = get_store()
    version = await store.redis.get(KEY_META)
    if _trend_cache is not None and version is not None and _trend_cache[0] == version:
        return _trend_cache[1]
    points = []
    for raw in await store.redis.lrange(KEY_TREND, 0, -1):
        try:
            points.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    if version is not None:
        _trend_cache = (version, points)
    return points


async def get_all_alerts() -> list[dict]:
    """Toutes les alertes non corrigées, y compris celles d'une source arrêtée."""
    alerts = await _read_cached(KEY_ALERTS)
    if alerts is None:
        raise SnapshotUnavailable()
    return alerts


_confirmed: tuple | None = None


async def get_alerts() -> list[dict]:
    """Alertes actives CONFIRMÉES : celles que comptent tous les indicateurs.

    Une alerte d'une source arrêtée (dump, export) n'en fait pas partie :
    personne ne sait si elle est toujours en cours. Même liste rendue tant que
    l'instantané ne change pas : geo_service compare les objets par identité.
    """
    global _confirmed
    alerts = await get_all_alerts()
    if _confirmed is None or _confirmed[0] is not alerts:
        _confirmed = (alerts, [a for a in alerts if not a.get("frozen")])
    return _confirmed[1]


async def get_node(node_id: str) -> dict | None:
    """Un équipement par son identifiant de fusion.

    Une recherche linéaire sur la liste, et non un index Redis par
    équipement : le parc tient en quelques milliers d'entrées, la liste est
    déjà en mémoire du processus après la désérialisation, et maintenir un
    index séparé ajouterait un chemin par lequel les deux représentations
    pourraient diverger.
    """
    for node in await get_nodes():
        if node.get("id") == node_id:
            return node
    return None


async def get_tools_health() -> list[dict]:
    """État de chaque outil configuré.

    Les outils sont énumérés depuis la CONFIGURATION et non depuis les clés
    Redis présentes : un outil configuré dont le collecteur n'a jamais réussi
    à joindre l'API doit apparaître comme « jamais collecté », pas disparaître
    de la page. C'est exactement le cas qu'un exploitant a besoin de voir.
    """
    store = get_store()
    rows = []
    for tool in SUPERVISION_TOOLS:
        configured = tool_config(tool).enabled
        health = await store.read_tool_health(tool)
        if health is None:
            rows.append(
                {
                    "tool": tool,
                    "configured": configured,
                    "reachable": False,
                    "never_collected": configured,
                    "not_configured": not configured,
                    "error": (
                        "Aucune collecte enregistrée pour cet outil"
                        if configured
                        else None
                    ),
                }
            )
        else:
            rows.append(
                {
                    **health,
                    "configured": configured,
                    "never_collected": False,
                    "not_configured": not configured,
                }
            )
    return rows


async def _meta_or_empty() -> dict:
    """Métadonnées du cycle, ou {} : une information de fraîcheur manquante
    ne doit jamais empêcher d'afficher l'inventaire ou les incidents."""
    try:
        return await get_store().read_meta() or {}
    except Exception:  # noqa: BLE001 — Redis injoignable : dégradé, pas d'erreur
        logger.warning("Métadonnées de collecte illisibles", exc_info=True)
        return {}


async def source_collected_at() -> dict[str, str]:
    """Heure de la dernière collecte RÉUSSIE de l'inventaire, par outil.

    Lue dans les métadonnées du cycle (`source_data.<outil>.nodes`). Un outil
    tombé garde l'heure de sa dernière collecte complète : c'est exactement
    l'âge de ce que l'écran affiche pour ses équipements.
    """
    meta = await _meta_or_empty()
    rows = {}
    for tool, streams in (meta.get("source_data") or {}).items():
        stream = (streams or {}).get("nodes") or {}
        # Source arrêtée : sa dernière donnée, pas l'heure de la relecture.
        stamp = stream.get("data_until") or stream.get("collected_at")
        if stamp:
            rows[tool] = stamp
    return rows


async def frozen_sources() -> dict[str, str]:
    """{outil: date de la dernière donnée} des sources arrêtées."""
    meta = await _meta_or_empty()
    return {
        tool: until
        for tool, streams in (meta.get("source_data") or {}).items()
        if (until := ((streams or {}).get("nodes") or {}).get("data_until"))
    }


async def source_stream(tool: str, stream: str = "alerts") -> dict:
    """État d'un flux d'un outil au dernier cycle : {stale, collected_at, …}.

    Vide si l'outil n'a jamais été collecté. `stale` vrai : l'outil n'a pas
    répondu, l'écran montre sa dernière collecte réussie.
    """
    meta = await _meta_or_empty()
    return dict(((meta.get("source_data") or {}).get(tool) or {}).get(stream) or {})


def last_seen_at(node: dict, collected: dict[str, str]) -> str | None:
    """Dernière OBSERVATION d'un équipement par un outil de supervision.

    INC-03 / INC-04 : la colonne « Vu » lisait un champ que rien ne publiait
    et affichait « jamais » pour tout le parc, y compris les équipements
    NORMAL. L'heure retenue est la dernière collecte réussie des outils qui
    le supervisent (iTop, la CMDB, n'observe rien). None : aucun outil de
    supervision ne le voit — il est alors « non supervisé ».
    """
    stamps = [
        collected[tool] for tool in (node.get("sources") or {})
        if tool != "itop" and tool in collected
    ]
    return max(stamps) if stamps else None


def is_fresh(stamp: str | None) -> bool:
    """Observation récente : moins de deux intervalles de collecte (INC-03)."""
    if not stamp:
        return False
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() <= 2 * COLLECT_INTERVAL_S


async def snapshot_age_s() -> float | None:
    """Âge de l'instantané, en secondes. None si aucun instantané.

    Utilisé par la barre d'état du tableau de bord : au-delà de deux
    intervalles de collecte, l'interface affiche un avertissement plutôt que
    de laisser croire à des données fraîches.
    """
    meta = await get_store().read_meta()
    if not meta or not meta.get("collected_at"):
        return None
    try:
        collected = datetime.fromisoformat(meta["collected_at"])
    except (TypeError, ValueError):
        return None
    if collected.tzinfo is None:
        collected = collected.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - collected).total_seconds()


async def is_stale() -> bool:
    age = await snapshot_age_s()
    return age is None or age > COLLECT_INTERVAL_S * 2


# ---------------------------------------------------------------------------
# Agrégats sur l'instantané
# ---------------------------------------------------------------------------
# Calculés à la volée sur une liste déjà en mémoire, sans cache. Sur quelques
# milliers d'équipements, un décompte coûte moins qu'une lecture Redis
# supplémentaire ; mettre en cache ajouterait une seconde source de vérité
# pour économiser des microsecondes.
async def fleet_summary(
    nodes: list[dict] | None = None, records: list[dict] | None = None
) -> dict:
    """`records` : alertes et tickets du périmètre ; tout l'instantané sinon."""
    nodes = await get_nodes() if nodes is None else nodes
    all_records = await get_alerts() if records is None else records
    alerts = [
        record for record in all_records
        if record.get("kind", "technical") == "technical"
    ]
    itsm_tickets = [record for record in all_records if record.get("kind") == "itsm_ticket"]

    by_state: dict[str, int] = {}
    for node in nodes:
        state = node.get("state", "unknown")
        by_state[state] = by_state.get(state, 0) + 1

    by_severity: dict[str, int] = {}
    for alert in alerts:
        severity = alert.get("severity", "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1

    total = len(nodes)
    up = by_state.get("up", 0)
    supervised = supervised_count(by_state)
    unsupervised = by_state.get("unknown", 0) + by_state.get("silent", 0)
    return {
        "nodes_total": total,
        "nodes_by_state": by_state,
        "alerts_total": len(alerts),
        "itsm_tickets_total": len(itsm_tickets),
        "alerts_by_severity": by_severity,
        "alerts_unacknowledged": sum(
            1 for a in alerts if not a.get("acknowledged")
        ),
        # Proportion d'équipements joignables. Ce n'est PAS une disponibilité
        # au sens du SLA d'un équipement donné — c'est un indicateur de santé
        # du parc à l'instant présent, et il est nommé pour qu'on ne les
        # confonde pas.
        "fleet_health_pct": round(100.0 * up / total, 2) if total else None,
        # « Parc en service (instantané) » : en service ÷ équipements
        # SUPERVISÉS. Un équipement sans observation (inconnu, muet) n'est
        # ni en service ni en panne : il est compté à part (non supervisé) et
        # n'entre pas dans le dénominateur — sinon un site sans supervision
        # s'affiche à 0 % sans aucune panne (amendement CTC, AM-29).
        # None = aucun équipement supervisé : l'écran affiche « Non supervisé ».
        "fleet_availability_pct": (
            round(100.0 * up / supervised, 2) if supervised else None
        ),
        "nodes_supervised": supervised,
        "nodes_unsupervised": unsupervised,
        # Base du calcul, affichée sous l'indicateur (AM-34) : « 956 / 1 381 ».
        "availability_basis": {
            "up": up,
            "supervised": supervised,
            "unsupervised": unsupervised,
            "maintenance": by_state.get("maintenance", 0),
            "total": total,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def is_core(node: dict) -> bool:
    """Équipement de cœur : membre d'un groupe de NOC_CORE_GROUPS."""
    return any(str(group).strip().lower() in CORE_GROUPS for group in node.get("groups") or ())


async def core_node_ids() -> set[str] | None:
    """None si l'instantané est indisponible : la classe est alors inconnue."""
    try:
        return {node["id"] for node in await get_nodes() if is_core(node)}
    except SnapshotUnavailable:
        return None


def supervised_count(by_state: dict[str, int]) -> int:
    """Équipements dont l'état est OBSERVÉ : en service, dégradés ou en panne.

    Règle unique du NOC (AM-29) : la maintenance planifiée et l'absence
    d'observation (inconnu, muet) sortent du dénominateur de tous les taux.
    """
    return sum(by_state.get(state, 0) for state in ("up", "degraded", "down"))


async def sites_summary(
    nodes: list[dict] | None = None, records: list[dict] | None = None
) -> list[dict]:
    """Synthèse par site, triée du plus dégradé au plus sain."""
    nodes = await get_nodes() if nodes is None else nodes
    records = await get_alerts() if records is None else records
    # Alertes critiques par site, rattachées par la référence source de
    # l'équipement — la même clé que la fusion (collector/merge.py).
    site_of_source: dict[str, str] = {}
    for node in nodes:
        for tool, ref in (node.get("sources") or {}).items():
            site_of_source[f"{tool}:{ref}"] = node.get("site") or "Localité non renseignée"
    critical_by_site: dict[str, int] = {}
    for alert in records:
        if alert.get("kind", "technical") != "technical" or alert.get("severity") != "critical":
            continue
        site = site_of_source.get(f"{alert.get('tool')}:{alert.get('node_ref')}")
        if site:
            critical_by_site[site] = critical_by_site.get(site, 0) + 1
    sites: dict[str, dict] = {}
    for node in nodes:
        # Les équipements sans localité connue sont regroupés explicitement
        # plutôt qu'écartés : leur nombre est le meilleur indicateur de la
        # qualité des conventions de nommage côté outils sources.
        key = node.get("site") or "Localité non renseignée"
        bucket = sites.setdefault(
            key,
            {
                "site": key,
                "province": node.get("province"),
                "region": node.get("region"),
                "nodes": 0,
                "up": 0,
                "down": 0,
                "degraded": 0,
                "silent": 0,
                "maintenance": 0,
                "unknown": 0,
                "alerts": 0,
                "critical": critical_by_site.get(key, 0),
                "latitude": None,
                "longitude": None,
            },
        )
        bucket["nodes"] += 1
        if (
            bucket["latitude"] is None
            and node.get("latitude") is not None
            and node.get("longitude") is not None
        ):
            bucket["latitude"] = node["latitude"]
            bucket["longitude"] = node["longitude"]
        if node.get("state") == "up":
            bucket["up"] += 1
        elif node.get("state") == "down":
            bucket["down"] += 1
        elif node.get("state") == "degraded":
            bucket["degraded"] += 1
        elif node.get("state") == "silent":
            bucket["silent"] += 1
        elif node.get("state") == "maintenance":
            bucket["maintenance"] += 1
        elif node.get("state") == "unknown":
            bucket["unknown"] += 1
        bucket["alerts"] += node.get("alerts", 0)

    for bucket in sites.values():
        # Dénominateur = équipements supervisés (en service, dégradés, en
        # panne). Inconnus et muets sont comptés à part (`unsupervised`) :
        # ils ne prouvent ni la disponibilité ni la panne (AM-29). Un site
        # sans aucun équipement supervisé rend None → « Non supervisé ».
        supervised = supervised_count(bucket)
        bucket["supervised"] = supervised
        bucket["unsupervised"] = bucket["unknown"] + bucket["silent"]
        bucket["availability_pct"] = (
            round(100 * bucket["up"] / supervised, 2) if supervised else None
        )

    rows = list(sites.values())
    rows.sort(
        key=lambda r: (
            -r["down"],
            -r["degraded"],
            -r["silent"],
            -r["alerts"],
            r["site"],
        )
    )
    return rows


async def summarise_organisations(
    nodes: list[dict] | None = None,
) -> list[dict]:
    """Summarise live node health by organisation, including unknown values."""
    nodes = await get_nodes() if nodes is None else nodes
    organisations: dict[str, dict] = {}
    for node in nodes:
        name = node.get("organisation") or "Organisation non renseignée"
        bucket = organisations.setdefault(
            name,
            {
                "organisation": name,
                "nodes": 0,
                "up": 0,
                "down": 0,
                "degraded": 0,
                "silent": 0,
                "maintenance": 0,
                "unknown": 0,
                "alerts": 0,
            },
        )
        bucket["nodes"] += 1
        state = node.get("state", "unknown")
        bucket[state if state in NODE_STATES else "unknown"] += 1
        bucket["alerts"] += node.get("alerts", 0)

    for bucket in organisations.values():
        supervised = supervised_count(bucket)
        bucket["supervised"] = supervised
        bucket["unsupervised"] = bucket["unknown"] + bucket["silent"]
        bucket["availability_pct"] = (
            round(100 * bucket["up"] / supervised, 2) if supervised else None
        )
    return sorted(
        organisations.values(),
        key=lambda row: (-row["down"], -row["degraded"], -row["alerts"], row["organisation"]),
    )
