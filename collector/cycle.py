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

3. **Un instantané partiel est publié, jamais un instantané vide inventé.**
   Si Zabbix répond et Centreon non, le NOC affiche le parc Zabbix et signale
   Centreon en panne. Si aucune source ni aucun cache valide ne fournit de
   données, l'instantané précédent est conservé au lieu de présenter un parc
   vide comme sain.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from integrations.base import SourceClient
from integrations.models import Alert, Node, ToolHealth, ToolSnapshot

from . import config
from .merge import MergedNode, attach_alerts, merge_nodes
from .operations import active_maintenance_keys, link_operations
from .rollup import observe, rollup_key
from .state import SnapshotStore, build_meta
from .trend import sample as trend_sample

logger = logging.getLogger(__name__)


def _cached_nodes(payload: dict | None) -> tuple[list[Node], str | None]:
    if payload is None:
        return [], None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("records"), list)
        or not isinstance(payload.get("collected_at"), str)
        or not payload["collected_at"]
    ):
        logger.error("Instantané source d'inventaire incomplet, rejeté")
        return [], None
    collected_at = payload.get("collected_at")
    nodes = []
    for record in payload["records"]:
        if not isinstance(record, dict):
            logger.error("Entrée d'inventaire mémorisée invalide, collecte rejetée")
            return [], None
        try:
            record = dict(record)
            record["groups"] = tuple(record.get("groups") or ())
            record["observed_at"] = datetime.fromisoformat(record["observed_at"])
            record["stale"] = True
            nodes.append(Node(**record))
        except (KeyError, TypeError, ValueError):
            logger.exception("Équipement mémorisé invalide, collecte rejetée")
            return [], None
    return nodes, collected_at


def _cached_alerts(payload: dict | None) -> tuple[list[Alert], str | None]:
    if payload is None:
        return [], None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("records"), list)
        or not isinstance(payload.get("collected_at"), str)
        or not payload["collected_at"]
    ):
        logger.error("Instantané source d'alertes incomplet, rejeté")
        return [], None
    collected_at = payload.get("collected_at")
    alerts = []
    for record in payload["records"]:
        if not isinstance(record, dict):
            logger.error("Entrée d'alerte mémorisée invalide, collecte rejetée")
            return [], None
        try:
            record = dict(record)
            record["since"] = datetime.fromisoformat(record["since"])
            if record.get("acknowledged_at"):
                record["acknowledged_at"] = datetime.fromisoformat(
                    record["acknowledged_at"]
                )
            record["last_observed_at"] = datetime.fromisoformat(
                record["last_observed_at"]
            )
            record["stale"] = True
            alerts.append(Alert(**record))
        except (KeyError, TypeError, ValueError):
            logger.exception("Alerte mémorisée invalide, collecte rejetée")
            return [], None
    return alerts, collected_at


async def _fallback_source_data(store, name: str, collection: str):
    payload = await store.read_source_data(name, collection)
    if collection == "nodes":
        return _cached_nodes(payload)
    return _cached_alerts(payload)


def _observe_rollup(
    merged: list[MergedNode],
    alerts: list[Alert],
    at: datetime,
    maintenance_node_keys: set[str],
    maintenance_sites: set[str],
) -> None:
    """Ventile l'observation du cycle par site, pour le bilan journalier.

    Une entrée « tous sites confondus » (site None) est tenue en plus des
    entrées par site : sans elle, le total du parc ne serait pas la somme des
    sites, puisque les équipements sans localité connue en sont absents.
    """
    day = at.date()
    observe(
        day, None, merged, alerts, maintenance_node_keys, maintenance_sites
    )

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
        observe(
            day,
            site,
            nodes,
            alerts_by_site.get(site, []),
            maintenance_node_keys,
            maintenance_sites,
        )

    # Mêmes comptes par région et par province : sans eux, les tendances
    # d'un tableau de bord filtré sur une région resteraient celles du pays.
    for level in ("region", "province"):
        members: dict[str, list[MergedNode]] = {}
        place_of_source: dict[str, str] = {}
        for node in merged:
            name = getattr(node, level)
            if not name:
                continue
            members.setdefault(name, []).append(node)
            for tool, ref in node.sources.items():
                place_of_source[f"{tool}:{ref}"] = name
        alerts_by_place: dict[str, list[Alert]] = {}
        for alert in alerts:
            name = place_of_source.get(f"{alert.tool}:{alert.node_ref}")
            if name:
                alerts_by_place.setdefault(name, []).append(alert)
        for name, nodes in members.items():
            observe(
                day,
                rollup_key(level, name),
                nodes,
                alerts_by_place.get(name, []),
                maintenance_node_keys,
                maintenance_sites,
            )


async def _cached_records(store, name: str, collection: str) -> list[dict]:
    """Dernière collecte réussie de maintenances / ordres de travail."""
    payload = await store.read_source_data(name, collection)
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return [record for record in payload["records"] if isinstance(record, dict)]
    return []


