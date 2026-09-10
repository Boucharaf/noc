"""
Connecteur Centreon 22.10 — API REST v2 sous /centreon/api/latest.

Documentation : https://docs.centreon.com/22.10/en/api/rest-api-v2.html

AUTHENTIFICATION. `POST /login` rend un jeton à replacer dans l'en-tête
`X-AUTH-TOKEN`. Ce jeton expire (une heure par défaut en 22.10, et non 24 h
comme le supposait l'ancien connecteur — d'où des collectes qui échouaient en
milieu de journée). On ne parie donc pas sur une durée : le jeton est
renouvelé dès qu'un appel répond 401, ce qui est robuste quelle que soit la
configuration de l'instance.

INVENTAIRE ET ALERTES. `/monitoring/resources` et non `/monitoring/hosts` +
`/monitoring/services` : c'est l'endpoint unifié introduit en 21.x, celui que
la page « Ressources » de Centreon utilise elle-même. Un seul appel rend les
hôtes ET les services avec leur état, leur acquittement et leur fenêtre de
maintenance — là où l'ancien connecteur en faisait deux, puis un par service
pour les métriques, soit plusieurs centaines d'appels par cycle sur un parc
moyen.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .base import SourceClient, ToolUnavailable
from .models import Alert, MetricPoint, Node, ToolHealth
from .normalize import iso_to_dt, severity

logger = logging.getLogger(__name__)

# Correspondance nom de métrique Centreon -> type du NOC. Les noms viennent
# des perfdata des sondes standard (check_icmp, check_traffic, check_centreon_cpu).
_METRIC_NAMES = {
    "rta": "latency_ms",
    "rtmax": "latency_ms",
    "pl": "packet_loss_pct",
    "packet_loss": "packet_loss_pct",
    "traffic_in": "bandwidth_in_mbps",
    "traffic_out": "bandwidth_out_mbps",
    "cpu": "cpu_pct",
    "cpu_used": "cpu_pct",
    "memory_used": "ram_pct",
    "used": "ram_pct",
}

# Statuts considérés comme des problèmes. DOWN et UNREACHABLE concernent les
# hôtes, WARNING/CRITICAL/UNKNOWN les services ; l'API accepte la liste
# complète pour une requête portant sur les deux types.
_PROBLEM_STATUSES = ["DOWN", "UNREACHABLE", "WARNING", "CRITICAL", "UNKNOWN"]

# Centreon rend le trafic en bits par seconde et les temps en millisecondes.
_SCALE = {
    "bandwidth_in_mbps": 1 / 1e6,
    "bandwidth_out_mbps": 1 / 1e6,
}


class CentreonClient(SourceClient):
    name = "centreon"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 20.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        # L'URL peut être donnée avec ou sans le préfixe applicatif. En local
        # c'est « http://centreon/centreon », en production souvent
        # « https://centreon.example.bf/centreon ».
        root = self.base_url
        if not root.endswith("/centreon"):
            root = f"{root}/centreon"
        self.api = f"{root}/api/latest"
        self._token: str | None = None

    # -- plomberie ---------------------------------------------------------
    async def _login(self) -> str:
        response = await self._request(
            "POST",
            f"{self.api}/login",
            json={
                "security": {
                    "credentials": {"login": self.user, "password": self.password}
                }
            },
        )
        try:
            token = response.json()["security"]["token"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolUnavailable(
                self.name, "réponse de login inattendue (jeton absent)"
            ) from exc
        self._token = token
        return token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET authentifié, avec UNE re-authentification en cas de 401.

        La ré-authentification est bornée à un essai : si le second appel
        échoue encore, ce sont les identifiants qui sont mauvais, et boucler
        ne ferait que verrouiller le compte côté Centreon.
        """
        if self._token is None:
            await self._login()
        try:
            response = await self._request(
                "GET",
                f"{self.api}{path}",
                params=params,
                headers={"X-AUTH-TOKEN": self._token},
            )
        except ToolUnavailable as exc:
            if "HTTP 401" not in str(exc) and "HTTP 403" not in str(exc):
                raise
            logger.info("Centreon : jeton expiré, ré-authentification")
            await self._login()
            response = await self._request(
                "GET",
                f"{self.api}{path}",
                params=params,
                headers={"X-AUTH-TOKEN": self._token},
            )
        return response.json()

    # -- contrat -----------------------------------------------------------
    async def check(self) -> ToolHealth:
        async def probe():
            # /platform/versions ne demande pas de jeton : il sépare
            # « Centreon injoignable » de « identifiants refusés ».
            response = await self._request("GET", f"{self.api}/platform/versions")
            body = response.json()
            return (body.get("web") or {}).get("version")

        health = await self._health(probe)
        if not health.reachable:
            return health
        try:
            await self._login()
        except Exception as exc:  # noqa: BLE001
            return ToolHealth(
                tool=self.name,
                reachable=False,
                version=health.version,
                error=f"authentification refusée : {exc}",
            )
        return health

    async def _resources(self, resource_types: list[str], extra: dict | None = None) -> list[dict]:
        """Pagination complète de /monitoring/resources.

        Centreon plafonne `limit` et rend le total dans `meta` : on boucle
        jusqu'à l'avoir atteint. Ne pas paginer donnerait un parc
        silencieusement tronqué aux 100 premiers équipements — le genre
        d'erreur qu'on ne voit qu'en production.
        """
        collected: list[dict] = []
        page = 1
        limit = 100
        while True:
            params = {
                "types": json.dumps(resource_types),
                "page": page,
                "limit": limit,
            }
            if extra:
                params.update(extra)
            body = await self._get("/monitoring/resources", params)
            rows = body.get("result") or []
            collected.extend(rows)
            meta = body.get("meta") or {}
            total = meta.get("total", len(collected))
            if len(collected) >= total or not rows:
                return collected
            page += 1
            if page > 200:  # garde-fou : 20 000 ressources
                logger.warning("Centreon : pagination interrompue à 200 pages")
                return collected

    async def fetch_nodes(self) -> list[Node]:
        rows = await self._resources(["host"])
        nodes: list[Node] = []
        for row in rows:
            status = (row.get("status") or {}).get("code")
            in_maintenance = bool(row.get("in_downtime"))
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(row.get("id")),
                    name=row.get("name") or "(sans nom)",
                    hostname=row.get("name") or "",
                    ip=row.get("fqdn") or (row.get("information") or None),
                    state=_host_state(status, in_maintenance),
                    enabled=not row.get("is_notification_enabled") is False,
                    groups=tuple(
                        g.get("name", "") for g in (row.get("groups") or []) if g.get("name")
                    ),
                    site=_site_from_groups(row.get("groups") or []),
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        # Filtrage par STATUT et non par « état ».
        #
        # Le paramètre `states` de Centreon 22.10 n'accepte que
        # `unhandled_problems`, `acknowledged`, `in_downtime` et `all` — la
        # valeur `problems`, qu'on croirait naturelle, fait répondre l'API en
        # HTTP 500 (constaté sur l'instance locale 22.10). Or
        # `unhandled_problems` masquerait les alertes acquittées, que le mur
        # d'alertes du NOC affiche différemment mais ne cache pas.
        #
        # `statuses` donne exactement ce qu'il faut : tout ce qui n'est pas
        # nominal, acquitté ou non.
        rows = await self._resources(
            ["host", "service"],
            {"statuses": json.dumps(_PROBLEM_STATUSES)},
        )
        alerts: list[Alert] = []
        for row in rows:
            status = row.get("status") or {}
            code = status.get("code")
            resource_type = row.get("type")
            scale = "centreon_host" if resource_type == "host" else "centreon_service"
            parent = row.get("parent") or {}
            acknowledged = bool(row.get("acknowledged"))
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=f"{resource_type}-{row.get('id')}",
                    severity=severity(scale, code),
                    message=row.get("information") or status.get("name") or "(sans détail)",
                    since=(
                        iso_to_dt(row.get("last_status_change"))
                        or datetime.now(timezone.utc)
                    ),
                    # Pour un service, l'équipement est l'hôte parent ; pour un
                    # hôte, c'est lui-même.
                    node_ref=str(parent.get("id") or row.get("id")),
                    node_name=parent.get("name") or row.get("name"),
                    acknowledged=acknowledged,
                    acknowledged_at=iso_to_dt(
                        (row.get("acknowledgement") or {}).get("entry_time")
                    ),
                )
            )
        return alerts

    async def fetch_history(
        self, node_ref: str, metric_type: str, start: datetime, end: datetime
    ) -> list[MetricPoint]:
        """Séries de performance, lues dans les RRD de Centreon.

        Chemin : on liste les services de l'hôte, puis on demande les données
        de performance de chacun sur la fenêtre, et on ne garde que les
        métriques dont le nom correspond au type demandé.
        """
        services = await self._resources(
            ["service"], {"search": json.dumps({"parent.id": {"$eq": int(node_ref)}})}
        ) if str(node_ref).isdigit() else []

        window = {
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
        }
        scale = _SCALE.get(metric_type, 1.0)
        points: list[MetricPoint] = []

        for service in services:
            service_id = service.get("id")
            parent_id = (service.get("parent") or {}).get("id", node_ref)
            try:
                body = await self._get(
                    f"/monitoring/hosts/{parent_id}/services/{service_id}/metrics",
                    window,
                )
            except ToolUnavailable:
                # Un service sans RRD (checks passifs récents) n'est pas une
                # panne : on passe au suivant.
                continue
            for metric in body.get("metrics") or []:
                if _METRIC_NAMES.get(str(metric.get("metric", "")).lower()) != metric_type:
                    continue
                times = body.get("times") or []
                for at_raw, value in zip(times, metric.get("data") or []):
                    at = iso_to_dt(at_raw)
                    if at is None or value is None:
                        continue
                    points.append(MetricPoint(at=at, value=float(value) * scale))

        points.sort(key=lambda p: p.at)
        return points


def _host_state(status_code, in_maintenance: bool) -> str:
    """État d'un hôte Centreon : 0 UP, 1 DOWN, 2 UNREACHABLE, 4 PENDING."""
    if in_maintenance:
        return "maintenance"
    return {
        0: "up",
        1: "down",
        2: "degraded",   # UNREACHABLE : la panne est en amont, pas sur l'hôte
        4: "silent",     # PENDING : jamais contrôlé depuis le dernier export
    }.get(status_code, "unknown")


def _site_from_groups(groups: list[dict]) -> str | None:
    """Même convention que pour Zabbix : un groupe « Site/<nom> » porte la
    localisation. Voir integrations/zabbix.py::_site_from_groups."""
    for group in groups:
        name = str(group.get("name", ""))
        for prefix in ("site/", "localité/", "localite/", "site:"):
            if name.lower().startswith(prefix):
                return name.split("/", 1)[-1].split(":", 1)[-1].strip() or None
    return None
