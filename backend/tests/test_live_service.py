import asyncio

from app.services.live_service import summarise_organisations


def test_summarise_organisations_counts_current_states_and_missing_structure():
    rows = asyncio.run(
        summarise_organisations(
            [
                {"organisation": "Ministère A", "state": "up", "alerts": 2},
                {"organisation": "Ministère A", "state": "down"},
                {"organisation": "Ministère B", "state": "up"},
                {"organisation": None, "state": "silent"},
                {"organisation": "Ministère B", "state": "maintenance"},
            ]
        )
    )

    def row(name, **counts):
        base = {
            "organisation": name,
            "nodes": 0,
            "up": 0,
            "down": 0,
            "degraded": 0,
            "silent": 0,
            "maintenance": 0,
            "unknown": 0,
            "alerts": 0,
        }
        return {**base, **counts}

    # Les plus touchées d'abord ; une supervision muette n'est pas « disponible »
    # et une maintenance planifiée sort du dénominateur.
    assert rows == [
        row("Ministère A", nodes=2, up=1, down=1, alerts=2, availability_pct=50.0),
        row("Ministère B", nodes=2, up=1, maintenance=1, availability_pct=100.0),
        row("Organisation non renseignée", nodes=1, silent=1, availability_pct=0.0),
    ]