async def poll_tool(name: str, client) -> ToolSnapshot:
    """Interroge un outil. Ne lève jamais.

    L'inventaire et les alertes sont demandés EN PARALLÈLE : ce sont deux
    appels indépendants, les enchaîner doublerait la durée du cycle pour rien.
    """
    health = await client.check()
    if not health.reachable:
        logger.warning("%s injoignable : %s", name, health.error)
        return ToolSnapshot(
            health=health,
            nodes_complete=False,
            alerts_complete=False,
        )

    warnings = getattr(client, "collection_warnings", None)
    if warnings is not None:
        warnings.clear()
    nodes_task = asyncio.create_task(client.fetch_nodes())
    alerts_task = asyncio.create_task(client.fetch_alerts())
    # Dernières valeurs du parc (latence, débits, CPU…) : seulement pour les
    # outils qui savent les rendre en un appel groupé.
    latest_task = (
        asyncio.create_task(client.fetch_fleet_latest())
        if type(client).fetch_fleet_latest is not SourceClient.fetch_fleet_latest
        else None
    )
    operations_tasks = {
        label: asyncio.create_task(getattr(client, method)())
        for label, method in (("maintenance", "fetch_maintenance"), ("work_orders", "fetch_work_orders"))
        if getattr(type(client), method) is not getattr(SourceClient, method)
    }
    results = await asyncio.gather(nodes_task, alerts_task, return_exceptions=True)
    operations: dict[str, tuple | None] = {"maintenance": None, "work_orders": None}
    for label, task in operations_tasks.items():
        try:
            operations[label] = tuple(await task)
        except Exception as exc:  # noqa: BLE001 — l'inventaire et les alertes
            # ne dépendent pas des maintenances : leur échec reste local.
            logger.warning("%s : %s indisponibles — %s", name, label, exc)
    latest: dict = {}
    if latest_task is not None:
        try:
            latest = await latest_task
        except Exception as exc:  # noqa: BLE001 — mesures d'appoint : leur
            # échec ne doit marquer ni l'inventaire ni les alertes en défaut.
            logger.warning("%s : dernières valeurs indisponibles — %s", name, exc)

    nodes: list[Node] = []
    alerts: list[Alert] = []
    nodes_complete = True
    alerts_complete = True
    errors: list[str] = []

    for label, result in zip(("inventaire", "alertes"), results):
        if isinstance(result, BaseException):
            logger.warning("%s : échec de la collecte des %s — %s", name, label, result)
            errors.append(f"{label} : {result}")
            if label == "inventaire":
                nodes_complete = False
            else:
                alerts_complete = False
        elif label == "inventaire":
            # Les références peuvent aussi décrire des objets désactivés ou
            # retirés; ils ne font pas partie du parc supervisé courant.
            nodes = [node for node in result if node.enabled]
        else:
            alerts = list(result)

    warnings = getattr(client, "collection_warnings", ())
    errors.extend(f"collecte partielle : {warning}" for warning in warnings)
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
    return ToolSnapshot(
        health=health,
        nodes=tuple(nodes),
        alerts=tuple(alerts),
        nodes_complete=nodes_complete,
        alerts_complete=alerts_complete,
        latest=latest,
        maintenance=operations["maintenance"],
        work_orders=operations["work_orders"],
    )


