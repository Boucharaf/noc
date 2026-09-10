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

import logging

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import epoch_to_dt, severity

logger = logging.getLogger(__name__)

# Classes d'objets NetXMS retenues à l'inventaire. NetXMS modélise aussi les
# conteneurs, les sous-réseaux et les grappes : les remonter comme des
# équipements gonflerait le parc d'objets qui ne sont pas des machines.
_NODE_CLASSES = frozenset({"Node", "AccessPoint"})

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
        body = await self._get("/objects", {"class": "Node"})
        nodes: list[Node] = []
        for obj in body.get("objects", body if isinstance(body, list) else []):
            if obj.get("objectClass") and obj["objectClass"] not in _NODE_CLASSES:
                continue
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(obj.get("objectId") or obj.get("id")),
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
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(alarm.get("id") or alarm.get("alarmId")),
                    severity=severity("netxms", alarm.get("currentSeverity", alarm.get("severity"))),
                    message=alarm.get("message") or "(sans libellé)",
                    since=epoch_to_dt(alarm.get("creationTime")),
                    node_ref=str(alarm.get("sourceObjectId") or "") or None,
                    node_name=alarm.get("sourceObjectName"),
                    acknowledged=state == 1,
                    acknowledged_at=epoch_to_dt(alarm.get("ackTime")),
                )
            )
        return [a for a in alerts if a.since is not None]
