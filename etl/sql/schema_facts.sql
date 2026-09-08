-- Faits relationnels (non temps-série pur) de l'entrepôt NOC.

CREATE TABLE IF NOT EXISTS fact_incident (
    id                SERIAL PRIMARY KEY,
    source_tool       TEXT NOT NULL,
    external_id       TEXT NOT NULL,
    node_id           INT REFERENCES dim_node(id),
    link_id           INT REFERENCES dim_link(id),
    itop_ticket_ref   TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    severity          TEXT,
    cause_category    TEXT,
    detected_at       TIMESTAMPTZ,
    acknowledged_at   TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ,
    mtta_minutes      DOUBLE PRECISION,
    mttr_minutes      DOUBLE PRECISION,
    downtime_minutes  DOUBLE PRECISION,
    description       TEXT,
    UNIQUE (source_tool, external_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_incident_node ON fact_incident(node_id);
CREATE INDEX IF NOT EXISTS idx_fact_incident_status ON fact_incident(status);
CREATE INDEX IF NOT EXISTS idx_fact_incident_detected_at ON fact_incident(detected_at);

CREATE TABLE IF NOT EXISTS fact_supervision_coverage_daily (
    date               DATE NOT NULL,
    ministry_id        INT REFERENCES dim_ministry(id),
    locality_id        INT REFERENCES dim_locality(id),
    nb_equip_total     INT NOT NULL DEFAULT 0,
    nb_equip_supervised INT NOT NULL DEFAULT 0,
    PRIMARY KEY (date, ministry_id, locality_id)
);