async def run_cycle(
    clients: dict,
    store: SnapshotStore,
    timeout_s: float,
) -> dict:
    """Exécute un cycle et publie seulement s'il existe une source valide."""
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
    source_data_status: dict[str, dict[str, dict[str, object]]] = {}
    # Dernières valeurs, clé « outil:ref » — la même que Node.key().
    latest_values: dict[str, dict[str, float]] = {}
    maintenance_records: list[dict] = []
    work_order_records: list[dict] = []

    async def collect_stream(
        name: str,
        collection: str,
        fresh: bool,
        records: tuple | list,
        destination: list,
    ) -> dict[str, object]:
        if fresh:
            values = list(records)
            await store.write_source_data(name, collection, values, started_at)
            destination.extend(values)
            return {"stale": False, "collected_at": started_at.isoformat()}

        values, collected_at = await _fallback_source_data(store, name, collection)
        destination.extend(values)
        if collected_at:
            logger.warning(
                "%s : conservation des %d éléments %s du dernier succès (%s)",
                name,
                len(values),
                collection,
                collected_at,
            )
        return {
            "stale": bool(collected_at),
            "collected_at": collected_at,
            "available": bool(collected_at),
        }

    for name, task in tasks.items():
        if task in pending:
            health = ToolHealth(
                tool=name,
                reachable=False,
                error=f"délai de cycle dépassé ({timeout_s:.0f} s)",
            )
            await store.write_tool_health(health)
            source_data_status[name] = {
                "nodes": await collect_stream(name, "nodes", False, (), all_nodes),
                "alerts": await collect_stream(name, "alerts", False, (), all_alerts),
            }
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
            source_data_status[name] = {
                "nodes": await collect_stream(name, "nodes", False, (), all_nodes),
                "alerts": await collect_stream(name, "alerts", False, (), all_alerts),
            }
            tools_failed.append(name)
            continue

        await store.write_tool_health(snapshot.health)
        source_data_status[name] = {
            "nodes": await collect_stream(
                name, "nodes", snapshot.nodes_complete, snapshot.nodes, all_nodes
            ),
            "alerts": await collect_stream(
                name, "alerts", snapshot.alerts_complete, snapshot.alerts, all_alerts
            ),
        }
        (tools_ok if snapshot.health.reachable else tools_failed).append(name)
        for ref, values in snapshot.latest.items():
            latest_values[f"{name}:{ref}"] = values
        for collection, records, destination in (
            ("maintenance", snapshot.maintenance, maintenance_records),
            ("work_orders", snapshot.work_orders, work_order_records),
        ):
            if records is not None:
                await store.write_source_data(name, collection, list(records), started_at)
                destination.extend(records)
            else:
                destination.extend(await _cached_records(store, name, collection))

    has_source_snapshot = any(
        stream.get("collected_at")
        for streams in source_data_status.values()
        for stream in streams.values()
    )
    if not has_source_snapshot:
        logger.error(
            "Aucune source ni collecte mémorisée disponible : "
            "instantané précédent conservé"
        )
        return {
            "snapshot_published": False,
            "tools_ok": tools_ok,
            "tools_failed": tools_failed,
            "source_data": source_data_status,
        }

    merged, report = merge_nodes(all_nodes)
    # Un seul état « inconnu » pour l'exploitant : qu'un outil ne remonte plus
    # rien (muet) ou qu'aucun état ne soit mesuré, on ne sait pas si
    # l'équipement fonctionne — et il compte de la même façon (non disponible).
    for node in merged:
        if node.state == "silent":
            node.state = "unknown"
    merged, orphans = attach_alerts(merged, all_alerts)
    technical_alerts = [alert for alert in all_alerts if alert.kind == "technical"]
    itsm_tickets = [alert for alert in all_alerts if alert.kind == "itsm_ticket"]

    link_operations(merged, maintenance_records, work_order_records)
    # Maintenance en cours : celle que déclarent iTop (changements) et Zabbix,
    # plus les équipements que leur outil dit en maintenance (Nagios
    # downtime, hôte Zabbix en maintenance) — `state` le porte déjà.
    maintenance = (
        active_maintenance_keys(maintenance_records, started_at)
        | {node.id for node in merged if node.state == "maintenance"},
        set(),
    )

    meta = build_meta(
        started_at=started_at,
        duration_s=time.perf_counter() - started,
        nodes=len(merged),
        alerts=len(technical_alerts),
        tools_ok=tools_ok,
        tools_failed=tools_failed,
    )
    meta["itsm_tickets"] = len(itsm_tickets)
    meta["source_data"] = source_data_status
    meta["merge"] = {
        "raw": report.total_raw,
        "merged": report.total_merged,
        "matched_by_ip": report.matched_by_ip,
        "matched_by_name": report.matched_by_name,
        "matched_by_verified_identity": report.matched_by_verified_identity,
        "ambiguous_total": report.ambiguous_total,
        "ambiguities": report.ambiguities,
        "state_conflicts": report.state_conflicts,
        "single_source": report.single_source[:50],
    }
    meta["orphan_alerts"] = len(orphans)

    # AVANT l'instantané : le backend recale ses caches sur la version de
    # l'instantané (clé meta) et relirait sinon les valeurs du cycle précédent.
    await store.write_latest(latest_values)
    await store.write_operations(maintenance_records, work_order_records)
    await store.write_snapshot(merged, all_alerts, meta)
    try:
        await store.append_trend(trend_sample(merged, all_alerts, maintenance[0], started_at))
    except Exception:  # noqa: BLE001 — les mini-courbes ne valent pas un cycle perdu
        logger.exception("Historique court non enregistré")

    # Alimente les compteurs du bilan journalier (collector/rollup.py). Fait
    # ici, dans le cycle, et non par une requête séparée : l'agrégat doit
    # porter sur ce qui a RÉELLEMENT été observé, cycle par cycle, y compris
    # les cycles où un outil manquait à l'appel.
    if config.ROLLUP_ENABLED:
        _observe_rollup(merged, technical_alerts, started_at, *maintenance)

    # La diffusion se fait APRÈS l'écriture de l'instantané : un navigateur
    # réveillé par une nouvelle alerte va immédiatement relire le parc, et il
    # doit y trouver l'équipement concerné.
    new_alerts = await store.diff_new_alerts(technical_alerts)
    if new_alerts:
        logger.info("%d nouvelle(s) alerte(s) diffusée(s)", len(new_alerts))
        await store.publish_new_alerts(new_alerts)

    logger.info(
        "Cycle terminé en %.1f s — %d équipement(s) après fusion (%d bruts), "
        "%d alerte(s), outils en échec : %s",
        meta["duration_s"],
        report.total_merged,
        report.total_raw,
        len(technical_alerts),
        ", ".join(tools_failed) or "aucun",
    )
    return meta
