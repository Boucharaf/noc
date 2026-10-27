"""
Connecteur Nagios — le mode dépend de ce qui est réellement déployé.

Nagios Core n'a pas d'API REST. Trois déploiements possibles, choisis par
`NAGIOS_MODE` :

    statusjson  — Nagios Core 4.x, CGI `statusjson.cgi` / `objectjson.cgi`
                  livrés en standard. C'est le cas le plus fréquent et le seul
                  qui ne demande aucune installation supplémentaire.
                  NAGIOS_API_URL désigne la racine web (http://hôte/nagios) :
                  les CGI sont cherchés sous <URL>/cgi-bin/.
    livestatus  — module MK Livestatus (socket TCP, requêtes façon SQL).
                  Port : celui de l'URL, sinon NAGIOS_LIVESTATUS_PORT (6557).
    xi          — Nagios XI, API REST sous /nagiosxi/api/v1 (offre payante).

Tant que `NAGIOS_MODE` vaut `unknown`, le connecteur se déclare non joignable
avec un message qui NOMME la variable à renseigner. C'est délibéré : une
intégration non configurée doit se voir sur l'écran Interopérabilité, pas se
faire passer pour un outil en panne ni pour un outil sain sans données.

CODES D'ÉTAT. Les CGI JSON n'emploient PAS les codes de retour des sondes
(0 OK, 1 WARNING…) : ils exposent des MASQUES DE BITS, définis dans
cgi/statusdata.h de Nagios Core —

    hôte     1 PENDING, 2 UP, 4 DOWN, 8 UNREACHABLE
    service  1 PENDING, 2 OK, 4 WARNING, 8 UNKNOWN, 16 CRITICAL

Livestatus, lui, rend les codes de retour classiques. Confondre les deux
fait lire chaque hôte UP comme « en panne » et chaque service OK comme une
alerte : les deux tables sont donc tenues séparément.

Laboratoire local : `docker compose --profile nagios up -d` (Nagios Core
4.5, voir docker-compose.yml).
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import epoch_to_dt, locality_from_groups

logger = logging.getLogger(__name__)

# --- statusjson.cgi (masques de bits) --------------------------------------
_JSON_HOST_STATE = {1: "silent", 2: "up", 4: "down", 8: "degraded"}
_JSON_HOST_SEVERITY = {4: "critical", 8: "high"}
_JSON_SERVICE_SEVERITY = {4: "medium", 8: "unknown", 16: "critical"}
# Libellés d'origine Nagios, en clair (DOWN, UNREACHABLE, WARNING…).
_JSON_HOST_LABEL = {4: "Hôte arrêté", 8: "Hôte injoignable"}
_JSON_SERVICE_LABEL = {4: "Avertissement", 8: "Inconnu", 16: "Critique"}
_LS_HOST_LABEL = {1: "Hôte arrêté", 2: "Hôte injoignable"}
_LS_SERVICE_LABEL = {1: "Avertissement", 2: "Critique", 3: "Inconnu"}

# --- Livestatus (codes de retour) ------------------------------------------
_LS_HOST_STATE = {0: "up", 1: "down", 2: "degraded"}
_LS_HOST_SEVERITY = {1: "critical", 2: "high"}
_LS_SERVICE_SEVERITY = {1: "medium", 2: "critical", 3: "unknown"}

# Même correspondance que Centreon (integrations/normalize.py) : un hôte DOWN
# est critique, un hôte UNREACHABLE — panne en amont — est « high ».


def _site_from_groups(groups) -> str | None:
    """Même convention que Zabbix et Centreon : un groupe « Site/<nom> »."""
    for group in groups:
        name = str(group)
        for prefix in ("site/", "localité/", "localite/", "site:"):
            if name.lower().startswith(prefix):
                return name.split("/", 1)[-1].split(":", 1)[-1].strip() or None
    return None


def _json_since(record: dict):
    """Date de début d'un problème, en millisecondes chez les CGI JSON.

    `last_state_change` vaut 0 pour un objet resté dans le même état depuis
    le démarrage de Nagios : on retombe alors sur le dernier changement
    d'état ferme, puis sur le dernier contrôle, plutôt que d'écarter toute la
    collecte pour une seule alerte.
    """
    for field in ("last_state_change", "last_hard_state_change", "last_check"):
        value = record.get(field)
        if value:
            stamp = epoch_to_dt(int(value) // 1000)
            if stamp is not None:
                return stamp
    return None


class NagiosClient(SourceClient):
    name = "nagios"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 20.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        self.mode = os.getenv("NAGIOS_MODE", "unknown").strip().lower()
        self.collection_warnings: list[str] = []
        parts = urlsplit(self.base_url if "://" in self.base_url else f"tcp://{self.base_url}")
        self.livestatus_host = parts.hostname or ""
        self.livestatus_port = parts.port or int(os.getenv("NAGIOS_LIVESTATUS_PORT", "6557"))

    def _unconfigured(self) -> ToolUnavailable:
        return ToolUnavailable(
            self.name,
            "NAGIOS_MODE non renseigné — valeurs acceptées : "
            "statusjson, livestatus, xi",
        )

    def _xi_not_implemented(self) -> ToolUnavailable:
        return ToolUnavailable(
            self.name,
            "le mode Nagios XI n'est pas implémenté; choisir statusjson ou livestatus "
            "pour éviter une collecte vide",
        )

    # -- statusjson / objectjson ------------------------------------------
    async def _cgi(self, cgi: str, query: str, extra: dict | None = None) -> dict:
        params = {"query": query}
        if extra:
            params.update(extra)
        response = await self._request(
            "GET",
            f"{self.base_url}/cgi-bin/{cgi}",
            params=params,
            auth=(self.user, self.password) if self.user else None,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise ToolUnavailable(
                self.name, f"{cgi} : réponse non-JSON (NAGIOS_API_URL erronée ?)"
            ) from exc
        result = body.get("result") or {}
        # Les CGI répondent HTTP 200 même en erreur : le verdict est dans
        # result.type_code (0 = succès), par exemple pour un compte qui n'a
        # pas les droits « authorized_for_all_hosts ».
        if result.get("type_code") not in (None, 0):
            verdict = result.get("type_text") or "erreur"
            raise ToolUnavailable(
                self.name, f"{cgi} : {verdict} — {result.get('message', '')}".strip()
            )
        return body.get("data") or {}

    async def _optional_objects(self, query: str, label: str) -> dict:
        """Configuration des objets — complément de l'état, pas l'essentiel.

        `objectjson.cgi` de Nagios Core plante (« buffer overflow detected »,
        HTTP 500) dès qu'un objet porte un caractère non ASCII dans son alias
        — constaté sur 4.5.12 avec « é » et « — ». L'état des hôtes, lu par
        statusjson, reste juste : on le publie sans adresses ni groupes et on
        le SIGNALE, plutôt que de perdre tout l'inventaire Nagios.
        """
        try:
            data = await self._cgi("objectjson.cgi", query, {"details": "true"})
        except ToolUnavailable as exc:
            warning = f"objectjson.cgi indisponible ({exc}) : {label} non collectés"
            self.collection_warnings.append(warning)
            logger.warning("nagios : %s", warning)
            return {}
        return data.get(query) or {}

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
            with socket.create_connection(
                (self.livestatus_host, self.livestatus_port), timeout=self.timeout_s
            ) as sock:
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
                data = await self._cgi("statusjson.cgi", "programstatus")
                return (data.get("programstatus") or {}).get("version")
            if self.mode == "livestatus":
                rows = await self._livestatus("GET status\nColumns: program_version\n")
                return rows[0][0] if rows and rows[0] else None
            if self.mode == "xi":
                raise self._xi_not_implemented()
            raise self._unconfigured()

        return await self._health(probe)

    async def fetch_nodes(self) -> list[Node]:
        if self.mode == "statusjson":
            status = await self._cgi("statusjson.cgi", "hostlist", {"details": "true"})
            # statusjson ne porte pas l'adresse : elle vient de la
            # configuration des objets, tout comme les groupes d'hôtes.
            definitions = await self._optional_objects("hostlist", "adresses et alias")
            groups_by_host: dict[str, list[str]] = {}
            for name, group in (
                await self._optional_objects("hostgrouplist", "groupes d'hôtes (sites)")
            ).items():
                for member in group.get("members") or []:
                    groups_by_host.setdefault(member, []).append(name)
            nodes = []
            for name, host in (status.get("hostlist") or {}).items():
                definition = definitions.get(name) or {}
                groups = tuple(sorted(groups_by_host.get(name, ())))
                in_downtime = int(host.get("scheduled_downtime_depth") or 0) > 0
                nodes.append(
                    Node(
                        tool=self.name,
                        ref=name,
                        name=definition.get("alias") or name,
                        hostname=name,
                        ip=definition.get("address") or None,
                        state=(
                            "maintenance"
                            if in_downtime
                            else _JSON_HOST_STATE.get(host.get("status"), "unknown")
                        ),
                        # Pas de filtre sur checks_enabled : un hôte en
                        # contrôles PASSIFS a ses contrôles actifs coupés et
                        # reste pourtant supervisé.
                        groups=groups,
                        site=_site_from_groups(groups),
                        province=locality_from_groups(groups)["province"],
                        region=locality_from_groups(groups)["region"],
                    )
                )
            return nodes
        if self.mode == "livestatus":
            rows = await self._livestatus(
                "GET hosts\nColumns: name alias address state has_been_checked "
                "scheduled_downtime_depth groups\n"
            )
            nodes = []
            for name, alias, address, state, checked, downtime, groups in rows:
                groups = tuple(sorted(groups or ()))
                nodes.append(
                    Node(
                        tool=self.name,
                        ref=name,
                        name=alias or name,
                        hostname=name,
                        ip=address or None,
                        state=(
                            "maintenance"
                            if downtime
                            else "silent"
                            if not checked
                            else _LS_HOST_STATE.get(state, "unknown")
                        ),
                        groups=groups,
                        site=_site_from_groups(groups),
                        province=locality_from_groups(groups)["province"],
                        region=locality_from_groups(groups)["region"],
                    )
                )
            return nodes
        if self.mode == "xi":
            raise self._xi_not_implemented()
        raise self._unconfigured()

    async def fetch_alerts(self) -> list[Alert]:
        if self.mode == "statusjson":
            return await self._statusjson_alerts()
        if self.mode == "livestatus":
            return await self._livestatus_alerts()
        if self.mode == "xi":
            raise self._xi_not_implemented()
        raise self._unconfigured()

    async def _statusjson_alerts(self) -> list[Alert]:
        hosts = await self._cgi("statusjson.cgi", "hostlist", {"details": "true"})
        services = await self._cgi("statusjson.cgi", "servicelist", {"details": "true"})
        alerts: list[Alert] = []

        # Hôtes DOWN / UNREACHABLE : sans eux, un équipement tombé ne
        # remonterait que par les services de ses voisins.
        for host_name, host in (hosts.get("hostlist") or {}).items():
            sev = _JSON_HOST_SEVERITY.get(host.get("status"))
            if sev is None:
                continue
            alerts.append(
                self._alert(
                    ref=host_name,
                    host_name=host_name,
                    severity=sev,
                    source_severity=_JSON_HOST_LABEL.get(host.get("status")),
                    message=host.get("plugin_output") or "hôte injoignable",
                    since=_json_since(host),
                    acknowledged=bool(host.get("problem_has_been_acknowledged")),
                )
            )

        for host_name, host_services in (services.get("servicelist") or {}).items():
            for service_name, service in host_services.items():
                sev = _JSON_SERVICE_SEVERITY.get(service.get("status"))
                if sev is None:  # OK ou PENDING : rien à signaler
                    continue
                alerts.append(
                    self._alert(
                        ref=f"{host_name}/{service_name}",
                        host_name=host_name,
                        severity=sev,
                        source_severity=_JSON_SERVICE_LABEL.get(service.get("status")),
                        message=service.get("plugin_output") or service_name,
                        since=_json_since(service),
                        acknowledged=bool(service.get("problem_has_been_acknowledged")),
                    )
                )
        return alerts

    async def _livestatus_alerts(self) -> list[Alert]:
        hosts = await self._livestatus(
            "GET hosts\nColumns: name state plugin_output last_state_change "
            "acknowledged\nFilter: state != 0\nFilter: has_been_checked = 1\n"
        )
        services = await self._livestatus(
            "GET services\nColumns: host_name description state plugin_output "
            "last_state_change acknowledged\nFilter: state != 0\n"
            "Filter: has_been_checked = 1\n"
        )
        alerts: list[Alert] = []
        for name, state, output, changed, acknowledged in hosts:
            sev = _LS_HOST_SEVERITY.get(state)
            if sev is None:
                continue
            alerts.append(
                self._alert(
                    ref=name,
                    host_name=name,
                    severity=sev,
                    source_severity=_LS_HOST_LABEL.get(state),
                    message=output or "hôte injoignable",
                    since=epoch_to_dt(changed),
                    acknowledged=bool(acknowledged),
                )
            )
        for host_name, description, state, output, changed, acknowledged in services:
            alerts.append(
                self._alert(
                    ref=f"{host_name}/{description}",
                    host_name=host_name,
                    severity=_LS_SERVICE_SEVERITY.get(state, "unknown"),
                    source_severity=_LS_SERVICE_LABEL.get(state),
                    message=output or description,
                    since=epoch_to_dt(changed),
                    acknowledged=bool(acknowledged),
                )
            )
        return alerts

    def _alert(self, *, ref, host_name, severity, message, since, acknowledged,
               source_severity=None) -> Alert:
        if since is None:
            raise ToolUnavailable(
                self.name, f"alerte {ref} sans date de changement valide"
            )
        return Alert(
            tool=self.name,
            ref=ref,
            severity=severity,
            source_severity=source_severity,
            message=message,
            since=since,
            node_ref=host_name,
            node_name=host_name,
            acknowledged=acknowledged,
        )
