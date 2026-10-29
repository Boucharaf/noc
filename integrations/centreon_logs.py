"""
Connecteur Centreon — rejeu d'un export du journal `centreon_storage.logs`.

VISUALISATION LOCALE UNIQUEMENT. En production, Centreon est lu par son API
(integrations/centreon.py). Ce connecteur sert à voir dans le NOC un export
du journal de Centreon fourni par l'agence (database/alertes.sql), comme la
base NetXMS restaurée sert à voir le dump NetXMS. Le choix se fait par la
forme de CENTREON_API_URL (integrations/config.py) :

    https://…           → API REST v2, centreon.py (production)
    file:///chemin      → ce fichier (export du journal, local)

Les deux rendent les mêmes `Node` et `Alert`, avec les mêmes références
(`host-<id>`, `service-<id>`) : rien au-delà de `integrations/` ne sait
lequel tourne.

FORMAT ATTENDU. Un export tabulé de la table `logs`, en-tête compris (ce que
produit `mysql -e "SELECT * FROM logs …"`) : log_id, ctime, host_id,
host_name, msg_type, output, service_description, service_id, status, type…

CE QUE LE JOURNAL PERMET, ET CE QU'IL NE PERMET PAS. Centreon y écrit les
CHANGEMENTS d'état et les résultats de contrôle qu'il journalise ; le dernier
état de chaque hôte et de chaque service s'en déduit en le rejouant dans
l'ordre. Le journal ne contient en revanche ni l'adresse des hôtes (elle est
lue, quand elle y figure, dans la sortie du contrôle de l'hôte : « OK -
10.165.22.35 rta 1,3 ms »), ni leurs groupes, donc ni site ni région, ni
aucune mesure de performance (`fetch_history` reste vide). L'état affiché
est celui de la FIN de l'export, figé : le NOC le montre tel quel.
"""
from __future__ import annotations

import csv
import ipaddress
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlsplit

from .base import SourceClient, ToolUnavailable
from .centreon import _host_state
from .models import Alert, Node, ToolHealth
from .normalize import epoch_to_dt, severity, source_severity

logger = logging.getLogger(__name__)

# Types de message du journal Centreon (colonne msg_type).
_SERVICE_STATE = {"0", "6", "8"}   # SERVICE ALERT, CURRENT / INITIAL SERVICE STATE
_HOST_STATE = {"1", "7", "9"}      # HOST ALERT, CURRENT / INITIAL HOST STATE
_SERVICE_ACK = "10"
_HOST_ACK = "11"
# Colonne `type` : 0 SOFT (état non confirmé, contrôle en cours de
# re-vérification), 1 HARD (état confirmé). Seul un état HARD fait une
# alerte, comme sur l'écran de Centreon.
_SOFT = "0"

_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_REQUIRED = {"ctime", "host_id", "host_name", "msg_type", "output",
             "service_description", "service_id", "status", "type"}


@dataclass
class _Check:
    """Dernier état HARD d'un hôte ou d'un service, rejoué depuis le journal."""

    name: str
    status: int = 0
    since: datetime | None = None   # début de l'état en cours
    output: str = ""
    acknowledged_at: datetime | None = None
    seen_at: datetime | None = None


@dataclass
class _Host(_Check):
    ip: str | None = None
    has_host_state: bool = False
    services: dict[str, _Check] = field(default_factory=dict)


def _ip_in(output: str) -> str | None:
    for candidate in _IPV4.findall(output or ""):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not (address.is_loopback or address.is_unspecified):
            return candidate
    return None


def _apply(check: _Check, status: int, at: datetime, output: str) -> None:
    """Un état HARD : il ne date l'état en cours que s'il en change."""
    if check.since is None or status != check.status:
        check.since = at
        check.acknowledged_at = None  # un acquittement ne survit pas au changement
    check.status = status
    check.output = output


