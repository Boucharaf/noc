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

import logging
import os

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import iso_to_dt, severity

logger = logging.getLogger(__name__)


class NSPClient(SourceClient):
    name = "nsp"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 30.0):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        self.mode = os.getenv("NSP_FM_MODE", "unknown").strip().lower()
        self._token: str | None = None

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
            # classique, NSP ne fournit que des alarmes. Les équipements
            # apparaîtront par leurs alarmes, ce qui est incomplet mais
            # honnête — plutôt qu'un inventaire reconstitué au jugé.
            return []
        body = await self._get(
            "/restconf/data/nsp-equipment:network/network-element"
        )
        elements = (
            body.get("nsp-equipment:network-element")
            or body.get("network-element")
            or []
        )
        return [
            Node(
                tool=self.name,
                ref=str(ne.get("ne-id") or ne.get("id")),
                name=ne.get("ne-name") or ne.get("name") or "(sans nom)",
                ip=ne.get("ip-address"),
                state={"in-service": "up", "out-of-service": "down"}.get(
                    str(ne.get("communication-state", "")).lower(), "unknown"
                ),
                node_type=ne.get("ne-type"),
            )
            for ne in elements
        ]

    async def fetch_alerts(self) -> list[Alert]:
        if self.mode == "yang":
            body = await self._get("/restconf/data/nsp-fault:alarms/alarm-list")
            raw = body.get("nsp-fault:alarm-list") or body.get("alarm-list") or []
        elif self.mode == "classic":
            body = await self._get("/nbi-fm/api/v1/fm/alarms")
            raw = (body.get("response") or {}).get("data") or body.get("data") or []
        else:
            raise self._unconfigured()

        alerts: list[Alert] = []
        for alarm in raw:
            # NSP conserve les alarmes acquittées ET terminées dans la même
            # liste : seules celles qui ne sont pas effacées sont actives.
            if str(alarm.get("severity", "")).lower() == "cleared":
                continue
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(alarm.get("alarm-id") or alarm.get("id")),
                    severity=severity("nsp", alarm.get("severity")),
                    message=alarm.get("additional-text")
                    or alarm.get("alarm-name")
                    or "(sans libellé)",
                    since=iso_to_dt(
                        alarm.get("first-time-detected") or alarm.get("timeStamp")
                    ),
                    node_ref=str(alarm.get("ne-id") or "") or None,
                    node_name=alarm.get("ne-name"),
                    acknowledged=bool(alarm.get("acknowledged")),
                    acknowledged_at=iso_to_dt(alarm.get("acknowledged-time")),
                )
            )
        return [a for a in alerts if a.since is not None]
