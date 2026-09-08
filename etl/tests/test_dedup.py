from etl.transform import dedup


def test_dedup_incidents_prefers_api_and_adds_missing_from_db():
    api = [{"source_tool": "zabbix", "external_id": "1", "status": "open"}]
    db = [
        {"source_tool": "zabbix", "external_id": "1", "status": "resolved"},  # doublon -> ignoré
        {"source_tool": "zabbix", "external_id": "2", "status": "open"},      # absent de l'API -> ajouté
    ]
    result = dedup.dedup_incidents(api, db)
    assert len(result) == 2
    kept = {r["external_id"]: r["status"] for r in result}
    assert kept["1"] == "open"  # l'API prime, jamais écrasée par la BDD
    assert kept["2"] == "open"


def test_dedup_metrics_uses_full_key():
    api = [
        {"source_tool": "zabbix", "node_external_ref": "10", "metric_type": "cpu_pct",
         "time": "2026-01-01T00:00:00Z", "value": 42},
    ]
    db = [
        {"source_tool": "zabbix", "node_external_ref": "10", "metric_type": "cpu_pct",
         "time": "2026-01-01T00:00:00Z", "value": 99},  # même clé -> ignoré
        {"source_tool": "zabbix", "node_external_ref": "10", "metric_type": "cpu_pct",
         "time": "2026-01-01T01:00:00Z", "value": 50},  # timestamp différent -> ajouté
    ]
    result = dedup.dedup_metrics(api, db)
    assert len(result) == 2
