"""
Connecteur Nokia NSP (réseau de transport) — deux modes de gestion de fautes.

Nokia fait cohabiter deux interfaces de Fault Management, et le choix dépend
de la version déployée :

    yang     — RESTCONF sur le modèle YANG `nsp-fault`. C'est la voie que
               Nokia recommande pour toute nouvelle intégration.
    classic  — API NBI historique `/nbi-fm/api/v1/fm/alarms`, en dépréciation.

`NSP_FM_MODE` tranche. Tant qu'il vaut `unknown`, le connecteur se déclare
non joignable en NOMMANT la variable à renseigner, plutôt que de laisser
croire à une panne réseau.

AUTHENTIFICATION. Jeton Bearer d'une durée de vie d'environ soixante minutes,
obtenu par Basic Auth sur la passerelle REST. Il est renouvelé sur 401 plutôt
qu'à échéance calculée : parier sur une durée que l'exploitant peut
reconfigurer produit des collectes qui échouent sans raison visible.

HORS PÉRIMÈTRE DU LABORATOIRE LOCAL : Nokia ne distribue pas NSP publiquement,
il n'existe aucun moyen de le monter en conteneur. Ce connecteur s'activera
sur l'instance de l'agence.
"""
from __future__ import annotations

import os

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import epoch_to_dt, iso_to_dt, severity, source_severity


class NSPClient(SourceClient):
    name = "nsp"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 30.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        self.mode = os.getenv("NSP_FM_MODE", "unknown").strip().lower()
        self._token: str | None = None
        self.collection_warnings: list[str] = []

    def _unconfigured(self) -> ToolUnavailable:
        return ToolUnavailable(
            self.name, "NSP_FM_MODE non renseigné — valeurs acceptées : yang, classic"
        )

    async def _login(self) -> str:
        response = await self._request(
            "POST",
            f"{self.base_url}/rest-gateway/rest/api/v1/auth/token",
            json={"grant_type": "client_credentials"},
            auth=(self.user, self.password),
        )
        body = response.json()
        token = body.get("access_token") or (body.get("response") or {}).get("access_token")
        if not token:
            raise ToolUnavailable(self.name, "réponse d'authentification sans access_token")
        self._token = token
        return token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if self._token is None:
            await self._login()
        try:
            response = await self._request(
                "GET",
                f"{self.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except ToolUnavailable as exc:
            if "HTTP 401" not in str(exc):
                raise
            await self._login()
            response = await self._request(
                "GET",
                f"{self.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        return response.json()

    async def check(self) -> ToolHealth:
        if self.mode == "unknown":
            return ToolHealth(tool=self.name, reachable=False, error=str(self._unconfigured()))

        async def probe():
            await self._login()
            return None

        return await self._health(probe)

    async def fetch_nodes(self) -> list[Node]:
        if self.mode != "yang":
            # L'API historique n'expose pas d'inventaire exploitable : en mode
            # classique, NSP ne fournit que des alarmes. Signaler la limite
            # évite de présenter l'intégration comme une couverture complète.
            self.collection_warnings.append(
                "mode NSP classic : inventaire des équipements non disponible"
            )
            return []
        body = await self._get(
            "/restconf/data/nsp-equipment:network/network-element"
        )
        nodes = []
        for ne in _records(body, "network-element"):
            ref = _field(ne, "ne-id", "neId", "id")
            if ref is None:
                raise ToolUnavailable(self.name, "équipement NSP sans identifiant")
            name = _field(ne, "ne-name", "neName", "name") or "(sans nom)"
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(ref),
                    name=name,
                    hostname=name,
                    ip=_field(ne, "ip-address", "ipAddress", "management-ip"),
                    state=_ne_state(ne),
                    node_type=_field(ne, "ne-type", "neType", "product"),
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        if self.mode == "yang":
            body = await self._get("/restconf/data/nsp-fault:alarms/alarm-list")
            raw = _records(body, "alarm-list", "alarm")
        elif self.mode == "classic":
            body = await self._get("/nbi-fm/api/v1/fm/alarms")
            raw = _records(body, "alarms", "alarm")
        else:
            raise self._unconfigured()

        alerts: list[Alert] = []
        for alarm in raw:
            # NSP conserve les alarmes acquittées ET terminées dans la même
            # liste : seules celles qui ne sont pas effacées sont actives.
            raw_severity = str(_field(alarm, "severity", "perceivedSeverity") or "").lower()
            if raw_severity == "cleared" or _field(alarm, "is-cleared", "isCleared") is True:
                continue
            # L'identifiant d'une alarme NSP est son FDN ; `alarm-id` n'existe
            # que sur certaines versions.
            ref = _field(alarm, "alarm-fdn", "alarmFdn", "fdn", "alarm-id", "alarmId", "id")
            if ref is None:
                raise ToolUnavailable(self.name, "alarme NSP sans identifiant")
            since = _when(
                _field(
                    alarm,
                    "first-time-detected", "firstTimeDetected",
                    "last-time-detected", "lastTimeDetected", "timeStamp",
                )
            )
            if since is None:
                raise ToolUnavailable(
                    self.name, f"alarme {ref} sans date de détection valide"
                )
            ne_id = _field(alarm, "ne-id", "neId")
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(ref),
                    severity=severity("nsp", raw_severity),
                    source_severity=source_severity("nsp", raw_severity),
                    message=_field(
                        alarm, "additional-text", "additionalText", "alarm-name", "alarmName"
                    )
                    or "(sans libellé)",
                    since=since,
                    node_ref=str(ne_id) if ne_id not in (None, "") else None,
                    node_name=_field(alarm, "ne-name", "neName"),
                    acknowledged=_truthy(
                        _field(alarm, "acknowledged", "isAcknowledged", "acknowledgement-state")
                    ),
                    acknowledged_at=_when(
                        _field(alarm, "acknowledged-time", "acknowledgedTime")
                    ),
                )
            )
        return alerts


