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
import math
import time
from datetime import datetime, timedelta, timezone

from .base import SourceClient, ToolUnavailable
from .models import Alert, MetricPoint, NetworkInterface, Node
from .normalize import (
    combine_latest,
    combine_series,
    epoch_to_dt,
    locality_from_groups,
    severity,
    source_severity,
)

logger = logging.getLogger(__name__)

# Au-delà de cette ancienneté, les valeurs brutes ont été purgées par le
# housekeeper de Zabbix : on bascule sur les tendances horaires.
_TREND_THRESHOLD = timedelta(days=7)
_PAGE_SIZE = 1000
_PROBLEM_PAGE_SIZE = 1000

# Correspondance clé d'item Zabbix -> type de métrique du NOC. La clé est
# comparée sur sa RACINE (avant le premier crochet) : `net.if.in[eth0]` et
# `net.if.in[eth1]` sont tous deux du trafic entrant.
_ITEM_KEYS = {
    "icmpping": "availability_pct",
    "icmppingloss": "packet_loss_pct",
    "icmppingsec": "latency_ms",
    "net.if.in": "bandwidth_in_mbps",
    "net.if.out": "bandwidth_out_mbps",
    "system.cpu.util": "cpu_pct",
    "vm.memory.util": "ram_pct",
    "vm.memory.utilization": "ram_pct",
    "agent.ping": "availability_pct",
    "system.hw.sensors": "temp_cpu",
    "system.cpu.load": "cpu_load",
    "proc.num": "proc_count",
    "system.uptime": "uptime",
    "net.if.errors": "if_errors",
    "net.if.collisions": "if_errors",
}

# Préfixes de clé relevés pour les moyennes du parc (fetch_fleet_latest).
_FLEET_KEY_PREFIXES = (
    "icmpping", "agent.ping", "net.if.in[", "net.if.out[", "system.cpu.util",
    "vm.memory.util", "vm.memory.size[", "vfs.fs.size[", "vfs.fs.dependent.size[",
    "system.uptime",
)

