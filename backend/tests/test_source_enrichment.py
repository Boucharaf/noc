"""Traduction des données propres à chaque outil (tickets et CI iTop,
services Centreon).

Retirés avec les fonctionnalités correspondantes (commit d4a70d7) : contexte
métier des CI (propriétaire, service, criticité), interfaces réseau,
dépendances entre hôtes, cibles SLA publiées dans l'instantané et
conservation des nœuds désactivés — ceux-ci sont désormais exclus du parc
(test_data_quality::test_collector_excludes_disabled_nodes).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from integrations.base import ToolUnavailable
from integrations.centreon import CentreonClient
from integrations.itop import ITopClient


def _ticket_response(fields: str, extra: dict | None = None) -> dict:
    """Réponse core/get d'un ticket, limitée aux champs demandés — comme iTop."""
    available = {
        "id": "7",
        "ref": "I-000007",
        "title": "Lien indisponible",
        "status": "assigned",
        "start_date": "2026-09-30 10:00:00",
        "last_update": "2026-09-30 10:05:00",
        "priority": "2",
        "org_id_friendlyname": "Ministère des Finances",
        "functionalcis_list": [{"functionalci_id": "42", "functionalci_name": "RTR-01"}],
        "agent_id_friendlyname": "A. Traoré",
        "team_id_friendlyname": "Réseau",
        "assignment_date": "2026-09-30 10:02:00",
        **(extra or {}),
    }
    requested = set(fields.split(","))
    return {
        "objects": {
            "Incident::7": {
                "key": "7",
                "fields": {key: value for key, value in available.items() if key in requested},
            }
        },
        "message": "Found: 1",
    }


def test_itop_ticket_details_and_sla_targets_are_normalized():
    client = ITopClient("http://itop", ticket_classes=("Incident",))

    async def fake_call(_operation, payload):
        if payload.get("class") == "SLT":
            return {
                "objects": {
                    "SLT::1": {
                        "key": "1",
                        "fields": {
                            "name": "WAN critique", "metric": "TTR", "value": "4", "unit": "hours",
                        },
                    }
                },
                "message": "Found: 1",
            }
        return _ticket_response(payload["output_fields"])

    client._call = fake_call
    alerts = asyncio.run(client.fetch_alerts())
    targets = asyncio.run(client.fetch_sla_targets())

    (ticket,) = alerts
    assert ticket.kind == "itsm_ticket"
    assert ticket.ticket_ref == "I-000007"
    assert ticket.severity == "high"
    assert ticket.node_ref == "42"
    # Pris en charge = sorti du statut « nouveau ».
    assert ticket.acknowledged is True
    assert ticket.acknowledged_at is not None
    assert ticket.details["agent"] == "A. Traoré"
    assert ticket.details["team"] == "Réseau"
    assert ticket.details["organisation"] == "Ministère des Finances"
    assert targets == [
        {"ref": "1", "name": "WAN critique", "metric": "TTR", "value": "4", "unit": "hours"}
    ]


def test_itop_ticket_fields_fall_back_level_by_level():
    """Code de résolution, puis prise en charge, puis socle : une classe
    personnalisée perd un niveau de détail, jamais tous ses tickets."""
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def run(refused: tuple[str, ...]):
        client = ITopClient("http://itop", ticket_classes=("Incident",))
        requested = []

        async def fake_call(_operation, payload):
            fields = payload["output_fields"]
            requested.append(fields)
            if any(name in fields.split(",") for name in refused):
                raise ToolUnavailable("itop", "Error: invalid attribute code")
            return _ticket_response(fields, {"resolution_code": ""})

        client._call = fake_call
        return asyncio.run(client.fetch_incident_history(start, end)), requested, client

    # Instance standard : code de résolution lu ; vide = cause non saisie.
    tickets, requested, _ = run(())
    assert len(requested) == 1
    assert tickets[0]["resolution_code"] == ""
    assert tickets[0]["agent"] == "A. Traoré"

    # Classe sans code de résolution : prise en charge conservée, champ absent.
    tickets, requested, client = run(("resolution_code",))
    assert len(requested) == 2
    assert tickets[0]["resolution_code"] is None
    assert tickets[0]["agent"] == "A. Traoré"
    assert client.collection_warnings == []

    # Classe sans champs de prise en charge : socle, perte signalée.
    tickets, requested, client = run(("resolution_code", "agent_id_friendlyname"))
    assert len(requested) == 3
    assert tickets[0]["agent"] is None
    assert tickets[0]["ref"] == "I-000007"
    assert client.collection_warnings == [
        "tickets Incident : détails de prise en charge indisponibles"
    ]


