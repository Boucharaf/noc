"""
Connecteur API iTop (3.2) — REST/JSON via /webservices/rest.php.

Référence : documentation REST/JSON de l'instance iTop de l'agence
(menu Admin > REST/JSON, toujours versionnée par instance).

Opération utilisée : core/get sur les classes suivantes :
    Incident (ou UserRequest selon le paramétrage de l'agence) -> fact_incident
    Organization                                               -> dim_ministry (à confirmer, voir README)
    Location                                                   -> dim_locality (à confirmer, voir README)
    NetworkDevice / Server                                     -> dim_node (croisement avec Zabbix/NetXMS)

Piège documenté : rien ne relie nativement un ticket iTop à un eventid
Zabbix. Tant que le champ personnalisé (ex. zbx_event_id) n'existe pas
côté iTop, la corrélation incident iTop <-> événement outil de supervision
se fait par (CI concerné, fenêtre temporelle proche) dans
transform/identity_resolution.py — pas ici.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from .common import ToolUnavailableError, build_session

# Nom de la classe iTop porteuse des incidents. A confirmer sur l'instance
# de l'agence (Incident si le module tickets standard est utilisé,
# UserRequest sinon) -- voir README.
INCIDENT_CLASS = "Incident"


class ITopClient:
    def __init__(self, base_url: str, user: str, password: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/") + "/webservices/rest.php"
        self.user = user
        self.password = password
        self.session = build_session(verify_ssl)

    def _call(self, operation: str, extra: dict, version: str = "1.3") -> dict:
        json_data = {"operation": operation, **extra}
        try:
            resp = self.session.post(
                self.base_url,
                params={"version": version},
                data={
                    "auth_user": self.user,
                    "auth_pwd": self.password,
                    "json_data": json.dumps(json_data),
                },
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001 - réseau ou JSON invalide
            raise ToolUnavailableError(f"iTop injoignable: {exc}") from exc
        if body.get("code", 0) != 0:
            raise ToolUnavailableError(f"iTop API error: {body.get('message')}")
        return body

    def health_check(self) -> bool:
        try:
            self._call("list_operations", {})
            return True
        except ToolUnavailableError:
            return False

    def fetch_nodes(self) -> list[dict]:
        """Référentiel CI (équipements) tel que déclaré dans iTop — sert
        de source d'identité pour le croisement avec Zabbix/NetXMS, pas de
        source de métriques."""
        nodes = []
        for cls in ("NetworkDevice", "Server"):
            body = self._call(
                "core/get",
                {
                    "class": cls,
                    "key": "SELECT " + cls,
                    "output_fields": "id,name,status,org_id,location_id",
                },
            )
            for obj in (body.get("objects") or {}).values():
                f = obj["fields"]
                nodes.append(
                    {
                        "source_tool": "itop",
                        "external_ref": obj["key"],
                        "external_type": cls,
                        "name": f["name"],
                        "is_active": f.get("status") not in ("obsolete", "decommissioned"),
                        "ministry_external_ref": f.get("org_id"),
                        "locality_external_ref": f.get("location_id"),
                    }
                )
        return nodes

    def fetch_incidents(self, since: datetime) -> list[dict]:
        since_str = since.strftime("%Y-%m-%d %H:%M:%S")
        body = self._call(
            "core/get",
            {
                "class": INCIDENT_CLASS,
                "key": f"SELECT {INCIDENT_CLASS} WHERE start_date >= '{since_str}'",
                "output_fields": (
                    "id,ref,status,start_date,resolution_date,close_date,"
                    "priority,urgency,impact,org_id,caller_id"
                ),
            },
        )
        incidents = []
        for obj in (body.get("objects") or {}).values():
            f = obj["fields"]
            incidents.append(
                {
                    "source_tool": "itop",
                    "external_id": obj["key"],
                    "itop_ticket_ref": f.get("ref"),
                    "status": f.get("status"),
                    "detected_at": _parse_dt(f.get("start_date")),
                    "resolved_at": _parse_dt(f.get("resolution_date") or f.get("close_date")),
                    "severity": f.get("priority"),
                    "ministry_external_ref": f.get("org_id"),
                }
            )
        return incidents

    def fetch_metrics(self, since: datetime) -> list[dict]:
        # iTop est un référentiel CMDB/ITSM, pas une source de métriques.
        return []

    def fetch_sla_thresholds(self) -> list[dict]:
        """SLT (Service Level Threshold) -> comparé à fact_incident.resolved_at
        pour calculer le respect SLA. Optionnel : ne casse rien si absent."""
        try:
            body = self._call(
                "core/get",
                {
                    "class": "SLT",
                    "key": "SELECT SLT",
                    "output_fields": "id,name,value,unit,metric",
                },
            )
        except ToolUnavailableError:
            return []
        return [
            {"external_id": obj["key"], **obj["fields"]}
            for obj in (body.get("objects") or {}).values()
        ]


def _parse_dt(value: Optional[str]):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