# Conversions d'unité vers celles du NOC. Zabbix rend icmppingsec en
# SECONDES et net.if.* en octets par seconde ; les afficher tels quels
# donnerait des latences à 0,004 et des débits à neuf chiffres.
#
# Débits : l'item BRUT `net.if.in[eth0]` rend des octets/s, mais les
# gabarits livrés (Linux by Zabbix agent, tous les « … by SNMP ») ajoutent un
# multiplicateur ×8 et l'unité « bps » : la valeur est déjà en bits/s. Le
# facteur dépend donc de l'unité de l'item (voir `_to_noc_unit`) ; celui-ci
# ne vaut que pour un item sans unité déclarée.
_SCALE = {
    "latency_ms": 1000.0,          # s    -> ms
    "bandwidth_in_mbps": 8 / 1e6,  # o/s  -> Mbit/s
    "bandwidth_out_mbps": 8 / 1e6,
    "availability_pct": 100.0,     # 0|1  -> % (agent.ping, icmpping)
    "uptime": 1.0 / 86400.0,       # s    -> jours
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
        self.collection_warnings: list[str] = []
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
                "selectInterfaces": ["ip", "dns", "useip", "available", "main"],
                "selectHostGroups": ["name"],
                # Position déclarée dans l'inventaire de l'hôte (champs
                # standard « Location latitude / longitude »), quand l'agence
                # la renseigne : elle place l'équipement sur la carte. Le
                # reste de l'inventaire (constructeur, modèle, n° de série)
                # va sur la fiche d'équipement ; aucun champ de contact n'est
                # demandé, ce sont des données personnelles.
                "selectInventory": ["location_lat", "location_lon", *_INVENTORY_FIELDS],
            },
        )
        if not hosts:
            # Un compte sans droit de lecture sur les groupes d'hôtes reçoit une
            # liste VIDE, pas une erreur : seul un « Super admin » voit tout.
            # Publier « 0 équipement » sans le dire ferait passer une
            # intégration aveugle pour un parc vide.
            self.collection_warnings.append(
                "aucun hôte visible : le compte n'a probablement aucun droit de "
                "lecture sur les groupes d'hôtes (Utilisateurs > Groupes d'utilisateurs "
                "> Permissions dans Zabbix)"
            )
        icmp_candidates = [
            host
            for host in hosts
            if str(host.get("status")) == "0"
            and all(
                str(interface.get("available")) == "0"
                for interface in host.get("interfaces") or []
            )
        ]
        if icmp_candidates:
            host_ids = [str(host["hostid"]) for host in icmp_candidates]
            icmp_items = await self._call(
                "item.get",
                {
                    "output": ["hostid", "key_", "lastvalue", "status"],
                    "hostids": host_ids,
                    "monitored": True,
                    "search": {"key_": "icmpping"},
                },
            )
            items_by_host: dict[str, list[dict]] = {}
            for item in icmp_items:
                items_by_host.setdefault(str(item.get("hostid")), []).append(item)
            for host in icmp_candidates:
                host["items"] = items_by_host.get(str(host["hostid"]), [])

        nodes: list[Node] = []
        for host in hosts:
            interfaces = [
                NetworkInterface.from_record(item)
                for item in host.get("interfaces") or []
            ]
            primary = next(
                (interface for interface in interfaces if interface.main),
                interfaces[0] if interfaces else NetworkInterface(),
            )
            groups = tuple(g["name"] for g in host.get("hostgroups") or [])
            locality = locality_from_groups(groups)
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(host["hostid"]),
                    name=host.get("name") or host["host"],
                    hostname=host["host"],
                    ip=primary.ip or None,
                    state=_host_state(host, interfaces),
                    # status : 0 = supervisé, 1 = non supervisé.
                    enabled=str(host.get("status")) == "0",
                    groups=groups,
                    site=_site_from_groups(groups),
                    province=locality["province"],
                    region=locality["region"],
                    **_coordinates(host.get("inventory")),
                    details=_inventory_details(host.get("inventory")),
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        problems = []
        cursor = None
        while True:
            params = {
                "output": "extend",
                "selectAcknowledges": "extend",
                "selectTags": "extend",
                "recent": False,        # uniquement ce qui est encore en cours
                "sortfield": ["eventid"],
                "sortorder": "ASC",
                "limit": _PROBLEM_PAGE_SIZE,
            }
            if cursor is not None:
                params["eventid_from"] = str(cursor)
            page = await self._call("problem.get", params)
            problems.extend(page)
            if len(page) < _PROBLEM_PAGE_SIZE:
                break
            last_event_id = page[-1].get("eventid")
            try:
                next_cursor = int(last_event_id) + 1
            except (TypeError, ValueError) as exc:
                raise ToolUnavailable(
                    self.name, "problem.get a renvoyé un eventid invalide"
                ) from exc
            if cursor is not None and next_cursor <= cursor:
                raise ToolUnavailable(
                    self.name,
                    "problem.get ne progresse pas avec eventid_from; "
                    "résultat incomplet",
                )
            cursor = next_cursor
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
            since = epoch_to_dt(problem.get("clock"))
            if since is None:
                raise ToolUnavailable(
                    self.name,
                    f"problème {problem.get('eventid')} sans horodatage valide",
                )
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(problem["eventid"]),
                    severity=severity("zabbix", problem.get("severity")),
                    source_severity=source_severity("zabbix", problem.get("severity")),
                    message=problem.get("name") or "(sans libellé)",
                    since=since,
                    node_ref=host.get("hostid"),
                    node_name=host.get("name"),
                    acknowledged=str(problem.get("acknowledged")) == "1",
                    acknowledged_at=_acknowledged_at(acknowledges),
                    details=_problem_details(problem, acknowledges),
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

        use_trends = (datetime.now(timezone.utc) - start) > _TREND_THRESHOLD
        method = "trend.get" if use_trends else "history.get"
        start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
        series: list[list[tuple[datetime, float]]] = []

        for item in items:
            params = {
                "output": "extend",
                "itemids": [str(item["itemid"])],
                "time_from": start_ts,
                "time_till": end_ts,
                "sortfield": "clock",
                "sortorder": "ASC",
            }
            if not use_trends:
                # history.get exige le type de valeur; chaque item peut avoir
                # un type différent même s'il remonte la même métrique.
                params["history"] = int(item.get("value_type", 0))
            rows = await self._fetch_history_window(method, params, start_ts, end_ts)
            points: list[tuple[datetime, float]] = []
            for row in rows:
                at = epoch_to_dt(row.get("clock"))
                if at is None:
                    raise ToolUnavailable(
                        self.name,
                        f"point historique sans horodatage valide (item {item['itemid']})",
                    )
                raw_value = row.get("value_avg") if use_trends else row.get("value")
                try:
                    number = _to_noc_unit(item, metric_type, float(raw_value))
                except (TypeError, ValueError) as exc:
                    raise ToolUnavailable(
                        self.name,
                        f"valeur historique invalide (item {item['itemid']})",
                    ) from exc
                if math.isfinite(number) and not _no_reply(metric_type, number):
                    points.append((at, number))
            series.append(points)

        # Un équipement peut avoir plusieurs items pour une même métrique
        # (une par interface, une par système de fichiers). Les séries sont
        # combinées par intervalle — une minute en valeurs brutes, une heure
        # en tendances — selon la nature de la métrique (somme du trafic,
        # maximum du remplissage disque, moyenne sinon).
        return combine_series(series, metric_type, 3600 if use_trends else 60)

    async def fetch_latest(self, node_ref: str) -> dict[str, MetricPoint]:
        items = await self._items_for(node_ref, None)
        grouped: dict[str, tuple[datetime, list[float]]] = {}
        for item in items:
            at = epoch_to_dt(item.get("lastclock"))
            if at is None:
                continue
            try:
                value = float(item.get("lastvalue"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            metric_type = _metric_for_item(item)
            if metric_type is None:
                continue
            value = _to_noc_unit(item, metric_type, value)
            if _no_reply(metric_type, value):
                continue

            # Toutes les séries de la métrique contribuent (somme des
            # interfaces, disque le plus rempli…), datées de la plus récente.
            current = grouped.get(metric_type)
            if current is None:
                grouped[metric_type] = (at, [value])
            else:
                grouped[metric_type] = (max(at, current[0]), [*current[1], value])

        return {
            metric_type: MetricPoint(at=at, value=combine_latest(values, metric_type))
            for metric_type, (at, values) in grouped.items()
        }

    async def fetch_maintenance(self) -> list[dict]:
        """Maintenances Zabbix en cours, à venir ou terminées depuis moins de
        30 jours, avec leurs hôtes (directs ou par groupe).

        `start`/`end` sont la période de VALIDITÉ (active_since/active_till) ;
        les créneaux précis vivent dans le calendrier de la maintenance, et
        c'est `maintenance_status` de l'hôte qui dit s'il y est maintenant.
        """
        horizon = int(time.time()) - 30 * 86400
        maintenances = await self._call(
            "maintenance.get",
            {
                "output": ["maintenanceid", "name", "description", "maintenance_type",
                           "active_since", "active_till"],
                "selectHosts": ["hostid", "host", "name"],
                "selectHostGroups": ["groupid"],
            },
        )
        group_ids = sorted({
            str(group["groupid"])
            for item in maintenances
            for group in item.get("hostgroups") or []
        })
        hosts_by_group: dict[str, list[dict]] = {}
        if group_ids:
            for host in await self._call(
                "host.get",
                {"output": ["hostid", "host", "name"], "groupids": group_ids,
                 "selectHostGroups": ["groupid"]},
            ):
                for group in host.get("hostgroups") or []:
                    hosts_by_group.setdefault(str(group["groupid"]), []).append(host)
        windows = []
        for item in maintenances:
            end = int(item.get("active_till") or 0)
            if end and end < horizon:
                continue
            hosts = {str(h["hostid"]): h for h in item.get("hosts") or []}
            for group in item.get("hostgroups") or []:
                for host in hosts_by_group.get(str(group["groupid"]), []):
                    hosts.setdefault(str(host["hostid"]), host)
            start_dt = epoch_to_dt(item.get("active_since"))
            end_dt = epoch_to_dt(item.get("active_till"))
            windows.append({
                "key": f"zabbix:maintenance:{item['maintenanceid']}",
                "tool": self.name,
                "kind": "maintenance",
                "ref": str(item["maintenanceid"]),
                "title": item.get("name") or "(sans nom)",
                "status": None,
                "start": start_dt.isoformat() if start_dt else None,
                "end": end_dt.isoformat() if end_dt else None,
                # 0 = avec collecte de données, 1 = sans collecte.
                "outage": None,
                "description": item.get("description") or None,
                "cis": [
                    {"ref": hostid, "name": host.get("host") or host.get("name")}
                    for hostid, host in hosts.items()
                ],
            })
        return windows

    async def fetch_fleet_latest(self) -> dict[str, dict[str, float]]:
        """Dernières valeurs de tout le parc Zabbix, en un seul `item.get`.

        Le filtre `search` sur les racines de clé utiles (préfixes) évite de
        rapatrier les centaines d'items sans intérêt d'un gabarit. Une valeur
        de plus de 15 minutes est écartée : un hôte qui ne remonte plus ne
        doit pas tirer la moyenne avec une mesure d'hier.
        """
        items = await self._call(
            "item.get",
            {
                "output": ["hostid", "key_", "units", "lastvalue", "lastclock"],
                "monitored": True,
                "search": {"key_": list(_FLEET_KEY_PREFIXES)},
                "searchByAny": True,
                "startSearch": True,
            },
        )
        horizon = time.time() - 900
        grouped: dict[str, dict[str, list[float]]] = {}
        for item in items:
            try:
                clock = int(item.get("lastclock") or 0)
                value = float(item.get("lastvalue"))
            except (TypeError, ValueError):
                continue
            if clock < horizon or not math.isfinite(value):
                continue
            metric_type = _metric_for_item(item)
            if metric_type is None:
                continue
            value = _to_noc_unit(item, metric_type, value)
            if _no_reply(metric_type, value):
                continue
            grouped.setdefault(str(item["hostid"]), {}).setdefault(metric_type, []).append(value)
        return {
            host: {metric: combine_latest(values, metric) for metric, values in metrics.items()}
            for host, metrics in grouped.items()
        }

    async def _fetch_history_window(
        self, method: str, params: dict, start_ts: int, end_ts: int
    ) -> list[dict]:
        query = {
            **params,
            "time_from": start_ts,
            "time_till": end_ts,
            "limit": _PAGE_SIZE,
        }
        rows = await self._call(method, query)
        if len(rows) < _PAGE_SIZE:
            return rows
        if start_ts >= end_ts:
            raise ToolUnavailable(
                self.name,
                f"{method} dépasse {_PAGE_SIZE} points sur une seconde; "
                "la série est incomplète",
            )

        middle = (start_ts + end_ts) // 2
        left = await self._fetch_history_window(method, params, start_ts, middle)
        right = await self._fetch_history_window(method, params, middle + 1, end_ts)
        return left + right

    async def _items_for(
        self, node_ref: str, metric_type: str | None
    ) -> list[dict]:
        """Items de l'hôte correspondant au type de métrique demandé.

        Le filtrage se fait ici et non côté Zabbix : l'API ne sait pas filtrer
        `item.get` sur une racine de clé, seulement sur une clé exacte, et les
        clés portent des paramètres variables (`net.if.in[eth0]`).
        """
        items = await self._call(
            "item.get",
            {
                "output": [
                    "itemid", "key_", "value_type", "units", "lastvalue", "lastclock",
                    "status",
                ],
                "hostids": [str(node_ref)],
                "monitored": True,
            },
        )
        matching = []
        for item in items:
            item_metric = _metric_for_item(item)
            if item_metric is not None and (
                metric_type is None or item_metric == metric_type
            ):
                matching.append(item)
        return matching


def _coordinates(inventory) -> dict:
    """Latitude/longitude de l'inventaire Zabbix, si valides.

    L'inventaire est une liste vide quand il est désactivé sur l'hôte, et ses
    champs sont du texte libre : une valeur illisible ou hors bornes est
    ignorée plutôt que de placer l'équipement au large du golfe de Guinée.
    """
    if not isinstance(inventory, dict):
        return {}
    try:
        lat = float(str(inventory.get("location_lat") or "").replace(",", "."))
        lon = float(str(inventory.get("location_lon") or "").replace(",", "."))
    except ValueError:
        return {}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return {}
    return {"latitude": lat, "longitude": lon}


# Champs d'inventaire Zabbix -> clés de Node.details["inventory"].
_INVENTORY = {
    "vendor": "vendor",
    "model": "model",
    "serialno_a": "serial",
    "os": "os",
    "type": "type",
    "location": "location",
}
_INVENTORY_FIELDS = tuple(_INVENTORY)


def _inventory_details(inventory) -> dict:
    """Inventaire matériel de l'hôte, champs vides écartés."""
    if not isinstance(inventory, dict):
        return {}
    facts = {
        name: str(inventory[field]).strip()
        for field, name in _INVENTORY.items()
        if str(inventory.get(field) or "").strip()
    }
    return {"inventory": facts} if facts else {}


def _problem_details(problem: dict, acknowledges: list[dict]) -> dict:
    """Ce que Zabbix dit d'un problème au-delà de sa gravité :

    * `tags` — étiquettes du déclencheur (service, couche, client…) ;
    * `opdata` — donnée opérationnelle (« 95 % utilisé ») ;
    * `suppressed` — masqué par une maintenance Zabbix ;
    * `cause_ref` — Zabbix 7 : ce problème est le SYMPTÔME d'un autre ;
    * `actions` — commentaires laissés à l'acquittement, du plus ancien au
      plus récent.
    """
    details: dict = {}
    tags = [
        {"tag": str(tag.get("tag") or ""), "value": str(tag.get("value") or "")}
        for tag in problem.get("tags") or []
        if tag.get("tag")
    ]
    if tags:
        details["tags"] = tags
    if str(problem.get("opdata") or "").strip():
        details["opdata"] = str(problem["opdata"]).strip()
    if str(problem.get("suppressed")) == "1":
        details["suppressed"] = True
    if str(problem.get("cause_eventid") or "0") not in ("", "0"):
        details["cause_ref"] = str(problem["cause_eventid"])
    actions = []
    for action in acknowledges:
        message = str(action.get("message") or "").strip()
        if not message:
            continue
        user = (
            " ".join(filter(None, (action.get("name"), action.get("surname")))).strip()
            or action.get("username")
            or None
        )
        actions.append({"at": epoch_to_dt(action.get("clock")), "user": user, "message": message})
    if actions:
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        details["actions"] = sorted(actions, key=lambda a: a["at"] or oldest)
    return details


def _key_parameters(key: str) -> list[str]:
    """Paramètres d'une clé d'item : `vfs.fs.size[/,pused]` -> ["/", "pused"]."""
    if "[" not in key:
        return []
    inside = key.partition("[")[2].rpartition("]")[0]
    return [part.strip().strip('"').lower() for part in inside.split(",")]


def _parameter(key: str, index: int) -> str:
    parameters = _key_parameters(key)
    return parameters[index] if len(parameters) > index else ""


def _metric_for_item(item: dict) -> str | None:
    """Type de métrique NOC d'un item, ou None s'il ne doit pas être affiché.

    La RACINE de la clé ne suffit pas : ses paramètres changent ce que la
    valeur mesure. `system.cpu.util[,idle]` est le temps d'INACTIVITÉ (le
    gabarit Linux de Zabbix en publie une dizaine de variantes),
    `net.if.in[eth0,errors]` compte des erreurs et non des octets,
    `proc.num[nginx]` ne compte que les processus nginx. Les mélanger dans
    une même courbe en ferait une moyenne dénuée de sens.
    """
    key = str(item.get("key_", ""))
    root = key.split("[", 1)[0]

    if root in ("vfs.fs.size", "vfs.fs.dependent.size"):
        return "disk_pct" if _parameter(key, 1) in ("pused", "pfree") else None
    if root == "vm.memory.size":
        return "ram_pct" if _parameter(key, 0) in ("pused", "pavailable", "pfree") else None
    if root == "system.cpu.util":
        # Gabarits « … by SNMP » : `system.cpu.util[snmp,<index>]`, item
        # calculé = utilisation totale (100 - inactivité).
        if _parameter(key, 0) == "snmp":
            return "cpu_pct"
        # Agent : [<cpu>,<type>,<mode>] ; type vide = utilisation totale.
        cpu, kind, mode = _parameter(key, 0), _parameter(key, 1), _parameter(key, 2)
        if cpu not in ("", "all") or mode not in ("", "avg1"):
            return None
        return "cpu_pct" if kind in ("", "idle") else None
    if root == "system.cpu.load":
        cpu, mode = _parameter(key, 0), _parameter(key, 1)
        return "cpu_load" if cpu in ("", "all") and mode in ("", "avg1") else None
    if root in ("net.if.in", "net.if.out"):
        mode = _parameter(key, 1)
        if mode in ("", "bytes"):
            return _ITEM_KEYS[root]
        return "if_errors" if mode == "errors" else None
    if root == "proc.num":
        # Sans filtre seulement : le nombre total de processus.
        return "proc_count" if not any(_key_parameters(key)) else None
    return _ITEM_KEYS.get(root)


def _no_reply(metric_type: str, value: float) -> bool:
    """`icmppingsec` vaut 0 quand l'hôte n'a PAS répondu — pas une latence
    nulle (un aller-retour réel ne fait jamais 0,000 s). Garder ces zéros
    afficherait « 0 ms » en vert sur un équipement coupé et tirerait vers le
    bas la latence moyenne du parc."""
    return metric_type == "latency_ms" and value == 0


def _to_noc_unit(item: dict, metric_type: str, value: float) -> float:
    """Valeur brute Zabbix -> unité du NOC (voir `_SCALE`)."""
    key = str(item.get("key_", ""))
    root = key.split("[", 1)[0]
    if metric_type == "if_errors":
        return value
    if metric_type in ("bandwidth_in_mbps", "bandwidth_out_mbps") and str(
        item.get("units") or ""
    ).strip().lower() in ("bps", "b/s", "bit/s"):
        return value / 1e6  # déjà en bits/s (gabarits Zabbix)
    value *= _SCALE.get(metric_type, 1.0)
    inverted = (
        (metric_type == "disk_pct" and _parameter(key, 1) == "pfree")
        or (metric_type == "ram_pct" and _parameter(key, 0) in ("pavailable", "pfree"))
        or (root == "system.cpu.util" and _parameter(key, 1) == "idle")
    )
    return 100.0 - value if inverted else value


def _acknowledged_at(acknowledges: list[dict]):
    """Heure du PREMIER acquittement.

    `acknowledges` liste toutes les actions sur le problème (commentaire,
    changement de gravité…) dans un ordre non garanti. Seules celles qui
    portent le bit « acquitter » (2) comptent.
    """
    clocks = []
    for action in acknowledges:
        try:
            flags = int(action.get("action", 0))
        except (TypeError, ValueError):
            continue
        if flags & 2:
            stamp = epoch_to_dt(action.get("clock"))
            if stamp is not None:
                clocks.append(stamp)
    return min(clocks) if clocks else None


def _host_state(host: dict, interfaces: list[NetworkInterface]) -> str:
    """État d'un hôte Zabbix, traduit vers le vocabulaire du NOC.

    `available` ne décrit que l'agent/SNMP. Pour un hôte monitoré en ICMP
    seul, l'état vient de son dernier item `icmpping` ou `icmppingloss`.
    """
    if str(host.get("maintenance_status")) == "1":
        return "maintenance"
    if str(host.get("status")) == "1":
        return "unknown"  # hôte désactivé : Zabbix ne le sonde plus
    icmp_states = []
    for item in host.get("items") or []:
        if str(item.get("status", "0")) != "0":
            continue
        key = str(item.get("key_", "")).split("[", 1)[0]
        if key not in ("icmpping", "icmppingloss"):
            continue
        try:
            value = float(item.get("lastvalue"))
        except (TypeError, ValueError):
            continue
        if key == "icmpping":
            icmp_states.append("up" if value > 0 else "down")
        elif value >= 100:
            icmp_states.append("down")
        elif value > 0:
            icmp_states.append("degraded")
        else:
            icmp_states.append("up")
    if icmp_states:
        # « up » ne doit pas masquer une perte partielle : un hôte qui répond
        # à `icmpping` avec 40 % de pertes est dégradé, pas sain.
        if all(state == "down" for state in icmp_states):
            return "down"
        if "degraded" in icmp_states or "down" in icmp_states:
            return "degraded"
        return "up"

    availabilities = {interface.available for interface in interfaces}
    if 1 in availabilities:
        return "up"
    if 2 in availabilities:
        return "down"
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
