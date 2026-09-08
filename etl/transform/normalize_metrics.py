"""
Normalise les métriques brutes de chaque outil vers le schéma commun
de la hypertable `metric_value` (voir sql/schema_timescale.sql) :

    {time, node_external_ref, source_tool, metric_type, value}

Chaque connecteur a déjà traduit son unité/nom de métrique natif vers un
`metric_type` de la liste commune (voir extract/api/*.py) ; ce module ne
fait qu'écarter les valeurs invalides et garantir un type cohérent.
"""
from __future__ import annotations

_VALID_METRIC_TYPES = {
    "latency_ms",
    "packet_loss_pct",
    "bandwidth_in_mbps",
    "bandwidth_out_mbps",
    "cpu_pct",
    "ram_pct",
    "availability_pct",
}


def normalize(raw_metrics: list[dict]) -> list[dict]:
    normalized = []
    for m in raw_metrics:
        if m.get("metric_type") not in _VALID_METRIC_TYPES:
            continue
        if m.get("time") is None or m.get("value") is None:
            continue
        try:
            value = float(m["value"])
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "source_tool": m["source_tool"],
                "node_external_ref": (
                    str(m["node_external_ref"]) if m.get("node_external_ref") else None
                ),
                "link_external_ref": (
                    str(m["link_external_ref"]) if m.get("link_external_ref") else None
                ),
                "metric_type": m["metric_type"],
                "time": m["time"],
                "value": value,
            }
        )
    return normalized