class CentreonLogClient(SourceClient):
    name = "centreon"

    def __init__(self, url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 20.0):
        super().__init__(url, user, password, verify_ssl, timeout_s)
        parts = urlsplit(url)
        # file:///srv/dumps/alertes.sql, ou file:///C:/… sous Windows (hors
        # Docker) : la barre devant la lettre de lecteur n'appartient pas au
        # chemin.
        path = unquote(parts.netloc + parts.path)
        self.path = path[1:] if re.match(r"^/[A-Za-z]:/", path) else path
        self._cache: tuple[tuple[float, int], dict[str, _Host], dict] | None = None

    # -- lecture ---------------------------------------------------------------
    def _replay(self) -> tuple[dict[str, _Host], dict]:
        """Rejoue le journal ; relu seulement si le fichier a changé."""
        try:
            stat = os.stat(self.path)
        except OSError as exc:
            raise ToolUnavailable(self.name, f"export introuvable : {self.path}") from exc
        signature = (stat.st_mtime, stat.st_size)
        if self._cache and self._cache[0] == signature:
            return self._cache[1], self._cache[2]

        csv.field_size_limit(10**8)
        try:
            with open(self.path, encoding="utf8", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
                missing = _REQUIRED - set(reader.fieldnames or ())
                if missing:
                    raise ToolUnavailable(
                        self.name,
                        "ce n'est pas un export de centreon_storage.logs "
                        f"(colonnes absentes : {', '.join(sorted(missing))})",
                    )
                rows = [row for row in reader if (row.get("ctime") or "").isdigit()]
        except OSError as exc:
            raise ToolUnavailable(self.name, f"export illisible : {exc}") from exc

        rows.sort(key=lambda row: (int(row["ctime"]), int(row.get("log_id") or 0)
                                   if str(row.get("log_id") or "").isdigit() else 0))
        hosts: dict[str, _Host] = {}
        for row in rows:
            host_id = (row.get("host_id") or "").strip()
            if not host_id or host_id in ("0", "NULL"):
                continue  # messages du moteur (configuration, notifications)
            at = epoch_to_dt(row["ctime"])
            host = hosts.setdefault(host_id, _Host(name=row.get("host_name") or host_id))
            host.name = row.get("host_name") or host.name
            host.seen_at = at
            msg_type = row.get("msg_type")
            try:
                status = int(row.get("status") or 0)
            except ValueError:
                continue
            output = row.get("output") or ""
            service_id = (row.get("service_id") or "").strip()

            if msg_type in _HOST_STATE:
                host.ip = _ip_in(output) or host.ip
                if row.get("type") != _SOFT:
                    _apply(host, status, at, output)
                    host.has_host_state = True
            elif msg_type in _SERVICE_STATE and service_id not in ("", "0", "NULL"):
                service = host.services.setdefault(
                    service_id, _Check(name=row.get("service_description") or service_id)
                )
                service.seen_at = at
                if "ping" in service.name.lower():
                    host.ip = host.ip or _ip_in(output)
                if row.get("type") != _SOFT:
                    _apply(service, status, at, output)
            elif msg_type == _HOST_ACK and host.status:
                host.acknowledged_at = host.acknowledged_at or at
            elif msg_type == _SERVICE_ACK and service_id in host.services:
                service = host.services[service_id]
                if service.status:
                    service.acknowledged_at = service.acknowledged_at or at

        meta = {
            "rows": len(rows),
            "first": epoch_to_dt(rows[0]["ctime"]) if rows else None,
            "last": epoch_to_dt(rows[-1]["ctime"]) if rows else None,
        }
        self._cache = (signature, hosts, meta)
        return hosts, meta

    # -- contrat ---------------------------------------------------------------
    async def check(self) -> ToolHealth:
        async def probe():
            _hosts, meta = self._replay()
            if not meta["rows"]:
                raise ToolUnavailable(self.name, "export vide")
            return (
                f"export du journal, {meta['rows']} lignes, "
                f"du {meta['first']:%d/%m/%Y} au {meta['last']:%d/%m/%Y %H:%M} UTC"
            )

        return await self._health(probe)

    @staticmethod
    def _state(host: _Host) -> str:
        """État de l'hôte à la fin de l'export.

        Le contrôle de l'hôte d'abord. Centreon ne journalise que ses
        CHANGEMENTS : un hôte resté joignable toute la période n'a souvent
        aucune ligne d'hôte. Son état se lit alors sur ses services — tous
        nominaux : « up » ; l'un critique : « dégradé » ; sinon « inconnu ».
        """
        if host.has_host_state:
            return _host_state(host.status, False, "host")
        statuses = {service.status for service in host.services.values()}
        if not statuses:
            return "unknown"
        if statuses == {0}:
            return "up"
        if 2 in statuses or 1 in statuses:
            return "degraded"
        return "unknown"

    async def fetch_nodes(self) -> list[Node]:
        hosts, _meta = self._replay()
        return [
            Node(
                tool=self.name,
                ref=f"host-{host_id}",
                name=host.name,
                hostname=host.name,
                ip=host.ip,
                state=self._state(host),
                node_type="host",
            )
            for host_id, host in sorted(hosts.items())
        ]

    async def fetch_alerts(self) -> list[Alert]:
        hosts, _meta = self._replay()
        alerts: list[Alert] = []
        for host_id, host in sorted(hosts.items()):
            checks = [("host", host_id, host, "centreon_host")] if host.has_host_state else []
            checks += [
                ("service", service_id, service, "centreon_service")
                for service_id, service in sorted(host.services.items())
            ]
            for kind, ref, check, scale in checks:
                if not check.status or check.since is None:
                    continue
                label = check.output or check.name
                alerts.append(
                    Alert(
                        tool=self.name,
                        ref=f"{kind}-{ref}",
                        severity=severity(scale, check.status),
                        source_severity=source_severity(scale, check.status),
                        message=label if kind == "host" else f"{check.name} : {label}",
                        since=check.since,
                        node_ref=f"host-{host_id}",
                        node_name=host.name,
                        acknowledged=check.acknowledged_at is not None,
                        acknowledged_at=check.acknowledged_at,
                    )
                )
        return alerts
