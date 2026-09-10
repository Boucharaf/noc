"""
Connecteur Nagios — le mode dépend de ce qui est réellement déployé.

Nagios Core n'a pas d'API REST. Trois déploiements possibles, choisis par
`NAGIOS_MODE` :

    statusjson  — Nagios Core 4.x, CGI `statusjson.cgi` livré en standard.
                  C'est le cas le plus fréquent et le seul qui ne demande
                  aucune installation supplémentaire.
    livestatus  — module MK Livestatus (socket TCP, requêtes façon SQL).
    xi          — Nagios XI, API REST sous /nagiosxi/api/v1 (offre payante).

Tant que `NAGIOS_MODE` vaut `unknown`, le connecteur se déclare non joignable
avec un message qui NOMME la variable à renseigner. C'est délibéré : une
intégration non configurée doit se voir sur l'écran Interopérabilité, pas se
faire passer pour un outil en panne ni pour un outil sain sans données.

HORS PÉRIMÈTRE DU LABORATOIRE LOCAL — voir integrations/netxms.py pour la
même remarque.
"""
from __future__ import annotations

import asyncio
import logging
import os

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import epoch_to_dt

logger = logging.getLogger(__name__)

# États d'hôte Nagios : 1 UP, 2 DOWN, 4 UNREACHABLE, 8 PENDING.
_HOST_STATE = {1: "up", 2: "down", 4: "degraded", 8: "silent"}
# États de service : 1 OK, 2 WARNING, 4 CRITICAL, 8 UNKNOWN, 16 PENDING.
_SERVICE_SEVERITY = {2: "medium", 4: "critical", 8: "unknown", 16: "unknown"}


class NagiosClient(SourceClient):
    name = "nagios"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 20.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        self.mode = os.getenv("NAGIOS_MODE", "unknown").strip().lower()
        self.livestatus_port = int(os.getenv("NAGIOS_LIVESTATUS_PORT", "6557"))

    def _unconfigured(self) -> ToolUnavailable:
        return ToolUnavailable(
            self.name,
            "NAGIOS_MODE non renseigné — valeurs acceptées : "
            "statusjson, livestatus, xi",
        )

    # -- statusjson --------------------------------------------------------
    async def _status_json(self, query: str, extra: dict | None = None) -> dict:
        params = {"query": query}
        if extra:
            params.update(extra)
        response = await self._request(
            "GET",
            f"{self.base_url}/cgi-bin/statusjson.cgi",
            params=params,
            auth=(self.user, self.password) if self.user else None,
        )
        return response.json().get("data", {})

    # -- livestatus --------------------------------------------------------
    async def _livestatus(self, query: str) -> list[list]:
        """Requête Livestatus sur socket TCP.

        Passe par un thread : Livestatus parle un protocole sur socket brut,
        et bloquer la boucle asyncio pendant qu'un Nagios lent répond
        gèlerait la collecte de TOUS les autres outils.
        """
        import json
        import socket

        def _query() -> list[list]:
            host = self.base_url.replace("http://", "").replace("https://", "").split(":")[0]
            with socket.create_connection((host, self.livestatus_port), timeout=self.timeout_s) as sock:
                sock.sendall((query + "OutputFormat: json\n\n").encode())
                sock.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            return json.loads(b"".join(chunks) or b"[]")

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailable(self.name, f"Livestatus : {exc}") from exc

    # -- contrat -----------------------------------------------------------
    async def check(self) -> ToolHealth:
        if self.mode == "unknown":
            return ToolHealth(tool=self.name, reachable=False, error=str(self._unconfigured()))

        async def probe():
            if self.mode == "statusjson":
                data = await self._status_json("programstatus")
                return (data.get("programstatus") or {}).get("version")
            if self.mode == "livestatus":
                rows = await self._livestatus("GET status\nColumns: program_version\n")
                return rows[0][0] if rows and rows[0] else None
            if self.mode == "xi":
                response = await self._request(
                    "GET",
                    f"{self.base_url}/nagiosxi/api/v1/system/status",
                    params={"apikey": self.password},
                )
                return (response.json() or {}).get("version")
            raise self._unconfigured()

        return await self._health(probe)

    async def fetch_nodes(self) -> list[Node]:
        if self.mode == "statusjson":
            data = await self._status_json("hostlist", {"details": "true"})
            return [
                Node(
                    tool=self.name,
                    ref=name,
                    name=name,
                    ip=host.get("address"),
                    state=_HOST_STATE.get(host.get("status"), "unknown"),
                )
                for name, host in (data.get("hostlist") or {}).items()
            ]
        if self.mode == "livestatus":
            rows = await self._livestatus(
                "GET hosts\nColumns: name address state\n"
            )
            return [
                Node(
                    tool=self.name,
                    ref=row[0],
                    name=row[0],
                    ip=row[1] or None,
                    # Livestatus code l'état autrement que les CGI :
                    # 0 UP, 1 DOWN, 2 UNREACHABLE.
                    state={0: "up", 1: "down", 2: "degraded"}.get(row[2], "unknown"),
                )
                for row in rows
            ]
        return []

    async def fetch_alerts(self) -> list[Alert]:
        if self.mode == "statusjson":
            data = await self._status_json("servicelist", {"details": "true"})
            alerts: list[Alert] = []
            for host_name, services in (data.get("servicelist") or {}).items():
                for service_name, service in services.items():
                    sev = _SERVICE_SEVERITY.get(service.get("status"))
                    if sev is None:  # OK ou PENDING : rien à signaler
                        continue
                    alerts.append(
                        Alert(
                            tool=self.name,
                            ref=f"{host_name}/{service_name}",
                            severity=sev,
                            message=service.get("plugin_output") or service_name,
                            since=epoch_to_dt(
                                (service.get("last_state_change") or 0) // 1000
                            ),
                            node_ref=host_name,
                            node_name=host_name,
                            acknowledged=bool(service.get("problem_has_been_acknowledged")),
                        )
                    )
            return [a for a in alerts if a.since is not None]
        if self.mode == "livestatus":
            rows = await self._livestatus(
                "GET services\nColumns: host_name description state plugin_output "
                "last_state_change acknowledged\nFilter: state != 0\n"
            )
            return [
                Alert(
                    tool=self.name,
                    ref=f"{row[0]}/{row[1]}",
                    severity={1: "medium", 2: "critical", 3: "unknown"}.get(row[2], "unknown"),
                    message=row[3] or row[1],
                    since=epoch_to_dt(row[4]),
                    node_ref=row[0],
                    node_name=row[0],
                    acknowledged=bool(row[5]),
                )
                for row in rows
                if epoch_to_dt(row[4]) is not None
            ]
        return []
