"""
Écriture et lecture de l'instantané Redis.

CE MODULE EST LE CONTRAT entre le collecteur et le backend. Il est le seul
endroit du dépôt qui connaisse les noms de clés Redis ; tout le reste passe
par ses fonctions. Le contrat lui-même est documenté dans ARCHITECTURE.md,
section « Contrat de l'instantané Redis ».

DEUX RÈGLES QUI EXPLIQUENT TOUT LE FICHIER :

1. **L'instantané est réécrit en entier, jamais mis à jour par morceaux.**
   Un équipement disparu de l'outil source doit disparaître du NOC au cycle
   suivant. Une mise à jour incrémentale le laisserait à l'écran
   indéfiniment, avec son dernier état connu — un fantôme que personne ne
   sait faire partir.

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
KEY_HISTORY = f"{PREFIX}hist:"       # + outil:empreinte
KEY_ALERT_SEEN = f"{PREFIX}live:alerts:seen"

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

    async def write_tool_health(self, health) -> None:
        await self.redis.set(
            f"{KEY_TOOL}{health.tool}",
            json.dumps(to_jsonable(health), ensure_ascii=False),
            ex=self.ttl,
        )

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

        L'ensemble des clés vues est stocké dans Redis et non en mémoire du
        processus : un collecteur redémarré ne doit pas rediffuser tout le
        parc comme s'il venait de tomber en panne.
        """
        current = {alert.key() for alert in alerts}
        previous = set(await self.redis.smembers(KEY_ALERT_SEEN) or [])

        new_keys = current - previous
        if current:
            pipe = self.redis.pipeline(transaction=True)
            pipe.delete(KEY_ALERT_SEEN)
            pipe.sadd(KEY_ALERT_SEEN, *current)
            pipe.expire(KEY_ALERT_SEEN, self.ttl)
            await pipe.execute()
        else:
            await self.redis.delete(KEY_ALERT_SEEN)

        # Un ensemble « vu » vide signifie soit un premier démarrage, soit une
        # expiration après une longue panne. Dans les deux cas, tout est
        # techniquement « nouveau », mais rien ne vient de se produire : on ne
        # diffuse rien, sinon le premier démarrage réveillerait l'astreinte.
        if not previous:
            return []
        return [alert for alert in alerts if alert.key() in new_keys]

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
