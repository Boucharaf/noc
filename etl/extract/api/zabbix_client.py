"""
Connecteur API Zabbix (7.0) — JSON-RPC sur api_jsonrpc.php.

Référence : https://www.zabbix.com/documentation/current/en/manual/api

Méthodes utilisées :
    user.login / user.logout   -> authentification (jeton de session)
    host.get                   -> dim_node (équipements)
    hostgroup.get               -> hiérarchie (site/ministère par convention de nommage)
    problem.get                 -> alertes actives -> fact_incident (status='open')
    event.get                   -> historique complet -> fact_incident (résolu), MTTA/MTTR
    history.get / trend.get     -> métriques temps réel / rétroactives -> metric_value

Piège documenté : trend.get n'a qu'une granularité horaire (min/avg/max),
à réserver au remplissage rétroactif ; history.get pour le temps réel.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Optional

import requests

from .common import ToolUnavailableError, build_session

_ITEM_KEY_TO_METRIC_TYPE = {
    "icmpping": None,  # traité via icmppingloss / icmppingsec ci-dessous
    "icmppingloss": "packet_loss_pct",
    "icmppingsec": "latency_ms",
    "net.if.in": "bandwidth_in_mbps",
    "net.if.out": "bandwidth_out_mbps",
    "system.cpu.util": "cpu_pct",
    "vm.memory.util": "ram_pct",
}


class ZabbixClient:
    def __init__(self, base_url: str, user: str, password: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/") + "/api_jsonrpc.php"
        self.user = user
        self.password = password
        self.session = build_session(verify_ssl)
        self._auth_token: Optional[str] = None
        self._id_counter = itertools.count(1)

    # -- plumbing -----------------------------------------------------
    def _call(self, method: str, params: dict, auth_required: bool = True) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": next(self._id_counter),
        }
        if auth_required:
            payload["auth"] = self._token()
        try:
            resp = self.session.post(self.base_url, json=payload, timeout=30)
            resp.raise_for_status()
            body = resp.json()
        except requests.exceptions.RequestException as exc:
            raise ToolUnavailableError(f"Zabbix injoignable: {exc}") from exc
        if "error" in body:
            raise ToolUnavailableError(f"Zabbix API error: {body['error']}")
        return body["result"]

    def _token(self) -> str:
        if self._auth_token is None:
            result = self._call(
                "user.login",
                {"username": self.user, "password": self.password},
                auth_required=False,
            )
            self._auth_token = result
        return self._auth_token

    def health_check(self) -> bool:
        try:
            self._call("apiinfo.version", {}, auth_required=False)
            return True
        except ToolUnavailableError:
            return False

    # -- données --------------------------------------------------------
    def fetch_nodes(self) -> list[dict]:
        hosts = self._call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "selectInterfaces": ["ip"],
                "selectHostGroups": ["name"],
            },
        )
        nodes = []
        for h in hosts:
            ip = h["interfaces"][0]["ip"] if h.get("interfaces") else None
            groups = [g["name"] for g in h.get("hostgroups", [])]
            nodes.append(
                {
                    "source_tool": "zabbix",
                    "external_ref": h["hostid"],
                    "name": h.get("name") or h["host"],
                    "ip_address": ip,
                    "is_active": h["status"] == "0",  # 0 = monitored
                    "groups": groups,  # exploité par identity_resolution / découpage géographique
                }
            )
        return nodes

    def fetch_incidents(self, since: datetime) -> list[dict]:
        ts = int(since.replace(tzinfo=timezone.utc).timestamp())
        events = self._call(
            "event.get",
            {
                "output": "extend",
                "select_acknowledges": "extend",
                "selectHosts": ["hostid"],
                "time_from": ts,
                "value": 1,  # PROBLEM events uniquement
                "sortfield": "clock",
                "sortorder": "ASC",
            },
        )
        incidents = []
        for e in events:
            ack_times = [a["clock"] for a in e.get("acknowledges", [])]
            incidents.append(
                {
                    "source_tool": "zabbix",
                    "external_id": e["eventid"],
                    "node_external_ref": e["hosts"][0]["hostid"] if e.get("hosts") else None,
                    "severity": int(e.get("severity", 0)),
                    "detected_at": datetime.fromtimestamp(int(e["clock"]), tz=timezone.utc),
                    "acknowledged_at": (
                        datetime.fromtimestamp(int(ack_times[0]), tz=timezone.utc)
                        if ack_times
                        else None
                    ),
                    "resolved_at": (
                        datetime.fromtimestamp(int(e["r_clock"]), tz=timezone.utc)
                        if e.get("r_clock") and e["r_clock"] != "0"
                        else None
                    ),
                    "description": e.get("name"),
                    "status": "resolved" if e.get("r_clock") not in (None, "0") else "open",
                }
            )
        return incidents

    def fetch_metrics(self, since: datetime) -> list[dict]:
        """Récupère les items pertinents puis leur historique depuis `since`.
        Séparé en deux appels car Zabbix ne permet pas de filtrer history.get
        par clé d'item directement : il faut d'abord résoudre les itemid."""
        items = self._call(
            "item.get",
            {"output": ["itemid", "hostid", "key_", "value_type"], "monitored": True},
        )
        ts_from = int(since.replace(tzinfo=timezone.utc).timestamp())
        metrics: list[dict] = []
        # Regroupement par value_type car history.get l'exige (0=float,3=uint,...)
        by_type: dict[str, list[dict]] = {}
        for it in items:
            key_root = it["key_"].split("[")[0]
            metric_type = _ITEM_KEY_TO_METRIC_TYPE.get(key_root)
            if metric_type is None:
                continue
            by_type.setdefault(it["value_type"], []).append({**it, "metric_type": metric_type})

        for value_type, its in by_type.items():
            itemids = [i["itemid"] for i in its]
            history = self._call(
                "history.get",
                {
                    "output": "extend",
                    "history": int(value_type),
                    "itemids": itemids,
                    "time_from": ts_from,
                    "sortfield": "clock",
                    "sortorder": "ASC",
                },
            )
            itemid_to_meta = {i["itemid"]: i for i in its}
            for h in history:
                meta = itemid_to_meta.get(h["itemid"])
                if not meta:
                    continue
                metrics.append(
                    {
                        "source_tool": "zabbix",
                        "node_external_ref": meta["hostid"],
                        "metric_type": meta["metric_type"],
                        "time": datetime.fromtimestamp(int(h["clock"]), tz=timezone.utc),
                        "value": float(h["value"]),
                    }
                )
        return metrics
