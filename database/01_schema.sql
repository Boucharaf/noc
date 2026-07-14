CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Dimensions géographiques
CREATE TABLE dim_region (
  id          SERIAL PRIMARY KEY,
  code        VARCHAR(10)  UNIQUE NOT NULL,
  name        VARCHAR(100) NOT NULL,
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_locality (
  id          SERIAL PRIMARY KEY,
  region_id   INTEGER NOT NULL REFERENCES dim_region(id),
  code        VARCHAR(10)  UNIQUE NOT NULL,
  name        VARCHAR(150) NOT NULL,
  latitude    DECIMAL(9,6),
  longitude   DECIMAL(9,6),
  population  INTEGER DEFAULT 0,
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_node (
  id           SERIAL PRIMARY KEY,
  locality_id  INTEGER NOT NULL REFERENCES dim_locality(id),
  code         VARCHAR(20)  UNIQUE NOT NULL,
  name         VARCHAR(200) NOT NULL,
  node_type    VARCHAR(50)  NOT NULL,
  ip_address   INET,
  source_tool  VARCHAR(20)  NOT NULL
                 CHECK (source_tool IN ('zabbix','nagios','netxms','centreon')),
  itop_ci_id   VARCHAR(50),
  is_active    BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_cause (
  id        SERIAL PRIMARY KEY,
  category  VARCHAR(50) NOT NULL,
  label     VARCHAR(150) NOT NULL,
  UNIQUE(category, label)
);

-- Comptes du tableau de bord (§10.1 : admin / analyst / noc_agent)
CREATE TABLE dim_user (
  id             SERIAL PRIMARY KEY,
  username       VARCHAR(50)  UNIQUE NOT NULL,
  full_name      VARCHAR(150) NOT NULL,
  role           VARCHAR(20)  NOT NULL DEFAULT 'noc_agent'
                   CHECK (role IN ('admin','analyst','noc_agent')),
  password_hash  VARCHAR(100) NOT NULL,
  -- SHA-256 of the PIN, for fast quick-login lookup by hash (bcrypt is used
  -- for the primary password; a short PIN doesn't warrant adaptive hashing
  -- and needs to support direct lookup rather than per-user iteration).
  pin_hash       VARCHAR(64)  UNIQUE,
  is_active      BOOLEAN DEFAULT TRUE,
  last_login_at  TIMESTAMP,
  created_at     TIMESTAMP DEFAULT NOW()
);

-- Table de faits principale
CREATE TABLE fact_incident (
  id               BIGSERIAL PRIMARY KEY,
  node_id          INTEGER NOT NULL REFERENCES dim_node(id),
  cause_id         INTEGER REFERENCES dim_cause(id),
  itop_ticket_id   VARCHAR(50),
  external_id      VARCHAR(100),
  status           VARCHAR(20) NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open','acknowledged','resolved','closed')),
  severity         VARCHAR(20) NOT NULL DEFAULT 'medium'
                     CHECK (severity IN ('critical','high','medium','low')),
  detected_at      TIMESTAMP NOT NULL,
  acknowledged_at  TIMESTAMP,
  resolved_at      TIMESTAMP,
  mttr_minutes     INTEGER GENERATED ALWAYS AS (
    EXTRACT(EPOCH FROM (resolved_at - detected_at)) / 60
  ) STORED,
  downtime_minutes INTEGER DEFAULT 0,
  shift            VARCHAR(20) GENERATED ALWAYS AS (
    CASE
      WHEN EXTRACT(HOUR FROM detected_at) BETWEEN 6 AND 21 THEN 'noc'
      WHEN EXTRACT(HOUR FROM detected_at) BETWEEN 7 AND 16 THEN 'terrain'
      ELSE 'auto'
    END
  ) STORED,
  source_tool      VARCHAR(20) NOT NULL,
  description      TEXT,
  created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_incident_node ON fact_incident(node_id);
CREATE INDEX idx_incident_detected ON fact_incident(detected_at DESC);
CREATE INDEX idx_incident_status ON fact_incident(status);
CREATE INDEX idx_incident_month ON fact_incident(
  DATE_TRUNC('month', detected_at), node_id
);
CREATE INDEX idx_node_locality ON dim_node(locality_id);
CREATE INDEX idx_locality_region ON dim_locality(region_id);

CREATE MATERIALIZED VIEW mv_kpi_node_monthly AS
SELECT
  DATE_TRUNC('month', i.detected_at)  AS month,
  n.id                               AS node_id,
  n.code, n.name, n.source_tool,
  l.id                               AS locality_id,
  l.name                             AS locality,
  r.name                             AS region,
  COUNT(i.id)                        AS total_incidents,
  COUNT(CASE WHEN i.status='resolved' THEN 1 END) AS resolved,
  AVG(i.mttr_minutes)                AS avg_mttr,
  SUM(i.downtime_minutes)            AS total_downtime,
  100.0 - (SUM(i.downtime_minutes)::FLOAT
    / (24.0*60*30)*100)              AS availability_pct
FROM fact_incident i
JOIN dim_node n ON i.node_id = n.id
JOIN dim_locality l ON n.locality_id = l.id
JOIN dim_region r ON l.region_id = r.id
GROUP BY 1,2,3,4,5,6,7,8
WITH DATA;

CREATE UNIQUE INDEX ON mv_kpi_node_monthly(month, node_id);

-- Browser/PWA Web Push subscriptions (one row per device/browser a user has
-- granted notification permission on).
CREATE TABLE push_subscription (
  id          SERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES dim_user(id),
  endpoint    TEXT UNIQUE NOT NULL,
  p256dh      TEXT NOT NULL,
  auth        TEXT NOT NULL,
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_push_subscription_user ON push_subscription(user_id);
