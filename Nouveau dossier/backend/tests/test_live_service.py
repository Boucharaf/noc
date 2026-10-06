from app.services.live_service import summarise_organisations


def test_summarise_organisations_counts_current_states_and_missing_structure():
    rows = summarise_organisations(
        [
            {"organisation": "Ministère A", "state": "up"},
            {"organisation": "Ministère A", "state": "down"},
            {"organisation": "Ministère B", "state": "up"},
            {"organisation": None, "state": "silent"},
        ]
    )

    assert rows == [
        {
            "organisation": "Structure non renseignée",
            "nodes_total": 1,
            "nodes_up": 0,
            "nodes_down": 0,
            "nodes_degraded": 0,
            "nodes_silent": 1,
            "nodes_maintenance": 0,
            "availability_pct": 0.0,
        },
        {
            "organisation": "Ministère A",
            "nodes_total": 2,
            "nodes_up": 1,
            "nodes_down": 1,
            "nodes_degraded": 0,
            "nodes_silent": 0,
            "nodes_maintenance": 0,
            "availability_pct": 50.0,
        },
        {
            "organisation": "Ministère B",
            "nodes_total": 1,
            "nodes_up": 1,
            "nodes_down": 0,
            "nodes_degraded": 0,
            "nodes_silent": 0,
            "nodes_maintenance": 0,
            "availability_pct": 100.0,
        },
    ]