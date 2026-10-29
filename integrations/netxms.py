"""
Connecteur NetXMS 5.0 — API Web (netxms-websvc), JSON. Le chemin de
PRODUCTION : en exploitation, le NOC ne lit NetXMS que par son API.

L'accès par la base (integrations/netxms_db.py) ne sert qu'à visualiser le
dump de production restauré en local ; les deux rendent les mêmes `Node` et
`Alert`. Isoler l'API dans ce fichier permet de basculer sur l'API embarquée
des versions récentes sans toucher au reste.

À VALIDER SUR L'INSTANCE RÉELLE. NetXMS ne publie aucune image Docker et n'est
pas monté dans la pile locale : les chemins et la forme des réponses
ci-dessous n'ont pas été confrontés à l'instance de l'agence. Le connecteur
accepte donc les variantes connues (classe et état en nombre ou en nom, dates
en secondes, millisecondes ou ISO 8601), et `python -m collector.probe netxms`
montre, sur l'instance réelle, ce qui est lu et ce qui manque. Les noms de DCI
de `fetch_history` sont libres dans NetXMS : leur correspondance est à
confirmer aussi.

CE QUE L'API NE DONNE PAS : le référentiel de sites de l'agence (colonne
`siteadmin_id` et schéma `donnebase`, propres à sa base). Le site vient alors
d'un attribut personnalisé (NETXMS_SITE_ATTRIBUTE) ou, à défaut, de la ville
de l'objet ; la province et la région, de la ville ou des coordonnées
(integrations/localities.py).
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
from datetime import datetime

from .base import SourceClient, ToolUnavailable
from .localities import locate
from .models import Alert, MetricPoint, Node, ToolHealth
from .normalize import display_locality, epoch_to_dt, iso_to_dt, severity, source_severity

logger = logging.getLogger(__name__)

# Classes d'objets NetXMS retenues à l'inventaire. NetXMS modélise aussi les
# conteneurs, les sous-réseaux et les grappes : les remonter comme des
# équipements gonflerait le parc d'objets qui ne sont pas des machines.
# 2 est le code numérique de la classe Node.
_NODE_CLASSES = frozenset({"Node", "AccessPoint", "2"})
_PAGE_SIZE = 500
_MAX_PAGES = 200
# Alarmes dont la source n'est pas un équipement (une interface, le plus
# souvent) : leur équipement est cherché objet par objet, puis gardé en
# mémoire. Plafonné par cycle pour borner la charge envoyée à NetXMS.
_MAX_SOURCE_LOOKUPS = 100

# État d'un objet NetXMS : 0 Normal, 1 Warning, 2 Minor, 3 Major,
# 4 Critical, 5 Unknown, 6 Unmanaged, 7 Disabled, 8 Testing.
_OBJECT_STATE = {
    0: "up",
    1: "degraded",
    2: "degraded",
    3: "down",
    4: "down",
    5: "silent",
    6: "unknown",
    7: "unknown",
    8: "maintenance",
}
_STATUS_NAMES = {
    "NORMAL": 0, "WARNING": 1, "MINOR": 2, "MAJOR": 3, "CRITICAL": 4,
    "UNKNOWN": 5, "UNMANAGED": 6, "DISABLED": 7, "TESTING": 8,
}
# États d'interface : administratif et opérationnel, puis état attendu.
_INTERFACE_STATE_NAMES = {"UP": 1, "DOWN": 2, "TESTING": 3, "UNKNOWN": 0}
_EXPECTED_STATE_NAMES = {"UP": 0, "DOWN": 1, "IGNORE": 2}
# Gravité d'alarme : 0 Normal … 4 Critical, mêmes noms que les états.
_SEVERITY_NAMES = {"NORMAL": 0, "WARNING": 1, "MINOR": 2, "MAJOR": 3, "CRITICAL": 4}
# État d'alarme : 0 en cours, 1 acquittée, 2 résolue, 3 terminée.
_ALARM_STATE_NAMES = {"OUTSTANDING": 0, "ACKNOWLEDGED": 1, "RESOLVED": 2, "TERMINATED": 3}


def _code(value, names: dict[str, int]) -> int | None:
    """Code NetXMS, qu'il arrive en nombre (3) ou en nom (« MAJOR »)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
        return names.get(text.upper())
    return None


