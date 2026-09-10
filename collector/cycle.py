"""
Un cycle de collecte : interroger tous les outils, fusionner, publier.

TROIS PROPRIÉTÉS QUE CE MODULE DOIT GARANTIR, et qui expliquent sa forme :

1. **Un outil en panne n'en empêche aucun autre.** Chaque outil est
   interrogé dans sa propre tâche, et son échec est capturé au niveau de la
   tâche. Un `gather` sans `return_exceptions` propagerait la première
   exception et perdrait les réponses déjà obtenues des autres outils.

2. **Le cycle est borné dans le temps.** Un outil qui ne répond ni ne coupe
   — le cas le plus pénible — bloquerait la collecte indéfiniment. Au-delà
   de `CYCLE_TIMEOUT_S`, on publie ce qu'on a et on note l'outil en échec.

3. **Un instantané partiel est publié, jamais un instantané vide.** Si Zabbix
   répond et Centreon non, le NOC affiche le parc Zabbix et signale Centreon
   en panne. Ne rien publier ferait expirer l'instantané et éteindrait le
   tableau de bord entier pour la défaillance d'une seule source.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from integrations.models import Alert, Node, ToolHealth, ToolSnapshot

from .merge import MergedNode, attach_alerts, merge_nodes
from .rollup import observe
from .state import SnapshotStore, build_meta

logger = logging.getLogger(__name__)


def _observe_rollup(
    merged: list[MergedNode], alerts: list[Alert], at: datetime
) -> None:
    """Ventile l'observation du cycle par site, pour le bilan journalier.

    Une entrée « tous sites confondus » (site None) est tenue en plus des
    entrées par site : sans elle, le total du parc ne serait pas la somme des
    sites, puisque les équipements sans localité connue en sont absents.
    """
    day = at.date()
    observe(day, None, merged, alerts)

    by_site: dict[str, list[MergedNode]] = {}
    # Index (outil, référence) -> site, construit une seule fois : rechercher
    # le site de chaque alerte en reparcourant le parc coûterait le produit
    # des deux, soit plusieurs millions de comparaisons sur un parc chargé.
    site_of_source: dict[str, str] = {}
    for node in merged:
        if not node.site:
            continue
        by_site.setdefault(node.site, []).append(node)
        for tool, ref in node.sources.items():
            site_of_source[f"{tool}:{ref}"] = node.site

    # Les alertes suivent l'équipement auquel la fusion les a rattachées.
    # Celles restées orphelines ne comptent que dans le total : leur
    # attribuer un site au hasard fausserait les statistiques par localité.
    alerts_by_site: dict[str, list[Alert]] = {}
    for alert in alerts:
        site = site_of_source.get(f"{alert.tool}:{alert.node_ref}")
        if site:
            alerts_by_site.setdefault(site, []).append(alert)

    for site, nodes in by_site.items():
        observe(day, site, nodes, alerts_by_site.get(site, []))


async def poll_tool(name: str, client) -> ToolSnapshot:
    """Interroge un outil. Ne lève jamais.

    L'inventaire et les alertes sont demandés EN PARALLÈLE : ce sont deux
    appels indépendants, les enchaîner doublerait la durée du cycle pour rien.
    """
    health = await client.check()
    if not health.reachable:
        logger.warning("%s injoignable : %s", name, health.error)
        return ToolSnapshot(health=health)

    nodes_task = asyncio.create_task(client.fetch_nodes())
    alerts_task = asyncio.create_task(client.fetch_alerts())
    results = await asyncio.gather(nodes_task, alerts_task, return_exceptions=True)

    nodes: list[Node] = []
    alerts: list[Alert] = []
    errors: list[str] = []

    for label, result in zip(("inventaire", "alertes"), results):
        if isinstance(result, BaseException):
            logger.warning("%s : échec de la collecte des %s — %s", name, label, result)
            errors.append(f"{label} : {result}")
        elif label == "inventaire":
            nodes = list(result)
        else:
            alerts = list(result)

    if errors:
        # L'outil a répondu au contrôle de santé mais pas à la donnée : c'est
        # une panne PARTIELLE, et elle doit se lire comme telle sur l'écran
        # Interopérabilité. La marquer « joignable » sans plus serait faux.
        health = ToolHealth(
            tool=name,
            reachable=False,
            latency_ms=health.latency_ms,
            version=health.version,
            error="; ".join(errors),
        )

    logger.info(
        "%s : %d équipement(s), %d alerte(s) active(s)", name, len(nodes), len(alerts)
    )
    return ToolSnapshot(health=health, nodes=tuple(nodes), alerts=tuple(alerts))


async def run_cycle(
    clients: dict,
    store: SnapshotStore,
    timeout_s: float,
) -> dict:
    """Exécute un cycle complet et publie l'instantané. Rend les métadonnées."""
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    tasks = {
        name: asyncio.create_task(poll_tool(name, client), name=f"collecte-{name}")
        for name, client in clients.items()
    }

    done, pending = await asyncio.wait(tasks.values(), timeout=timeout_s)

    # Les tâches encore en cours sont annulées : le cycle suivant repartira
    # proprement. Les laisser vivre ferait s'empiler les requêtes vers un
    # outil déjà en difficulté — exactement ce qu'il ne faut pas faire.
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    all_nodes: list[Node] = []
    all_alerts: list[Alert] = []
    tools_ok: list[str] = []
    tools_failed: list[str] = []

    for name, task in tasks.items():
        if task in pending:
            health = ToolHealth(
                tool=name,
                reachable=False,
                error=f"délai de cycle dépassé ({timeout_s:.0f} s)",
            )
            await store.write_tool_health(health)
            tools_failed.append(name)
            logger.error("%s : délai de cycle dépassé, tâche annulée", name)
            continue

        try:
            snapshot: ToolSnapshot = task.result()
        except Exception:  # noqa: BLE001 — poll_tool ne devrait jamais lever,
            # mais un cycle de collecte ne peut pas dépendre de ce « devrait ».
            logger.exception("%s : exception inattendue pendant la collecte", name)
            health = ToolHealth(tool=name, reachable=False, error="exception interne")
            await store.write_tool_health(health)
            tools_failed.append(name)
            continue

        await store.write_tool_health(snapshot.health)
        all_nodes.extend(snapshot.nodes)
        all_alerts.extend(snapshot.alerts)
        (tools_ok if snapshot.health.reachable else tools_failed).append(name)

    merged, report = merge_nodes(all_nodes)
    merged, orphans = attach_alerts(merged, all_alerts)

    meta = build_meta(
        started_at=started_at,
        duration_s=time.perf_counter() - started,
        nodes=len(merged),
        alerts=len(all_alerts),
        tools_ok=tools_ok,
        tools_failed=tools_failed,
    )
    meta["merge"] = {
        "raw": report.total_raw,
        "merged": report.total_merged,
        "matched_by_ip": report.matched_by_ip,
        "matched_by_name": report.matched_by_name,
        "single_source": report.single_source[:50],
    }
    meta["orphan_alerts"] = len(orphans)

    await store.write_snapshot(merged, all_alerts, meta)

    # Alimente les compteurs du bilan journalier (collector/rollup.py). Fait
    # ici, dans le cycle, et non par une requête séparée : l'agrégat doit
    # porter sur ce qui a RÉELLEMENT été observé, cycle par cycle, y compris
    # les cycles où un outil manquait à l'appel.
    _observe_rollup(merged, all_alerts, started_at)

    # La diffusion se fait APRÈS l'écriture de l'instantané : un navigateur
    # réveillé par une nouvelle alerte va immédiatement relire le parc, et il
    # doit y trouver l'équipement concerné.
    new_alerts = await store.diff_new_alerts(all_alerts)
    if new_alerts:
        logger.info("%d nouvelle(s) alerte(s) diffusée(s)", len(new_alerts))
        await store.publish_new_alerts(new_alerts)

    logger.info(
        "Cycle terminé en %.1f s — %d équipement(s) après fusion (%d bruts), "
        "%d alerte(s), outils en échec : %s",
        meta["duration_s"],
        report.total_merged,
        report.total_raw,
        len(all_alerts),
        ", ".join(tools_failed) or "aucun",
    )
    return meta