def test_itop_ci_maps_identity_organisation_site_and_ip():
    client = ITopClient("http://itop")

    async def fake_get_class(cls, _fields):
        if cls != "NetworkDevice":
            return None
        return {
            "objects": {
                "NetworkDevice::1": {
                    "key": "1",
                    "fields": {
                        "id": "1",
                        "name": "RTR-01",
                        "status": "production",
                        "org_id_friendlyname": "Ministère",
                        "location_id_friendlyname": "Ouagadougou",
                        "managementip": "10.0.0.1",
                    },
                }
            }
        }

    client._get_class = fake_get_class
    (node,) = asyncio.run(client.fetch_nodes())

    # La référence est l'identifiant numérique : c'est lui que les tickets citent.
    assert node.ref == "1"
    assert node.ip == "10.0.0.1"
    assert node.organisation == "Ministère"
    assert node.site == "Ouagadougou"
    assert node.node_type == "NetworkDevice"
    assert node.state == "unknown"


def test_itop_ci_without_numeric_id_is_rejected():
    client = ITopClient("http://itop")

    async def fake_get_class(cls, _fields):
        if cls != "NetworkDevice":
            return None
        return {"objects": {"NetworkDevice::1": {"key": "1", "fields": {"name": "RTR-01"}}}}

    client._get_class = fake_get_class
    try:
        asyncio.run(client.fetch_nodes())
    except ToolUnavailable as error:
        assert "sans identifiant numérique" in str(error)
    else:
        raise AssertionError("un CI sans id ne peut pas être rattaché à ses tickets")


def test_itop_ci_falls_back_to_minimal_fields_on_unknown_attribute():
    client = ITopClient("http://itop")
    calls = []

    async def fake_call(_operation, payload):
        fields = payload["output_fields"]
        calls.append(fields)
        if "managementip" in fields:
            raise ToolUnavailable("itop", "Error: invalid attribute code")
        return {
            "objects": {"NetworkDevice::1": {"key": "1", "fields": {"id": "1", "name": "RTR-01"}}},
            "message": "Found: 1",
        }

    client._call = fake_call
    result = asyncio.run(
        client._get_class(
            "NetworkDevice",
            "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip",
        )
    )

    assert len(calls) == 2
    assert calls[-1] == "id,name,status,org_id_friendlyname"
    assert result["objects"]["NetworkDevice::1"]["fields"]["name"] == "RTR-01"


def test_centreon_service_alert_attaches_to_parent_host():
    client = CentreonClient("http://centreon")
    host = {
        "id": 12,
        "type": "host",
        "name": "RTR-01",
        "fqdn": "10.0.0.1",
        "status": {"code": 0, "name": "UP"},
        "groups": [],
    }
    service = {
        "id": 55,
        "type": "service",
        "name": "Ping WAN",
        "information": "RRD loss 8%",
        "status": {"code": 2, "name": "CRITICAL"},
        "parent": {"id": 12, "name": "RTR-01"},
        "acknowledged": True,
        "acknowledgement": {"entry_time": "2026-10-01T08:00:00Z"},
        "last_status_change": "2026-10-01T07:55:00Z",
    }

    async def fake_resources(resource_types, extra=None):
        # Requête d'alertes : Centreon ne rend que les statuts en problème.
        rows = (service,) if extra and "statuses" in extra else (host, service)
        return [row for row in rows if row["type"] in resource_types]

    client._resources = fake_resources
    nodes = asyncio.run(client.fetch_nodes())
    alerts = asyncio.run(client.fetch_alerts())

    # Un service est un contrôle de l'hôte, pas un équipement.
    assert [node.ref for node in nodes] == ["host-12"]
    assert nodes[0].ip == "10.0.0.1"
    service_alert = next(alert for alert in alerts if alert.ref == "service-55")
    assert service_alert.node_ref == "host-12"
    assert service_alert.node_name == "RTR-01"
    assert service_alert.severity == "critical"
    assert service_alert.message == "RRD loss 8%"
    assert service_alert.acknowledged is True
    assert service_alert.acknowledged_at is not None