def _when(value) -> datetime | None:
    """Date NetXMS : secondes, millisecondes ou chaîne ISO 8601."""
    if isinstance(value, str) and not value.strip().isdigit():
        return iso_to_dt(value)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    # Au-delà de l'an 5138 en secondes, c'est forcément des millisecondes.
    return epoch_to_dt(number // 1000 if number > 99_999_999_999 else number)


def _ref(obj: dict) -> str | None:
    ref = obj.get("objectId", obj.get("id"))
    return None if ref is None else str(ref)


def _valid_ip(value) -> str | None:
    # NetXMS écrit 0.0.0.0 pour « pas d'adresse » : la laisser passer ferait
    # fusionner entre eux tous les équipements sans IP.
    if isinstance(value, dict):
        value = value.get("address")
    value = str(value or "").split("/")[0].strip()
    return value if value and value not in ("0.0.0.0", "::") else None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def _coordinate(location: dict, *names: str) -> float | None:
    for name in names:
        try:
            value = float(location.get(name))
        except (TypeError, ValueError):
            continue
        # 0,0 est la valeur par défaut d'un objet non géolocalisé.
        return value or None
    return None


def _custom_attribute(obj: dict, name: str) -> str | None:
    attributes = obj.get("customAttributes") or {}
    value = attributes.get(name)
    if isinstance(value, dict):  # { "value": …, "flags": … } selon les versions
        value = value.get("value")
    return (str(value).strip() or None) if value is not None else None


def _first(obj: dict, *names: str):
    """Première valeur renseignée parmi les noms qu'un champ porte selon les
    versions de l'API."""
    for name in names:
        value = obj.get(name)
        if value not in (None, "", 0, "0"):
            return value
    return None


# Disponibilité calculée par un script de l'agence et rangée dans des
# attributs personnalisés des nœuds (72 nœuds dans le dump du 7 août 2026).
# mttr et mtbf sont en heures : TotalDowntime / NumFailures = mttr × 3 600.
AVAILABILITY_ATTRIBUTES = (
    "perAvailability", "mttr", "mtbf", "NumFailures", "TotalDowntime", "TimeStamp",
)


def availability_from_attributes(attributes: dict[str, str | None]) -> dict | None:
    """{pct, mttr_h, mtbf_h, failures, downtime_s, computed_at}, ou None si
    l'agence n'a pas calculé la disponibilité de ce nœud."""
    def number(name: str) -> float | None:
        try:
            value = float(str(attributes.get(name)).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return value if value == value else None  # NaN écarté

    pct = number("perAvailability")
    if pct is None or not 0 <= pct <= 100:
        return None
    failures = number("NumFailures")
    downtime = number("TotalDowntime")
    computed = number("TimeStamp")
    return {
        "pct": round(pct, 3),
        "mttr_h": number("mttr"),
        "mtbf_h": number("mtbf"),
        "failures": int(failures) if failures is not None else None,
        "downtime_s": int(downtime) if downtime is not None else None,
        "computed_at": epoch_to_dt(int(computed)) if computed else None,
    }


def interface_summary(rows) -> dict[str, dict]:
    """Résumé des interfaces, par équipement.

    `rows` : (node_id, admin, oper, expected, speed_bps[, ref, nom]). États NetXMS :
    admin et oper 1 = actif, 2 = inactif ; expected 0 = doit être actif,
    1 = doit être inactif, 2 = à ignorer.

    Une interface inactive n'est une panne que si elle devait être active.
    Deux lectures, donc : les interfaces ACTIVÉES par l'administrateur (dont
    des ports libres, inactifs sans être en panne), et les interfaces
    SURVEILLÉES — celles que NetXMS attend actives, les vrais liens.
    """
    summary: dict[str, dict] = {}
    for node_id, admin, oper, expected, speed, *_rest in rows:
        if node_id in (None, "", 0, "0"):
            continue
        item = summary.setdefault(str(node_id), {
            "total": 0, "enabled": 0, "enabled_up": 0, "enabled_down": 0,
            "watched": 0, "watched_down": 0, "capacity_bps": 0,
        })
        item["total"] += 1
        if admin != 1:
            continue
        item["enabled"] += 1
        if oper == 1:
            item["enabled_up"] += 1
            try:
                item["capacity_bps"] += max(0, int(speed or 0))
            except (TypeError, ValueError):
                pass
        elif oper == 2:
            item["enabled_down"] += 1
        if expected == 0:
            item["watched"] += 1
            if oper == 2:
                item["watched_down"] += 1
    return summary


# Plafond par équipement : un cœur de réseau peut porter des centaines
# d'interfaces surveillées ; au-delà, l'instantané grossirait sans que la
# fiche d'équipement y gagne.
_MAX_LINKS_PER_NODE = 200


def watched_links(rows) -> dict[str, list[dict]]:
    """Liens surveillés, un par un, par équipement : interfaces activées que
    NetXMS attend actives. C'est ce qui permet l'historique de disponibilité
    PAR LIEN (collector/history.py) ; le résumé d'interface_summary ne donne
    que des comptes.

    `rows` comme interface_summary, avec la référence et le nom de
    l'interface en 6e et 7e position. État : up, down, ou unknown.
    """
    links: dict[str, list[dict]] = {}
    for row in rows:
        if len(row) < 7:
            continue
        node_id, admin, oper, expected, speed, ref, name = row[:7]
        if node_id in (None, "", 0, "0") or ref in (None, "") or admin != 1 or expected != 0:
            continue
        items = links.setdefault(str(node_id), [])
        if len(items) >= _MAX_LINKS_PER_NODE:
            continue
        try:
            speed_bps = max(0, int(speed or 0))
        except (TypeError, ValueError):
            speed_bps = 0
        items.append({
            "ref": str(ref),
            "name": str(name or ref),
            "state": "up" if oper == 1 else "down" if oper == 2 else "unknown",
            "speed_bps": speed_bps,
        })
    return links


class NetXMSClient(SourceClient):
    name = "netxms"

    def __init__(
        self,
        base_url: str,
        user: str = "",
        password: str = "",
        verify_ssl: bool = True,
        timeout_s: float = 20.0,
        site_attribute: str = "",
        collect_interfaces: bool = True,
    ):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        self.site_attribute = site_attribute
        self.collect_interfaces = collect_interfaces
        # Objet source d'alarme -> équipement. Une interface ne change pas
        # d'équipement : la correspondance est gardée d'un cycle à l'autre.
        self._source_node: dict[str, tuple[str, str | None]] = {}

    async def _get(self, path: str, params: dict | None = None):
        response = await self._request(
            "GET",
            f"{self.base_url}{path}",
            params=params,
            auth=(self.user, self.password),  # Basic Auth, propre à la Legacy Web API
        )
        try:
            return response.json()
        except ValueError as exc:
            raise ToolUnavailable(self.name, f"réponse non-JSON sur {path}") from exc

    async def check(self) -> ToolHealth:
        async def probe():
            body = await self._get("/v1/status")
            return (body or {}).get("version")

        return await self._health(probe)

    async def _list_objects(self, object_class: str) -> list[dict]:
        """Tous les objets d'une classe, page par page, sans en perdre un."""
        objects: list[dict] = []
        seen_ids: set[str] = set()
        offset = 0
        for _ in range(_MAX_PAGES):
            previous_ids = seen_ids.copy()
            body = await self._get(
                "/objects",
                {"class": object_class, "offset": offset, "limit": _PAGE_SIZE},
            )
            if isinstance(body, list):
                page = body
                total = None
            elif isinstance(body, dict):
                page = body.get("objects", [])
                total = body.get("totalCount", body.get("total"))
                if isinstance(page, dict):
                    page = list(page.values())
            else:
                raise ToolUnavailable(
                    self.name, "réponse /objects invalide : liste ou objet attendu"
                )
            if not isinstance(page, list):
                raise ToolUnavailable(self.name, "réponse /objects invalide : objects")
            objects.extend(page)
            seen_ids.update(ref for ref in map(_ref, page) if ref is not None)
            if total is not None:
                try:
                    expected_total = int(total)
                except (TypeError, ValueError) as exc:
                    raise ToolUnavailable(
                        self.name, "réponse /objects avec total invalide"
                    ) from exc
                if len(objects) >= expected_total:
                    break
                if len(page) < _PAGE_SIZE:
                    raise ToolUnavailable(
                        self.name,
                        f"pagination /objects incomplète : {len(objects)} objet(s) "
                        f"reçu(s) sur {expected_total} annoncés",
                    )
            elif len(page) < _PAGE_SIZE:
                break
            new_page_ids = {ref for ref in map(_ref, page) if ref is not None} - previous_ids
            if not page or not new_page_ids:
                raise ToolUnavailable(
                    self.name, "pagination /objects répétée; inventaire incomplet"
                )
            offset += len(page)
        else:
            raise ToolUnavailable(
                self.name,
                f"pagination /objects interrompue après {_MAX_PAGES} pages",
            )
        return objects

    async def _container_names(self) -> dict[str, str]:
        """Conteneurs NetXMS (« Client », « Core »…), pour nommer les groupes.

        Facultatif : un échec ne prive l'inventaire que de ses groupes."""
        try:
            containers = await self._list_objects("Container")
        except ToolUnavailable as exc:
            logger.warning("netxms : conteneurs non lus, équipements sans groupe (%s)", exc)
            return {}
        return {
            ref: str(obj.get("objectName") or obj.get("name"))
            for obj in containers
            if (ref := _ref(obj)) and (obj.get("objectName") or obj.get("name"))
        }

    @staticmethod
    def _details(obj: dict, interfaces: dict | None, links: list | None = None) -> dict:
        """Faits de la fiche d'équipement : inventaire, démarrage, panne,
        disponibilité calculée par l'agence, interfaces."""
        details: dict = {}
        inventory = {
            name: str(value).strip()
            for name, value in (
                ("vendor", _first(obj, "vendor", "hardwareVendor")),
                ("model", _first(obj, "productName", "hardwareProductName", "productCode")),
                ("serial", _first(obj, "serialNumber", "hardwareSerialNumber")),
                ("os", _first(obj, "platformName")),
                ("location", _first(obj, "snmpSysLocation")),
            )
            if value is not None and str(value).strip()
        }
        if inventory:
            details["inventory"] = inventory
        for name, field in (("boot_time", "bootTime"), ("down_since", "downSince")):
            when = _when(obj.get(field))
            if when is not None:
                details[name] = when
        availability = availability_from_attributes(
            {name: _custom_attribute(obj, name) for name in AVAILABILITY_ATTRIBUTES}
        )
        if availability:
            details["availability"] = availability
        if interfaces:
            details["interfaces"] = interfaces
        if links:
            details["links"] = links
        return details

    def _node(
        self,
        obj: dict,
        containers: dict[str, str],
        interfaces: dict[str, dict] | None = None,
        links: dict[str, list] | None = None,
    ) -> Node:
        ref = _ref(obj)
        if ref is None:
            raise ToolUnavailable(self.name, "équipement NetXMS sans identifiant")
        status = _code(obj.get("status"), _STATUS_NAMES)
        name = obj.get("objectName") or obj.get("name") or ""
        # `primaryName` est le nom DNS quand il existe, et l'adresse IP sinon :
        # une IP n'identifie pas un nom, le nom technique retombe alors sur
        # le nom de l'objet — comme dans netxms_db.py.
        primary_name = str(obj.get("primaryName") or "")
        technical = primary_name if primary_name and not _is_ip(primary_name) else name

        address = obj.get("postalAddress") or {}
        city = str(address.get("city") or obj.get("city") or "").strip() or None
        location = obj.get("geolocation") or obj
        latitude = _coordinate(location, "latitude", "lat")
        longitude = _coordinate(location, "longitude", "lon")
        province, region = locate(city, latitude, longitude)
        # Site : l'attribut désigné par l'agence d'abord, sinon la ville.
        site = (
            _custom_attribute(obj, self.site_attribute) if self.site_attribute else None
        ) or (city.title() if city else None)

        parents = obj.get("parents") or obj.get("parentIdList") or obj.get("parentIds") or ()
        groups = tuple(sorted(
            {containers[str(parent)] for parent in parents if str(parent) in containers}
        ))
        return Node(
            tool=self.name,
            ref=ref,
            name=name or primary_name or "(sans nom)",
            hostname=technical or "",
            ip=_valid_ip(obj.get("primaryIP") or obj.get("primaryIp") or obj.get("ipAddress")),
            state=_OBJECT_STATE.get(status, "unknown"),
            enabled=status not in (6, 7),  # 6 non géré, 7 désactivé
            groups=groups,
            site=site,
            province=display_locality(province),
            region=display_locality(region),
            latitude=latitude,
            longitude=longitude,
            details=self._details(obj, (interfaces or {}).get(ref), (links or {}).get(ref)),
        )

    async def _interfaces(self, node_ids: set[str]) -> tuple[dict[str, dict], dict[str, list]]:
        """Résumé des interfaces par équipement (voir interface_summary).

        Facultatif, et désactivable (NETXMS_COLLECT_INTERFACES=false) : c'est
        la lecture la plus lourde du cycle, plusieurs dizaines de milliers
        d'objets sur le parc de l'agence. Un échec ne prive l'inventaire que
        de ce résumé."""
        if not self.collect_interfaces:
            return {}, {}
        try:
            objects = await self._list_objects("Interface")
        except ToolUnavailable as exc:
            logger.warning("netxms : interfaces non lues (%s)", exc)
            return {}, {}
        rows = []
        for obj in objects:
            parents = [str(p) for p in (
                obj.get("parents") or obj.get("parentIdList") or obj.get("parentIds") or ()
            )]
            node_id = _first(obj, "parentNodeId", "nodeId") or next(
                (parent for parent in parents if parent in node_ids), None
            )
            rows.append((
                str(node_id) if node_id is not None else None,
                _code(obj.get("adminState"), _INTERFACE_STATE_NAMES),
                _code(obj.get("operState"), _INTERFACE_STATE_NAMES),
                _code(obj.get("expectedState"), _EXPECTED_STATE_NAMES),
                obj.get("speed"),
                _ref(obj),
                obj.get("objectName") or obj.get("ifName") or obj.get("name"),
            ))
        return interface_summary(rows), watched_links(rows)

    async def fetch_nodes(self) -> list[Node]:
        objects = [
            obj for obj in await self._list_objects("Node")
            if obj.get("objectClass") is None or str(obj["objectClass"]) in _NODE_CLASSES
        ]
        containers = await self._container_names()
        interfaces, links = await self._interfaces({ref for ref in map(_ref, objects) if ref})
        return [self._node(obj, containers, interfaces, links) for obj in objects]

    async def _resolve_sources(self, source_ids: set[str]) -> None:
        """Rattache à leur équipement les objets source encore inconnus.

        Une alarme d'interface (« GigabitEthernet2 down ») a pour source
        l'INTERFACE : sans remonter à son parent, un dixième des alarmes
        resteraient orphelines sur l'écran du NOC."""
        pending = sorted(source_ids - self._source_node.keys())[:_MAX_SOURCE_LOOKUPS]

        async def lookup(source_id: str) -> None:
            try:
                body = await self._get(f"/objects/{source_id}")
            except ToolUnavailable as exc:
                logger.warning("netxms : objet source %s non lu (%s)", source_id, exc)
                return
            obj = (body or {}).get("object", body) if isinstance(body, dict) else {}
            object_class = str(obj.get("objectClass", "Node"))
            parents = obj.get("parents") or obj.get("parentIdList") or obj.get("parentIds") or ()
            if object_class in _NODE_CLASSES or not parents:
                self._source_node[source_id] = (source_id, obj.get("objectName"))
            else:
                # Une interface a pour parent son équipement (et parfois un
                # sous-réseau) : le parent nœud est retenu quand NetXMS le
                # désigne, sinon le premier parent.
                node_id = str(obj.get("parentNodeId") or next(iter(parents)))
                self._source_node[source_id] = (node_id, None)

        await asyncio.gather(*(lookup(source_id) for source_id in pending))

    async def fetch_alerts(self) -> list[Alert]:
        body = await self._get("/alarms")
        if isinstance(body, dict):
            items = body.get("alarms", [])
            if isinstance(items, dict):
                items = list(items.values())
        elif isinstance(body, list):
            items = body
        else:
            raise ToolUnavailable(self.name, "réponse /alarms invalide")

        active = [
            alarm for alarm in items
            # Seuls les états 0 (en cours) et 1 (acquittée) sont actifs ; le
            # bit 0x10 marque un acquittement « collant ».
            if (_code(alarm.get("state", 0), _ALARM_STATE_NAMES) or 0) & 15 in (0, 1)
        ]
        await self._resolve_sources({
            str(alarm["sourceObjectId"]) for alarm in active if alarm.get("sourceObjectId")
        })

        alerts: list[Alert] = []
        for alarm in active:
            ref = alarm.get("id") or alarm.get("alarmId")
            if ref is None:
                raise ToolUnavailable(self.name, "alarme NetXMS sans identifiant")
            since = _when(alarm.get("creationTime"))
            if since is None:
                raise ToolUnavailable(
                    self.name, f"alarme {ref} sans date de création valide"
                )
            state = (_code(alarm.get("state", 0), _ALARM_STATE_NAMES) or 0) & 15
            raw_severity = _code(
                alarm.get("currentSeverity", alarm.get("severity")), _SEVERITY_NAMES
            )
            source_id = str(alarm.get("sourceObjectId") or "") or None
            node_ref, node_name = self._source_node.get(source_id, (source_id, None))
            acknowledged = state == 1
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(ref),
                    severity=severity("netxms", raw_severity),
                    source_severity=source_severity("netxms", raw_severity),
                    message=alarm.get("message") or "(sans libellé)",
                    since=since,
                    node_ref=node_ref,
                    node_name=alarm.get("sourceObjectName") if node_ref == source_id
                    else node_name,
                    acknowledged=acknowledged,
                    acknowledged_at=(
                        _when(alarm.get("ackTime") or alarm.get("lastChangeTime"))
                        if acknowledged else None
                    ),
                )
            )
        return alerts

    async def fetch_history(
        self, node_ref: str, metric_type: str, start: datetime, end: datetime
    ) -> list[MetricPoint]:
        dcis = await self._get(f"/objects/{node_ref}/dcis")
        items = dcis.get("dcis", dcis) if isinstance(dcis, dict) else dcis

        dci_id = None
        for item in items:
            name = str(item.get("name") or item.get("description") or "").lower()
            # Mapping empirique pour les métriques personnalisées
            if metric_type == "rssi" and "rssi" in name:
                dci_id = item.get("id")
                break
            if metric_type == "temp_cpu" and ("temp" in name or "température" in name):
                dci_id = item.get("id")
                break
            # `dci_custom` ne désigne aucune DCI précise : prendre la première
            # de la liste afficherait une mesure quelconque, d'unité inconnue,
            # sous un libellé qui laisse croire à un indicateur choisi.

        if not dci_id:
            return []

        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        data = await self._get(
            f"/dci/{dci_id}/values", {"start": start_ts, "end": end_ts}
        )
        values = data.get("values", data) if isinstance(data, dict) else data

        points: list[MetricPoint] = []
        for value in values:
            at = _when(value.get("timestamp"))
            if at is None:
                raise ToolUnavailable(
                    self.name, f"valeur DCI {dci_id} sans horodatage valide"
                )
            try:
                number = float(value["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ToolUnavailable(
                    self.name, f"valeur invalide dans la DCI {dci_id}"
                ) from exc
            points.append(MetricPoint(at=at, value=number))
        return points
