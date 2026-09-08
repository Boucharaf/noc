"""
Connecteur API Centreon (22.10) — REST API v2 (Centreon Web).

Référence : documentation Centreon Web API v2 (/api/latest/...).

Authentification : POST /api/latest/login -> token, à passer ensuite dans
l'en-tête X-AUTH-TOKEN. Le token expire (durée configurée côté Centreon,
généralement 24h) -> mis en cache via TokenCache.

Endpoints utilisés :
    /monitoring/hosts                       -> dim_node + statut temps réel
    /monitoring/services                    -> fact_incident (services en état non-OK)
    /monitoring/hosts/{id}/availability     -> disponibilité par équipement
    /monitoring/services/{id}/metrics       -> metric_value (perfdata : latence, trafic, CPU...)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .common import ToolUnavailableError, TokenCache, build_session

_METRIC_NAME_TO_TYPE = {
    "rta": "latency_ms",  # round trip average (check_icmp)
    "pl": "packet_loss_pct",  # packet loss
    "traffic_in": "bandwidth_in_mbps",
    "traffic_out": "bandwidth_out_mbps",
    "cpu": "cpu_pct",
    "memory": "ram_pct",
}


class CentreonClient:
    def __init__(self, base_url: str, user: str, password: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/") + "/api/latest"
        self.user = user
        self.password = password
        self.session = build_session(verify_ssl)
        self._tokens = TokenCache()

    def _headers(self) -> dict:
        token = self._tokens.get()
        if not token:
            token = self._login()
        return {"X-AUTH-TOKEN": token}

    def _login(self) -> str:
        try:
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"security": {"credentials": {"login": self.user, "password": self.password}}},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"Centreon injoignable (login): {exc}") from exc
        token = data["security"]["token"]
        self._tokens.set(token, ttl_seconds=23 * 3600)
        return token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}", params=params, headers=self._headers(), timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"Centreon injoignable ({path}): {exc}") from exc

    def health_check(self) -> bool:
        try:
            self._get("/platform/versions")
            return True
        except ToolUnavailableError:
            return False

    def fetch_nodes(self) -> list[dict]:
        body = self._get("/monitoring/hosts", params={"limit": 1000})
        nodes = []
        for h in body.get("result", []):
            nodes.append(
                {
                    "source_tool": "centreon",
                    "external_ref": h["id"],
                    "name": h.get("name"),
                    "is_active": h.get("is_activated", True),
                    "groups": [g.get("name") for g in h.get("groups", [])],
                }
            )
        return nodes

    def fetch_incidents(self, since: datetime) -> list[dict]:
        """Centreon n'a pas d'historique d'incidents "fermés" simple par API v2
        temps réel : on capture ici les services en état non-OK, la clôture
        est déduite au run suivant quand l'état repasse OK (voir dedup.py /
        normalize_incidents.py qui gère la fermeture par transition d'état)."""
        body = self._get(
            "/monitoring/services",
            params={"limit": 1000, "search": '{"state": {"$neq": 0}}'},
        )
        incidents = []
        for s in body.get("result", []):
            last_change = _iso_to_dt(s.get("last_hard_state_change"))
            incidents.append(
                {
                    "source_tool": "centreon",
                    "external_id": f"{s['host']['id']}-{s['id']}",
                    "node_external_ref": s["host"]["id"],
                    "severity": s.get("state"),  # 1=WARNING, 2=CRITICAL, 3=UNKNOWN
                    "detected_at": last_change,
                    "acknowledged_at": _iso_to_dt(s.get("acknowledgement_date")),
                    "resolved_at": None,  # fermé par transition d'état, pas par ce flux
                    "description": s.get("output"),
                    "status": "open",
                }
            )
        return incidents

    def fetch_metrics(self, since: datetime) -> list[dict]:
        metrics: list[dict] = []
        hosts = self._get("/monitoring/hosts", params={"limit": 1000}).get("result", [])
        for h in hosts:
            services = self._get(
                "/monitoring/services", params={"host_id": h["id"], "limit": 100}
            ).get("result", [])
            for s in services:
                try:
                    perf = self._get(f"/monitoring/services/{s['id']}/metrics")
                except ToolUnavailableError:
                    continue
                for metric in perf.get("result", {}).get("metrics", []):
                    metric_type = _METRIC_NAME_TO_TYPE.get(metric.get("name", "").lower())
                    if not metric_type:
                        continue
                    for point in metric.get("data", []):
                        ts = _iso_to_dt(point.get("time"))
                        if ts and ts < since.replace(tzinfo=timezone.utc):
                            continue
                        metrics.append(
                            {
                                "source_tool": "centreon",
                                "node_external_ref": h["id"],
                                "metric_type": metric_type,
                                "time": ts,
                                "value": point.get("value"),
                            }
                        )
        return metrics


def _iso_to_dt(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
