"""
Connecteur Zabbix 7.0 — JSON-RPC sur /api_jsonrpc.php.

Documentation : https://www.zabbix.com/documentation/7.0/en/manual/api

AUTHENTIFICATION. Depuis Zabbix 6.4, le jeton se présente dans l'en-tête
`Authorization: Bearer`, et le champ `auth` du corps JSON-RPC est déprécié.
La 7.0 accepte encore les deux — vérifié sur l'instance locale 7.0.23 — mais
il disparaîtra ; ce connecteur utilise l'en-tête. Un jeton d'API permanent
(ZABBIX_API_TOKEN) est préféré au couple identifiant/mot de passe quand il
est fourni : il n'expire pas, ne consomme pas de session, et se révoque sans
toucher au compte.

ALERTES. `problem.get` et non `event.get` : la table des problèmes ne
contient que ce qui est ACTIF, ce qui est exactement le périmètre de
l'instantané. `event.get` remonterait tout l'historique — précisément ce que
cette architecture refuse de recopier.

HISTORIQUE. Deux méthodes selon l'ancienneté demandée :
  history.get  — valeurs brutes, conservées `HistoryStorage` jours (31 par
                 défaut) ;
  trend.get    — moyennes horaires, conservées un an par défaut.
Demander de l'history.get sur trois mois renverrait vide sans erreur, ce qui
donnerait une courbe plate impossible à diagnostiquer. Le seuil de bascule
est donc explicite (`_TREND_THRESHOLD`).
"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime, timedelta, timezone

from .base import SourceClient, ToolUnavailable
from .models import Alert, MetricPoint, Node
from .normalize import epoch_to_dt, severity

logger = logging.getLogger(__name__)

# Au-delà de cette ancienneté, les valeurs brutes ont été purgées par le
# housekeeper de Zabbix : on bascule sur les tendances horaires.
_TREND_THRESHOLD = timedelta(days=7)

# Correspondance clé d'item Zabbix -> type de métrique du NOC. La clé est
# comparée sur sa RACINE (avant le premier crochet) : `net.if.in[eth0]` et
# `net.if.in[eth1]` sont tous deux du trafic entrant.
_ITEM_KEYS = {
    "icmppingloss": "packet_loss_pct",
    "icmppingsec": "latency_ms",
    "net.if.in": "bandwidth_in_mbps",
    "net.if.out": "bandwidth_out_mbps",
    "system.cpu.util": "cpu_pct",
    "vm.memory.util": "ram_pct",
    "vm.memory.utilization": "ram_pct",
    "agent.ping": "availability_pct",
}

# Conversions d'unité vers celles du NOC. Zabbix rend icmppingsec en
# SECONDES et net.if.* en octets par seconde ; les afficher tels quels
# donnerait des latences à 0,004 et des débits à neuf chiffres.
_SCALE = {
    "latency_ms": 1000.0,          # s    -> ms
    "bandwidth_in_mbps": 8 / 1e6,  # o/s  -> Mbit/s
    "bandwidth_out_mbps": 8 / 1e6,
    "availability_pct": 100.0,     # 0|1  -> %
}


class ZabbixClient(SourceClient):
    name = "zabbix"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 token: str = "", verify_ssl: bool = True, timeout_s: float = 20.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        # L'URL peut être donnée avec ou sans le script final : l'agence
        # renseigne souvent « https://zabbix.example/api_jsonrpc.php », le
        # compose local « http://zabbix-web:8080 ». Les deux doivent marcher.
        self.endpoint = (
            self.base_url
            if self.base_url.endswith(".php")
            else f"{self.base_url}/api_jsonrpc.php"
        )
        self._static_token = token.strip()
        self._session_token: str | None = None
        self._ids = itertools.count(1)

    # -- plomberie JSON-RPC ------------------------------------------------
    async def _call(self, method: str, params: dict, authenticated: bool = True) -> object:
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._token()}"

        response = await self._request(
            "POST",
            self.endpoint,
            json={
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": next(self._ids),
            },
            headers=headers,
        )
        body = response.json()
        if "error" in body:
            error = body["error"]
            # Un jeton de session périmé se manifeste par un message générique
            # de ré-authentification. On l'oublie pour que l'appel suivant en
            # redemande un, au lieu de boucler en erreur jusqu'au redémarrage.
            if "re-login" in str(error).lower() or "not authorized" in str(error).lower():
                self._session_token = None
            raise ToolUnavailable(
                self.name, f"{error.get('message')} {error.get('data', '')}".strip()
            )
        return body["result"]

    async def _token(self) -> str:
        if self._static_token:
            return self._static_token
        if self._session_token is None:
            if not self.user:
                raise ToolUnavailable(
                    self.name,
                    "ni ZABBIX_API_TOKEN ni ZABBIX_API_USER renseignés",
                )
            self._session_token = await self._call(
                "user.login",
                {"username": self.user, "password": self.password},
                authenticated=False,
            )
        return self._session_token

    # -- contrat -----------------------------------------------------------
    async def check(self):
        # apiinfo.version est la seule méthode qui n'exige pas
        # d'authentification : elle distingue « Zabbix injoignable » de
        # « identifiants refusés », deux pannes aux remèdes différents.
        async def probe():
            return await self._call("apiinfo.version", {}, authenticated=False)

        health = await self._health(probe)
        if health.reachable and not self._static_token:
            # Joignable ne suffit pas : il faut aussi que le compte marche,
            # sinon l'écran Interopérabilité afficherait « vert » sur une
            # intégration qui ne remontera jamais la moindre donnée.
            try:
                await self._token()
            except Exception as exc:  # noqa: BLE001
                from .models import ToolHealth

                return ToolHealth(
                    tool=self.name,
                    reachable=False,
                    version=health.version,
                    error=f"authentification refusée : {exc}",
                )
        return health

    async def fetch_nodes(self) -> list[Node]:
        hosts = await self._call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status", "maintenance_status"],
                "selectInterfaces": ["ip", "available"],
                "selectHostGroups": ["name"],
            },
        )
        nodes: list[Node] = []
        for host in hosts:
            interfaces = host.get("interfaces") or []
            groups = tuple(g["name"] for g in host.get("hostgroups") or [])
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(host["hostid"]),
                    name=host.get("name") or host["host"],
                    hostname=host["host"],
                    ip=interfaces[0].get("ip") if interfaces else None,
                    state=_host_state(host, interfaces),
                    # status : 0 = supervisé, 1 = non supervisé.
                    enabled=str(host.get("status")) == "0",
                    groups=groups,
                    site=_site_from_groups(groups),
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        problems = await self._call(
            "problem.get",
            {
                "output": "extend",
                "selectAcknowledges": ["clock", "action"],
                "recent": False,        # uniquement ce qui est encore en cours
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": 5000,
            },
        )
        # problem.get ne renvoie pas l'hôte : il faut le résoudre par les
        # déclencheurs. Un seul appel groupé plutôt qu'un par alerte — sur un
        # parc en crise, la différence est entre une requête et plusieurs
        # centaines.
        trigger_ids = sorted({p["objectid"] for p in problems if p.get("objectid")})
        hosts_by_trigger = await self._hosts_by_trigger(trigger_ids)

        alerts: list[Alert] = []
        for problem in problems:
            host = hosts_by_trigger.get(str(problem.get("objectid")), {})
            acknowledges = problem.get("acknowledges") or []
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(problem["eventid"]),
                    severity=severity("zabbix", problem.get("severity")),
                    message=problem.get("name") or "(sans libellé)",
                    since=epoch_to_dt(problem.get("clock")) or datetime.now(timezone.utc),
                    node_ref=host.get("hostid"),
                    node_name=host.get("name"),
                    acknowledged=str(problem.get("acknowledged")) == "1",
                    acknowledged_at=(
                        epoch_to_dt(acknowledges[0].get("clock")) if acknowledges else None
                    ),
                )
            )
        return alerts

    async def _hosts_by_trigger(self, trigger_ids: list[str]) -> dict[str, dict]:
        if not trigger_ids:
            return {}
        triggers = await self._call(
            "trigger.get",
            {
                "output": ["triggerid"],
                "triggerids": trigger_ids,
                "selectHosts": ["hostid", "name"],
            },
        )
        mapping: dict[str, dict] = {}
        for trigger in triggers:
            hosts = trigger.get("hosts") or []
            if hosts:
                mapping[str(trigger["triggerid"])] = {
                    "hostid": str(hosts[0]["hostid"]),
                    "name": hosts[0].get("name"),
                }
        return mapping

    async def fetch_history(
        self, node_ref: str, metric_type: str, start: datetime, end: datetime
    ) -> list[MetricPoint]:
        items = await self._items_for(node_ref, metric_type)
        if not items:
            return []

        item_ids = [item["itemid"] for item in items]
        use_trends = (datetime.now(timezone.utc) - start) > _TREND_THRESHOLD
        params = {
            "output": "extend",
            "itemids": item_ids,
            "time_from": int(start.timestamp()),
            "time_till": int(end.timestamp()),
            "sortfield": "clock",
            "sortorder": "ASC",
            "limit": 5000,
        }

        if use_trends:
            rows = await self._call("trend.get", params)
            raw = [(row["clock"], row["value_avg"]) for row in rows]
        else:
            # history.get EXIGE le type de valeur : les valeurs flottantes et
            # entières vivent dans deux tables distinctes. Tous les items
            # d'un même type de métrique partagent le leur, d'où le premier.
            params["history"] = int(items[0].get("value_type", 0))
            rows = await self._call("history.get", params)
            raw = [(row["clock"], row["value"]) for row in rows]

        scale = _SCALE.get(metric_type, 1.0)
        points: list[MetricPoint] = []
        for clock, value in raw:
            at = epoch_to_dt(clock)
            if at is None:
                continue
            try:
                points.append(MetricPoint(at=at, value=float(value) * scale))
            except (TypeError, ValueError):
                continue
        return points

    async def _items_for(self, node_ref: str, metric_type: str) -> list[dict]:
        """Items de l'hôte correspondant au type de métrique demandé.

        Le filtrage se fait ici et non côté Zabbix : l'API ne sait pas filtrer
        `item.get` sur une racine de clé, seulement sur une clé exacte, et les
        clés portent des paramètres variables (`net.if.in[eth0]`).
        """
        items = await self._call(
            "item.get",
            {
                "output": ["itemid", "key_", "value_type"],
                "hostids": [str(node_ref)],
                "monitored": True,
            },
        )
        matching = []
        for item in items:
            root = str(item.get("key_", "")).split("[", 1)[0]
            if _ITEM_KEYS.get(root) == metric_type:
                matching.append(item)
        return matching


def _host_state(host: dict, interfaces: list[dict]) -> str:
    """État d'un hôte Zabbix, traduit vers le vocabulaire du NOC.

    Zabbix ne publie pas d'état « up/down » d'hôte : il publie la
    DISPONIBILITÉ DE SON INTERFACE (`available` : 0 inconnu, 1 disponible,
    2 indisponible). C'est l'information la plus proche, et la seule qui ne
    demande pas d'interroger les déclencheurs.
    """
    if str(host.get("maintenance_status")) == "1":
        return "maintenance"
    if str(host.get("status")) == "1":
        return "unknown"  # hôte désactivé : Zabbix ne le sonde plus
    availabilities = {str(i.get("available")) for i in interfaces}
    if "2" in availabilities:
        return "down"
    if "1" in availabilities:
        return "up"
    # `0` partout : l'hôte est supervisé mais aucune interface n'a encore
    # répondu. Ce n'est pas « up », et le dire serait mentir.
    return "silent"


def _site_from_groups(groups: tuple[str, ...]) -> str | None:
    """Site déduit des groupes d'hôtes.

    Convention retenue avec l'agence : un groupe nommé « Site/<nom> » ou
    « Localité/<nom> » porte la localisation. Sans groupe conforme, on rend
    None — un site inventé serait pire qu'un site absent, parce qu'il
    remonterait dans les statistiques par localité.
    """
    for group in groups:
        for prefix in ("site/", "localité/", "localite/", "site:"):
            if group.lower().startswith(prefix):
                return group.split("/", 1)[-1].split(":", 1)[-1].strip() or None
    return None
