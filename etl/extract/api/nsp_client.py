"""
Connecteur Nokia NSP (backbone/transport) — EN ATTENTE DE CONFIRMATION
(voir README de ce dossier).

Deux inconnues à lever côté agence avant de figer ce connecteur :
    1. Version NSP réellement déployée (impacte les chemins RESTCONF/PM).
    2. Module Fault Management : "classic" (REST direct) vs "yang"
       (modèle YANG + abonnements notification), le classique étant en
       dépréciation progressive selon la documentation Nokia.

Sélection par `settings.nsp_fm_mode` ("classic" | "yang" | "unknown").

Authentification : token Bearer, durée de vie ~60 min -> rafraîchi via
TokenCache avant chaque lot d'appels.

Endpoints (mode "yang", recommandé par Nokia pour les nouvelles intégrations) :
    POST /rest-gateway/rest/api/v1/auth/token          -> authentification
    GET  /restconf/data/nsp-equipment:network/...      -> inventaire NE/liens -> dim_node/dim_link
    GET  /nsp-fault/...                                 -> alarmes -> fact_incident
    (Performance Management) endpoints spécifiques      -> metric_value (trafic, erreurs, latence liens)

Endpoints (mode "classic", pour compatibilité descendante) :
    POST /oauth2/token                                  -> authentification
    GET  /nbi-fm/api/v1/fm/alarms                       -> alarmes -> fact_incident
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .common import ToolUnavailableError, TokenCache, build_session


class NSPClient:
    def __init__(
        self,
        mode: str,
        base_url: str,
        user: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
    ):
        self.mode = mode
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.session = build_session(verify_ssl)
        self._tokens = TokenCache()

    def _headers(self) -> dict:
        token = self._tokens.get()
        if not token:
            token = self._authenticate()
        return {"Authorization": f"Bearer {token}"}

    def _authenticate(self) -> str:
        path = (
            "/rest-gateway/rest/api/v1/auth/token"
            if self.mode == "yang"
            else "/oauth2/token"
        )
        try:
            resp = self.session.post(
                f"{self.base_url}{path}",
                json={"grant_type": "client_credentials", "username": self.user, "password": self.password},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"NSP injoignable (auth): {exc}") from exc
        token = data.get("access_token")
        self._tokens.set(token, ttl_seconds=data.get("expires_in", 3600))
        return token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}", params=params, headers=self._headers(), timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ToolUnavailableError(f"NSP injoignable ({path}): {exc}") from exc

    def health_check(self) -> bool:
        if self.mode == "unknown":
            return False
        try:
            self._headers()
            return True
        except ToolUnavailableError:
            return False

    def fetch_nodes(self) -> list[dict]:
        """Inventaire des équipements réseau backbone -> dim_node.
        Chemin RESTCONF exact à confirmer selon la version NSP déployée."""
        if self.mode == "unknown":
            return []
        body = self._get("/restconf/data/nsp-equipment:network/network-element")
        elements = body.get("nsp-equipment:network-element", [])
        return [
            {
                "source_tool": "nsp",
                "external_ref": ne.get("id"),
                "name": ne.get("name"),
                "is_active": ne.get("operational-state") == "up",
            }
            for ne in elements
        ]

    def fetch_incidents(self, since: datetime) -> list[dict]:
        if self.mode == "unknown":
            return []
        path = "/nsp-fault/api/v1/alarms" if self.mode == "yang" else "/nbi-fm/api/v1/fm/alarms"
        body = self._get(path, params={"since": since.isoformat()})
        alarms = body.get("response", {}).get("data", []) or body.get("alarms", [])
        incidents = []
        for a in alarms:
            incidents.append(
                {
                    "source_tool": "nsp",
                    "external_id": a.get("id") or a.get("alarmId"),
                    "node_external_ref": a.get("affectedObject") or a.get("neId"),
                    "severity": a.get("severity"),
                    "detected_at": _iso_to_dt(a.get("raisedTime")),
                    "acknowledged_at": _iso_to_dt(a.get("ackTime")),
                    "resolved_at": _iso_to_dt(a.get("clearedTime")),
                    "description": a.get("description") or a.get("probableCause"),
                    "status": "resolved" if a.get("clearedTime") else "open",
                }
            )
        return incidents

    def fetch_metrics(self, since: datetime) -> list[dict]:
        """Compteurs de performance (PM) sur les liens backbone -> metric_value
        (bandwidth_in/out_mbps, packet_loss_pct, latency_ms). Endpoint PM
        exact à confirmer selon licence/version NSP (module Performance
        Management séparé du Fault Management)."""
        if self.mode == "unknown":
            return []
        return []  # implémenté une fois l'endpoint PM confirmé (voir README)


def _iso_to_dt(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
