-- Métriques temps-série, extension TimescaleDB.
-- Un seul type de table pour tous les outils : chaque connecteur
-- normalise déjà son metric_type natif vers cette liste commune
-- (voir transform/normalize_metrics.py).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS metric_value (
    time           TIMESTAMPTZ NOT NULL,
    node_id        INT REFERENCES dim_node(id),
    link_id        INT REFERENCES dim_link(id),
    source_tool    TEXT NOT NULL,
    metric_type    TEXT NOT NULL,  -- latency_ms | packet_loss_pct | bandwidth_in_mbps |
                                     -- bandwidth_out_mbps | cpu_pct | ram_pct | availability_pct
    value          DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('metric_value', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_metric_value_node_type_time
    ON metric_value (node_id, metric_type, time DESC);

-- Agrégats continus horaires, base des vues de tendance 24h/7j/30j/6mois.
CREATE MATERIALIZED VIEW IF NOT EXISTS metric_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    node_id,
    metric_type,
    avg(value)  AS avg_value,
    min(value)  AS min_value,
    max(value)  AS max_value
FROM metric_value
GROUP BY bucket, node_id, metric_type;

SELECT add_continuous_aggregate_policy('metric_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Rétention des données brutes : 13 mois (couvre le KPI "tendance 6 mois"
-- avec de la marge). Les agrégats horaires, eux, ne sont jamais purgés.
SELECT add_retention_policy('metric_value', INTERVAL '13 months', if_not_exists => TRUE);

-- Compression des chunks de plus de 7 jours pour limiter le volume disque.
ALTER TABLE metric_value SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'node_id, metric_type'
);
SELECT add_compression_policy('metric_value', INTERVAL '7 days', if_not_exists => TRUE);