def _records(body, *keys: str) -> list[dict]:
    """Liste d'enregistrements, quel que soit l'emballage de la réponse.

    RESTCONF préfixe la racine par le module (`nsp-fault:alarm-list`) et
    enveloppe la liste dans un conteneur (`{"alarm": [...]}`) ; l'API
    historique la place sous `response.data`. Itérer directement sur un
    conteneur parcourrait ses CLÉS, d'où cette normalisation.
    """
    value = body
    for _ in range(4):
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not isinstance(value, dict):
            return []
        for wrapper in ("response", "data"):
            if wrapper in value and not any(k in value for k in keys):
                value = value[wrapper]
                break
        else:
            found = None
            for key, item in value.items():
                if key.split(":", 1)[-1] in keys:
                    found = item
                    break
            if found is None:
                return []
            value = found
    return []


def _field(record: dict, *names: str):
    """Premier champ présent, avec ou sans préfixe de module YANG."""
    unprefixed = {key.split(":", 1)[-1]: value for key, value in record.items()}
    for name in names:
        value = unprefixed.get(name)
        if value not in (None, ""):
            return value
    return None


def _when(value):
    """Horodatage NSP : ISO 8601 (RESTCONF) ou millisecondes UNIX (NBI)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        return epoch_to_dt(int(value) // 1000 if int(value) > 10**11 else int(value))
    return iso_to_dt(value)


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "acknowledged")
    return bool(value)


def _ne_state(ne: dict) -> str:
    for name in ("communication-state", "communicationState", "operational-state", "operState"):
        raw = _field(ne, name)
        if raw is None:
            continue
        state = str(raw).strip().lower()
        if state in ("up", "reachable", "in-service", "enabled", "available"):
            return "up"
        if state in ("down", "unreachable", "out-of-service", "disabled", "failed"):
            return "down"
        if state in ("degraded", "partially-reachable"):
            return "degraded"
    return "unknown"
