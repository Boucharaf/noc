"""
Écriture et lecture de l'instantané Redis.

CE MODULE EST LE CONTRAT entre le collecteur et le backend. Il est le seul
endroit du dépôt qui connaisse les noms de clés Redis ; tout le reste passe
par ses fonctions. Le contrat lui-même est documenté dans ARCHITECTURE.md,
section « Contrat de l'instantané Redis ».

DEUX RÈGLES QUI EXPLIQUENT TOUT LE FICHIER :

1. **L'instantané courant est réécrit en entier, jamais mis à jour par
   morceaux.** Les dernières collectes complètes de chaque flux source sont
   conservées séparément. Une absence constatée après une collecte complète
   retire les objets ; un échec de collecte réutilise les anciennes données
   et les marque périmées au lieu de les faire disparaître ou de les
   présenter comme saines.

2. **Tout porte une durée de vie de trois cycles.** Si le collecteur meurt,
   les clés expirent et le backend cesse de servir un état périmé : il répond
   explicitement « collecte interrompue » au lieu d'afficher un parc
   faussement calme. Un instantané muet est un incident, pas une absence
   d'incident.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from integrations.models import to_jsonable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Espace de noms
# ---------------------------------------------------------------------------
PREFIX = "noc:"
KEY_NODES = f"{PREFIX}live:nodes"
KEY_ALERTS = f"{PREFIX}live:alerts"
KEY_META = f"{PREFIX}live:meta"
KEY_TOOL = f"{PREFIX}tool:"          # + nom de l'outil
KEY_SOURCE = f"{PREFIX}source:"      # + outil:nodes|alerts, last valid collection
KEY_HISTORY = f"{PREFIX}hist:"       # + outil:empreinte
KEY_ALERT_SEEN = f"{PREFIX}live:alerts:seen"
# Marqueur « le NOC a déjà vu un cycle » : distinct de l'ensemble des alertes
# vues, qui peut légitimement être vide (aucune alerte en cours).
KEY_ALERT_SEEN_SINCE = f"{PREFIX}live:alerts:seen_since"
# Compteurs du bilan journalier en cours (collector/rollup.py), sauvegardés à
# chaque cycle : un redémarrage du collecteur ne perd plus la journée.
KEY_ROLLUP = f"{PREFIX}rollup:pending"
KEY_LATEST = f"{PREFIX}live:latest"  # dernières valeurs, « outil:ref » -> {métrique: valeur}
KEY_MAINTENANCE = f"{PREFIX}live:maintenance"  # maintenances planifiées (iTop, Zabbix)
KEY_WORK_ORDERS = f"{PREFIX}live:work_orders"  # ordres de travail iTop
KEY_TREND = f"{PREFIX}live:trend"  # historique court : un point par cycle (collector/trend.py)

# Canal de diffusion des nouvelles alertes. Le backend y est abonné et
# retransmet vers les navigateurs par WebSocket. Passer par Redis plutôt que
# par un appel HTTP du collecteur vers le backend permet de faire tourner
# plusieurs backends derrière un répartiteur : tous reçoivent la publication.
CHANNEL_ALERTS = f"{PREFIX}events:alerts"


def snapshot_ttl(collect_interval_s: int) -> int:
    """Durée de vie des clés d'instantané : trois cycles.

    Deux cycles seraient trop justes — un cycle qui déborde légèrement ferait
    clignoter le tableau de bord entre « données » et « collecte
    interrompue ». Trois laissent passer un cycle raté sans fausse alerte,
    tout en gardant le signal utile si le collecteur est réellement mort.
    """
    return max(60, collect_interval_s * 3)


class SnapshotStore:
    """Accès à l'instantané. Instancié côté collecteur (écriture) comme côté
    backend (lecture) — d'où la présence des deux familles de méthodes."""

    def __init__(self, redis: Redis, collect_interval_s: int = 300):
        self.redis = redis
        self.collect_interval_s = collect_interval_s
        self.ttl = snapshot_ttl(collect_interval_s)

    # -- écriture (collecteur) --------------------------------------------
    async def write_snapshot(
        self,
        nodes: list,
        alerts: list,
        meta: dict[str, Any],
    ) -> None:
        """Publie l'instantané complet, de façon atomique.

        Le pipeline garantit que le backend ne peut pas lire des équipements
        du cycle N et des alertes du cycle N+1 : sans lui, une alerte
        pourrait désigner un équipement que la liste ne contient pas encore,
        et l'écran afficherait une alerte orpheline.
        """
        payload_nodes = json.dumps(to_jsonable(nodes), ensure_ascii=False)
        payload_alerts = json.dumps(to_jsonable(alerts), ensure_ascii=False)
        payload_meta = json.dumps(to_jsonable(meta), ensure_ascii=False)

        pipe = self.redis.pipeline(transaction=True)
        pipe.set(KEY_NODES, payload_nodes, ex=self.ttl)
        pipe.set(KEY_ALERTS, payload_alerts, ex=self.ttl)
        pipe.set(KEY_META, payload_meta, ex=self.ttl)
        await pipe.execute()

    async def write_latest(self, latest: dict) -> None:
        """Dernières valeurs du cycle. Même durée de vie que l'instantané :
        des mesures périmées ne doivent pas survivre au parc qu'elles
        décrivent."""
        await self.redis.set(KEY_LATEST, json.dumps(latest, ensure_ascii=False), ex=self.ttl)

    async def write_operations(self, maintenance: list, work_orders: list) -> None:
        """Maintenances et ordres de travail du cycle, déjà rattachés au parc."""
        pipe = self.redis.pipeline()
        pipe.set(KEY_MAINTENANCE, json.dumps(maintenance, ensure_ascii=False), ex=self.ttl)
        pipe.set(KEY_WORK_ORDERS, json.dumps(work_orders, ensure_ascii=False), ex=self.ttl)
        await pipe.execute()

    async def append_trend(self, point: dict) -> None:
        """Ajoute un point à l'historique court et ne garde que 24 h."""
        keep = max(12, 86400 // max(1, self.collect_interval_s))
        pipe = self.redis.pipeline()
        pipe.rpush(KEY_TREND, json.dumps(point, ensure_ascii=False))
        pipe.ltrim(KEY_TREND, -keep, -1)
        pipe.expire(KEY_TREND, 2 * 86400)
        await pipe.execute()

    async def write_tool_health(self, health) -> None:
        await self.redis.set(
            f"{KEY_TOOL}{health.tool}",
            json.dumps(to_jsonable(health), ensure_ascii=False),
            ex=self.ttl,
        )

    async def write_source_data(
        self, tool: str, collection: str, records: list, collected_at: datetime
    ) -> None:
        """Keep the last complete source collection without expiring it."""
        payload = {
            "collected_at": collected_at,
            "records": records,
        }
        await self.redis.set(
            f"{KEY_SOURCE}{tool}:{collection}",
            json.dumps(to_jsonable(payload), ensure_ascii=False),
        )

    async def read_source_data(self, tool: str, collection: str) -> dict | None:
        """Read the last complete collection for one source data stream."""
        value = await self._read_json(f"{KEY_SOURCE}{tool}:{collection}")
        if value is None:
            return None
        collected_at = value.get("collected_at") if isinstance(value, dict) else None
        valid_timestamp = isinstance(collected_at, str) and bool(collected_at)
        if valid_timestamp:
            try:
                valid_timestamp = (
                    datetime.fromisoformat(
                        collected_at.replace("Z", "+00:00")
                    ).tzinfo
                    is not None
                )
            except ValueError:
                valid_timestamp = False
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("records"), list)
            or not all(isinstance(record, dict) for record in value["records"])
            or not valid_timestamp
        ):
            logger.error(
                "Instantané source invalide pour %s/%s", tool, collection
            )
            return None
        return value

    async def publish_new_alerts(self, alerts: list) -> None:
        """Diffuse les alertes apparues depuis le cycle précédent.

        Publier TOUTES les alertes actives à chaque cycle inonderait les
        navigateurs et ferait sonner les notifications toutes les cinq
        minutes pour une panne qui dure. Seule la nouveauté est un événement.
        """
        if not alerts:
            return
        await self.redis.publish(
            CHANNEL_ALERTS, json.dumps(to_jsonable(alerts), ensure_ascii=False)
        )

    async def diff_new_alerts(self, alerts: list) -> list:
        """Alertes absentes du cycle précédent.

        L'ensemble des clés vues est stocké dans Redis, SANS EXPIRATION, et
        non en mémoire du processus :

          * un collecteur redémarré ne rediffuse pas tout le parc comme s'il
            venait de tomber en panne ;
          * après une coupure, même longue, les pannes apparues pendant la
            coupure SONT diffusées et notifiées au retour. Autrefois
            l'ensemble expirait au bout de trois cycles, et ces pannes-là
            n'étaient jamais notifiées.

        Seul un VRAI premier démarrage (aucun marqueur, Redis neuf ou vidé)
        ne diffuse rien : tout y serait « nouveau » sans que rien ne vienne de
        se produire, et l'astreinte serait réveillée pour tout le parc. Un
        ensemble vide, lui, veut seulement dire « aucune alerte au cycle
        précédent » : une alerte qui apparaît ensuite est bien nouvelle.
        """
        current = {alert.key() for alert in alerts}
        previous = set(await self.redis.smembers(KEY_ALERT_SEEN) or [])
        # Un ensemble non vide écrit par une version précédente vaut marqueur.
        initialised = bool(previous) or bool(await self.redis.exists(KEY_ALERT_SEEN_SINCE))

        pipe = self.redis.pipeline(transaction=True)
        pipe.delete(KEY_ALERT_SEEN)
        if current:
            pipe.sadd(KEY_ALERT_SEEN, *current)
        pipe.set(KEY_ALERT_SEEN_SINCE, datetime.now(timezone.utc).isoformat(), nx=True)
        await pipe.execute()

        if not initialised:
            return []
        new_keys = current - previous
        return [alert for alert in alerts if alert.key() in new_keys]

    async def save_rollup(self, payload: list) -> None:
        """Compteurs du bilan journalier en cours, sans expiration."""
        await self.redis.set(KEY_ROLLUP, json.dumps(payload, ensure_ascii=False))

    async def load_rollup(self) -> list:
        value = await self._read_json(KEY_ROLLUP)
        return value if isinstance(value, list) else []

    # -- lecture (backend) -------------------------------------------------
    async def read_nodes(self) -> list[dict] | None:
        return await self._read_json(KEY_NODES)

    async def read_alerts(self) -> list[dict] | None:
        return await self._read_json(KEY_ALERTS)

    async def read_meta(self) -> dict | None:
        return await self._read_json(KEY_META)

    async def read_tool_health(self, tool: str) -> dict | None:
        return await self._read_json(f"{KEY_TOOL}{tool}")

    async def _read_json(self, key: str):
        """Lecture tolérante.

        Une clé absente rend None — que l'appelant DOIT distinguer d'une liste
        vide : None veut dire « la collecte ne tourne plus », [] veut dire
        « la collecte tourne et ne trouve rien ». Les deux s'affichent
        différemment, et les confondre serait le pire des bogues de ce
        tableau de bord.
        """
        raw = await self.redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.error("Instantané illisible sous %s — clé ignorée", key)
            return None

    # -- cache d'historique (backend) -------------------------------------
    async def get_history(self, fingerprint: str):
        return await self._read_json(f"{KEY_HISTORY}{fingerprint}")

    async def set_history(self, fingerprint: str, points: list, ttl_s: int) -> None:
        await self.redis.set(
            f"{KEY_HISTORY}{fingerprint}",
            json.dumps(to_jsonable(points), ensure_ascii=False),
            ex=ttl_s,
        )


def build_meta(
    started_at: datetime,
    duration_s: float,
    nodes: int,
    alerts: int,
    tools_ok: list[str],
    tools_failed: list[str],
) -> dict[str, Any]:
    """Métadonnées du cycle, affichées sur l'écran Interopérabilité.

    `tools_failed` est publié même vide : la page doit pouvoir dire « tous les
    outils ont répondu » plutôt que de laisser l'exploitant déduire d'une
    absence.
    """
    return {
        "collected_at": started_at.astimezone(timezone.utc).isoformat(),
        "duration_s": round(duration_s, 3),
        "nodes": nodes,
        "alerts": alerts,
        "tools_ok": sorted(tools_ok),
        "tools_failed": sorted(tools_failed),
    }
