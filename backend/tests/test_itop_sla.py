"""Compteurs SLA d'iTop : quand iTop mesure, son verdict fait foi.

iTop arrête ses chronomètres pendant l'attente du demandeur et hors des
heures de couverture du contrat. Le calcul du NOC en temps continu
(résolution - ouverture) comptait ce temps comme du retard.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from integrations.base import ToolUnavailable
from integrations.itop import ITopClient, itop_sla

from app.services import incident_service as svc

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
GOALS = {"critical": SimpleNamespace(tta_target_minutes=15, ttr_target_minutes=240)}


def _goals(contract=None):
    goals = svc.Goals(GOALS)
    goals.contract = contract or {}
    return goals


def test_itop_verdict_replaces_wall_clock_breach():
    """Ouvert 10 h, résolu 6 h plus tard dont 4 h « en attente » : 6 h en
    temps continu dépasseraient l'objectif de 4 h ; iTop a compté 2 h et dit
    « tenu »."""
    opened = NOW - timedelta(hours=10)
    resolved = opened + timedelta(hours=6)
    facts = {"ttr_passed": False, "ttr_spent_s": 7200, "ttr_over_s": 0,
             "tto_passed": False, "tto_spent_s": 300}

    noc = svc._sla_state("critical", opened, opened + timedelta(minutes=5), resolved,
                         _goals(), NOW)
    itop = svc._sla_state("critical", opened, opened + timedelta(minutes=5), resolved,
                          _goals({"critical": {"ttr": 240, "tto": 15}}), NOW, facts)

    assert (noc["ttr_status"], noc["sla_source"]) == ("breached", "noc")
    assert (itop["ttr_status"], itop["sla_source"]) == ("met", "itop")
    assert itop["ttr_minutes"] == 120 and itop["ttr_wall_minutes"] == 360
    assert itop["tto_status"] == "met" and itop["tto_minutes"] == 5


def test_itop_passed_flag_and_overrun():
    opened = NOW - timedelta(hours=3)
    facts = {"ttr_passed": True, "ttr_over_s": 1800}
    state = svc._sla_state("critical", opened, None, NOW, _goals({"critical": {"ttr": 120}}),
                           NOW, facts)
    assert state["ttr_status"] == "breached"
    assert state["ttr_target_minutes"] == 120
    assert state["ttr_overrun_minutes"] == 30


def test_open_ticket_uses_itop_deadline():
    opened = NOW - timedelta(hours=1)
    soon = {"ttr_passed": False, "ttr_deadline": (NOW + timedelta(minutes=20)).isoformat()}
    late = {"ttr_passed": False, "ttr_deadline": (NOW - timedelta(minutes=5)).isoformat()}

    running = svc._sla_state("critical", opened, None, None, _goals(), NOW, soon)
    overdue = svc._sla_state("critical", opened, None, None, _goals(), NOW, late)

    assert (running["ttr_status"], running["ttr_remaining_minutes"]) == ("running", 20)
    assert overdue["ttr_status"] == "breached"


def test_ticket_without_itop_threshold_falls_back_to_noc_goal():
    """« Non dépassé » sans échéance ni seuil de contrat : iTop ne mesure pas
    ce ticket ; l'objectif du NOC s'applique et c'est dit."""
    opened = NOW - timedelta(hours=5)
    state = svc._sla_state("critical", opened, None, None, _goals(), NOW,
                           {"ttr_passed": False})
    assert (state["ttr_status"], state["sla_source"]) == ("breached", "noc")


def test_itop_sla_fields_are_parsed_flexibly():
    facts = itop_sla({
        "sla_ttr_passed": "yes", "sla_ttr_over": "600", "ttr": {"timespent": 3600},
        "sla_tto_passed": "0", "tto": 120, "ttr_escalation_deadline": "2026-11-20 14:00:00",
    })
    assert facts["ttr_passed"] is True and facts["ttr_over_s"] == 600
    assert facts["ttr_spent_s"] == 3600 and facts["tto_spent_s"] == 120
    assert facts["tto_passed"] is False
    assert facts["ttr_deadline"].startswith("2026-11-20T14:00:00")
    assert itop_sla({"id": "1"}) is None


def test_unknown_sla_field_is_dropped_alone():
    """L'instance ne connaît pas « tto_escalation_deadline » : seul ce champ
    est retiré, les autres compteurs restent demandés."""
    client = ITopClient("http://itop", ticket_classes=("Incident",))
    requested = []

    async def fake_call(_operation, payload):
        fields = payload["output_fields"].split(",")
        requested.append(fields)
        if "tto_escalation_deadline" in fields:
            raise ToolUnavailable("itop", "Error: invalid attribute code "
                                          "'tto_escalation_deadline' for class 'Incident'")
        values = {"id": "7", "ref": "I-7", "title": "x", "status": "resolved",
                  "start_date": "2026-11-20 08:00:00", "sla_ttr_passed": "no", "ttr": 60}
        return {"objects": {"Incident::7": {"key": "7", "fields": {
            k: v for k, v in values.items() if k in fields}}}, "message": "Found: 1"}

    client._call = fake_call
    start, end = NOW - timedelta(days=1), NOW
    (ticket,) = asyncio.run(client.fetch_incident_history(start, end))

    assert len(requested) == 2
    assert "sla_ttr_passed" in requested[1] and "tto_escalation_deadline" not in requested[1]
    assert ticket["itop_sla"]["ttr_passed"] is False
    # Appris : la requête suivante ne le redemande pas.
    asyncio.run(client.fetch_incident_history(start, end))
    assert len(requested) == 3
