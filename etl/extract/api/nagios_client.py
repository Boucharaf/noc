"""
Connecteur Nagios — EN ATTENTE DE CONFIRMATION (voir README de ce dossier).

Nagios Core n'a pas d'API REST native. Trois variantes possibles selon ce
qui est réellement déployé chez l'agence, sélectionnées par
`settings.nagios_mode` :

    "livestatus" -> module MK Livestatus (socket Unix/TCP, requêtes façon SQL)
    "xi"         -> Nagios XI REST API (/nagiosxi/api/v1/...), licence commerciale
    "ndoutils"   -> pas une API : export vers MySQL -> voir extract/db/nagios_db_reader.py
    "unknown"    -> health_check() renvoie False, fetch_* renvoient des listes vides
                    (ne bloque jamais le reste du pipeline)

Ce fichier fournit une implémentation fonctionnelle pour "livestatus" et
"xi" ; il suffira de fixer NAGIOS_MODE dans la config une fois la réponse
de l'agence connue. Si la réponse est "ndoutils", ce connecteur API reste
inactif et tout passe par extract/db/nagios_db_reader.py.
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Optional

from .common import ToolUnavailableError, build_session


class NagiosClient:
    def __init__(
        self,
        mode: str,
        base_url: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        livestatus_host: Optional[str] = None,
        livestatus_port: int = 6557,
        verify_ssl: bool = True,
    ):
        self.mode = mode
        self.base_url = (base_url or "").rstrip("/")
        self.user = user
        self.password = password
        self.livestatus_host = livestatus_host
        self.livestatus_port = livestatus_port
        self.session = build_session(verify_ssl) if mode == "xi" else None

    # -- health -----------------------------------------------------
    def health_check(self) -> bool:
        if self.mode == "livestatus":
            try:
                self._livestatus_query("GET status\nColumns: program_version\n")
                return True
            except ToolUnavailableError:
                return False
        if self.mode == "xi":
            try:
                self._xi_get("/system/status")
                return True
            except ToolUnavailableError:
                return False
        return False  # mode "unknown" ou "ndoutils" -> connecteur API inactif

    # -- MK Livestatus ------------------------------------------------
    def _livestatus_query(self, query: str) -> list[list[str]]:
        try:
            sock = socket.create_connection((self.livestatus_host, self.livestatus_port), timeout=10)
            sock.sendall(query.encode() + b"OutputFormat: json\n\n")
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            sock.close()
        except OSError as exc:
            raise ToolUnavailableError(f"Livestatus injoignable: {exc}") from exc
        import json

        raw = b"".join(chunks).decode(errors="replace").strip()
        return json.loads(raw) if raw else []

    # -- Nagios XI REST -------------------------------------------------
    def _xi_get(self, path: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["apikey"] = self.password  # Nagios XI utilise une clé API, pas user/password
        try:
            resp = self.session.get(f"{self.base_url}/nagiosxi/api/v1{path}", params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"Nagios XI injoignable ({path}): {exc}") from exc

    # -- contrat commun --------------------------------------------------
    def fetch_nodes(self) -> list[dict]:
        if self.mode == "livestatus":
            rows = self._livestatus_query(
                "GET hosts\nColumns: name address state\n"
            )
            return [
                {"source_tool": "nagios", "external_ref": r[0], "name": r[0],
                 "ip_address": r[1], "is_active": True}
                for r in rows
            ]
        if self.mode == "xi":
            body = self._xi_get("/objects/host")
            return [
                {"source_tool": "nagios", "external_ref": h["host_name"], "name": h["host_name"],
                 "ip_address": h.get("address"), "is_active": True}
                for h in body.get("hosts", [])
            ]
        return []

    def fetch_incidents(self, since: datetime) -> list[dict]:
        if self.mode == "livestatus":
            rows = self._livestatus_query(
                "GET services\nColumns: host_name description state last_state_change acknowledged\n"
                "Filter: state != 0\n"
            )
            incidents = []
            for host, desc, state, changed, ack in rows:
                incidents.append(
                    {
                        "source_tool": "nagios",
                        "external_id": f"{host}-{desc}",
                        "node_external_ref": host,
                        "severity": int(state),
                        "detected_at": datetime.fromtimestamp(int(changed), tz=timezone.utc),
                        "acknowledged_at": (
                            datetime.now(timezone.utc) if str(ack) == "1" else None
                        ),
                        "resolved_at": None,
                        "description": desc,
                        "status": "open",
                    }
                )
            return incidents
        if self.mode == "xi":
            body = self._xi_get("/objects/servicestatus", params={"status": "warning,critical,unknown"})
            return [
                {
                    "source_tool": "nagios",
                    "external_id": f"{s['host_name']}-{s['service_description']}",
                    "node_external_ref": s["host_name"],
                    "severity": s.get("current_state"),
                    "detected_at": _epoch_to_dt(s.get("last_state_change")),
                    "acknowledged_at": None,
                    "resolved_at": None,
                    "description": s.get("plugin_output"),
                    "status": "open",
                }
                for s in body.get("servicestatus", [])
            ]
        return []

    def fetch_metrics(self, since: datetime) -> list[dict]:
        # Nagios Core natif n'expose pas de perfdata structurée par API :
        # à activer seulement si un module de perfdata (ex. PNP4Nagios,
        # exporté ailleurs) est confirmé côté agence.
        return []


def _epoch_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
