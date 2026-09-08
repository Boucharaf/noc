"""
Connecteur API NetXMS (5.0) — Legacy Web API (application .war séparée,
netxms-websvc), format JSON.

Référence : NetXMS Administrator Guide, section Web API/REST API.
La version 5.0 utilisée par l'agence ne dispose PAS encore de la "Built-in
Web API" (embarquée, OpenAPI) apparue en 6.x : ce connecteur cible donc
explicitement la Legacy Web API. S'isoler dans ce fichier permet de la
remplacer facilement le jour d'une migration vers l'API embarquée, sans
toucher au reste du pipeline.

Endpoints utilisés :
    /objects                         -> dim_node (nœuds, interfaces)
    /alarms                          -> fact_incident (alarmes actives + historiques)
    /objects/{id}/dci                -> liste des DCI (Data Collection Items)
    /objects/{id}/dci/{dciId}/values -> metric_value (valeurs collectées)
    /v1/status                       -> health_check
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .common import ToolUnavailableError, build_session

# DCI dont le nom/description contient un de ces mots-clés -> metric_type.
# A ajuster une fois les DCI réels de l'agence connus (voir README).
_DCI_NAME_TO_METRIC_TYPE = {
    "ping": "latency_ms",
    "packet loss": "packet_loss_pct",
    "traffic in": "bandwidth_in_mbps",
    "traffic out": "bandwidth_out_mbps",
    "cpu": "cpu_pct",
    "memory": "ram_pct",
}


class NetXMSClient:
    def __init__(self, base_url: str, user: str, password: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.auth = (user, password)  # Basic Auth (legacy Web API)
        self.session = build_session(verify_ssl)

    def _get(self, path: str, params: Optional[dict] = None):
        try:
            resp = self.session.get(
                f"{self.base_url}{path}", params=params, auth=self.auth, timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"NetXMS injoignable ({path}): {exc}") from exc

    def health_check(self) -> bool:
        try:
            self._get("/v1/status")
            return True
        except ToolUnavailableError:
            return False

    def fetch_nodes(self) -> list[dict]:
        objects = self._get("/objects")
        nodes = []
        for obj in objects:
            if obj.get("class") not in ("Node",):
                continue
            nodes.append(
                {
                    "source_tool": "netxms",
                    "external_ref": obj["id"],
                    "name": obj.get("name"),
                    "is_active": obj.get("status") not in ("UNMANAGED", "DISABLED"),
                    "parent_id": obj.get("parentId"),  # exploité pour la hiérarchie site/zone
                }
            )
        return nodes

    def fetch_incidents(self, since: datetime) -> list[dict]:
        alarms = self._get("/alarms")
        incidents = []
        for a in alarms:
            created = _epoch_to_dt(a.get("creationTime"))
            if created and created < since.replace(tzinfo=timezone.utc):
                continue
            incidents.append(
                {
                    "source_tool": "netxms",
                    "external_id": a["id"],
                    "node_external_ref": a.get("sourceObjectId"),
                    "severity": a.get("severity"),
                    "detected_at": created,
                    "acknowledged_at": _epoch_to_dt(a.get("ackTime")),
                    "resolved_at": _epoch_to_dt(a.get("resolvedTime")),
                    "description": a.get("message"),
                    "status": "resolved" if a.get("resolvedTime") else "open",
                }
            )
        return incidents

    def fetch_metrics(self, since: datetime) -> list[dict]:
        metrics: list[dict] = []
        for obj in self._get("/objects"):
            if obj.get("class") != "Node":
                continue
            node_id = obj["id"]
            try:
                dcis = self._get(f"/objects/{node_id}/dci")
            except ToolUnavailableError:
                continue  # un nœud sans DCI accessible ne doit pas interrompre la collecte
            for dci in dcis:
                metric_type = _match_metric_type(dci.get("name", "") or dci.get("description", ""))
                if not metric_type:
                    continue
                values = self._get(
                    f"/objects/{node_id}/dci/{dci['id']}/values",
                    params={"from": int(since.timestamp())},
                )
                for v in values:
                    metrics.append(
                        {
                            "source_tool": "netxms",
                            "node_external_ref": node_id,
                            "metric_type": metric_type,
                            "time": _epoch_to_dt(v.get("timestamp")),
                            "value": _to_float(v.get("value")),
                        }
                    )
        return metrics


def _match_metric_type(label: str) -> Optional[str]:
    label = (label or "").lower()
    for keyword, metric_type in _DCI_NAME_TO_METRIC_TYPE.items():
        if keyword in label:
            return metric_type
    return None


def _epoch_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
