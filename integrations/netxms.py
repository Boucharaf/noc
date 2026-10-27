"""
Connecteur NetXMS 5.0 — Legacy Web API (netxms-websvc), JSON.

La 5.0 exploitée par l'agence n'a PAS l'API embarquée OpenAPI apparue en 6.x :
ce connecteur cible explicitement la Legacy Web API, servie par l'application
web `netxms-websvc` déployée à côté du serveur. Isoler ce choix dans un
fichier permet de basculer sur l'API embarquée le jour d'une migration sans
toucher au reste.

HORS PÉRIMÈTRE DU LABORATOIRE LOCAL. NetXMS ne publie aucune image Docker
officielle et n'est pas monté dans la pile locale : ce connecteur reste écrit,
testé sur ses parties pures, et s'activera dès que NETXMS_API_URL sera
renseignée. Les correspondances de DCI ci-dessous sont à confirmer sur
l'instance réelle — les noms de DCI sont libres dans NetXMS.
"""
from __future__ import annotations

from datetime import datetime

from .base import SourceClient, ToolUnavailable
from .models import Alert, MetricPoint, Node, ToolHealth
from .normalize import epoch_to_dt, severity, source_severity

# Classes d'objets NetXMS retenues à l'inventaire. NetXMS modélise aussi les
# conteneurs, les sous-réseaux et les grappes : les remonter comme des
# équipements gonflerait le parc d'objets qui ne sont pas des machines.
_NODE_CLASSES = frozenset({"Node", "AccessPoint"})
_PAGE_SIZE = 500
_MAX_PAGES = 200

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


class NetXMSClient(SourceClient):
    name = "netxms"

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

    async def fetch_nodes(self) -> list[Node]:
        objects = []
        seen_ids: set[str] = set()
        offset = 0
        for _ in range(_MAX_PAGES):
            previous_ids = seen_ids.copy()
            body = await self._get(
                "/objects",
                {"class": "Node", "offset": offset, "limit": _PAGE_SIZE},
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
            for obj in page:
                ref = obj.get("objectId") or obj.get("id")
                if ref is not None:
                    seen_ids.add(str(ref))
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
            new_page_ids = {
                str(obj.get("objectId") or obj.get("id"))
                for obj in page
                if obj.get("objectId") is not None or obj.get("id") is not None
            } - previous_ids
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

        nodes: list[Node] = []
        for obj in objects:
            if obj.get("objectClass") and obj["objectClass"] not in _NODE_CLASSES:
                continue
            ref = obj.get("objectId") or obj.get("id")
            if ref is None:
                raise ToolUnavailable(self.name, "équipement NetXMS sans identifiant")
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(ref),
                    name=obj.get("objectName") or obj.get("name") or "(sans nom)",
                    hostname=obj.get("objectName") or obj.get("name") or "",
                    ip=obj.get("primaryIP") or obj.get("ipAddress"),
                    state=_OBJECT_STATE.get(obj.get("status"), "unknown"),
                    enabled=obj.get("status") not in (6, 7),
                    groups=tuple(obj.get("parents") or ()),
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        body = await self._get("/alarms")
        alerts: list[Alert] = []
        for alarm in body.get("alarms", body if isinstance(body, list) else []):
            # État d'alarme NetXMS : 0 en cours, 1 acquittée, 2 résolue,
            # 3 terminée. Seuls 0 et 1 sont actifs.
            state = alarm.get("state", 0)
            if state not in (0, 1):
                continue
            since = epoch_to_dt(alarm.get("creationTime"))
            if since is None:
                raise ToolUnavailable(
                    self.name,
                    f"alarme {alarm.get('id') or alarm.get('alarmId')} "
                    "sans date de création valide",
                )
            ref = alarm.get("id") or alarm.get("alarmId")
            if ref is None:
                raise ToolUnavailable(self.name, "alarme NetXMS sans identifiant")
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(ref),
                    severity=severity("netxms", alarm.get("currentSeverity", alarm.get("severity"))),
                    source_severity=source_severity(
                        "netxms", alarm.get("currentSeverity", alarm.get("severity"))
                    ),
                    message=alarm.get("message") or "(sans libellé)",
                    since=since,
                    node_ref=str(alarm.get("sourceObjectId") or "") or None,
                    node_name=alarm.get("sourceObjectName"),
                    acknowledged=state == 1,
                    acknowledged_at=epoch_to_dt(alarm.get("ackTime")),
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
            at = epoch_to_dt(value.get("timestamp"))
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
