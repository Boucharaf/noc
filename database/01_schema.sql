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

  -- ajouts NOC terrain (v2) — voir app/models/dimension.py::Locality
  site_type        VARCHAR(30),
  criticality_tier  VARCHAR(10) DEFAULT 'T3',
  has_backup_power BOOLEAN DEFAULT FALSE,
  address          TEXT,
  access_notes     TEXT,
  contact_name     VARCHAR(150),
  contact_phone    VARCHAR(30),

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
                 CHECK (source_tool IN ('zabbix','nagios','netxms','centreon','nsp','itop')),
  itop_ci_id   VARCHAR(50),
  is_active    BOOLEAN DEFAULT TRUE,

  -- ajouts traçabilité matérielle + topologie (v2) — voir app/models/dimension.py::Node
  vendor              VARCHAR(100),
  model               VARCHAR(100),
  serial_number       VARCHAR(100),
  firmware_version    VARCHAR(50),
  installed_at        TIMESTAMP,
  warranty_expiry_at  TIMESTAMP,
  criticality_tier    VARCHAR(10) DEFAULT 'T3',
  parent_node_id      INTEGER REFERENCES dim_node(id),
  rack_location       VARCHAR(100),
  last_seen_at        TIMESTAMP,

  created_at   TIMESTAMP DEFAULT NOW()
);

-- Un nœud physique peut être supervisé par plusieurs outils à la fois (ex.
-- Zabbix pour le temps réel + iTop pour le ticketing) — sert aussi à
-- détecter les doublons d'équipements entre outils.
CREATE TABLE dim_node_monitoring_source (
  id           SERIAL PRIMARY KEY,
  node_id      INTEGER NOT NULL REFERENCES dim_node(id),
  tool         VARCHAR(20) NOT NULL CHECK (tool IN ('zabbix','nagios','netxms','centreon','nsp','itop')),
  external_id  VARCHAR(100) NOT NULL,
  is_primary   BOOLEAN DEFAULT FALSE,
  created_at   TIMESTAMP DEFAULT NOW(),
  UNIQUE(tool, external_id)
);

CREATE TABLE dim_cause (
  id        SERIAL PRIMARY KEY,
  category  VARCHAR(50) NOT NULL,
  label     VARCHAR(150) NOT NULL,
  UNIQUE(category, label)
);

-- Comptes du tableau de bord — 4 rôles distincts (Directeur, Chef NOC,
-- Technicien/Ingénieur, Agent terrain), voir app/models/user.py::VALID_ROLES.
CREATE TABLE dim_user (
  id             SERIAL PRIMARY KEY,
  username       VARCHAR(50)  UNIQUE NOT NULL,
  full_name      VARCHAR(150) NOT NULL,
  role           VARCHAR(20)  NOT NULL DEFAULT 'agent_terrain'
                   CHECK (role IN ('directeur','chef_noc','technicien','agent_terrain')),
  password_hash  VARCHAR(100) NOT NULL,
  -- SHA-256 of the PIN, for fast quick-login lookup by hash (bcrypt is used
  -- for the primary password; a short PIN doesn't warrant adaptive hashing
  -- and needs to support direct lookup rather than per-user iteration).
  pin_hash       VARCHAR(64)  UNIQUE,
  is_active      BOOLEAN DEFAULT TRUE,
  last_login_at  TIMESTAMP,

  -- ajouts scope + organisation (v2) — voir app/models/user.py
  region_id       INTEGER REFERENCES dim_region(id),
  locality_id     INTEGER REFERENCES dim_locality(id),
  phone_number    VARCHAR(30),
  employee_code   VARCHAR(30),
  team            VARCHAR(50),
  mfa_enabled     BOOLEAN DEFAULT FALSE,

  created_at     TIMESTAMP DEFAULT NOW()
);

-- Fenêtre de maintenance planifiée : un incident détecté pendant une fenêtre
-- active est marqué 'maintenance' plutôt que remonté comme alerte critique.
-- Placée après dim_user, dont created_by_user_id dépend.
CREATE TABLE dim_maintenance_window (
  id                   SERIAL PRIMARY KEY,
  node_id              INTEGER REFERENCES dim_node(id),
  locality_id          INTEGER REFERENCES dim_locality(id),
  reason               TEXT NOT NULL,
  starts_at            TIMESTAMP NOT NULL,
  ends_at              TIMESTAMP NOT NULL,
  suppress_alerts      BOOLEAN DEFAULT TRUE,
  created_by_user_id   INTEGER NOT NULL REFERENCES dim_user(id),
  created_at           TIMESTAMP DEFAULT NOW()
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

  -- ajouts flux de traitement / rôles (v2) — voir app/models/incident.py
  assigned_to_user_id    INTEGER REFERENCES dim_user(id),
  escalation_level       INTEGER DEFAULT 0,
  escalated_at           TIMESTAMP,
  escalated_to_user_id   INTEGER REFERENCES dim_user(id),

  -- ajouts SLA / pilotage (v2)
  sla_target_minutes  INTEGER,
  sla_breached        BOOLEAN DEFAULT FALSE,
  impact_scope        INTEGER DEFAULT 1,
  incident_type       VARCHAR(30),
  parent_incident_id  BIGINT REFERENCES fact_incident(id),
  reopened_count      INTEGER DEFAULT 0,

  created_at       TIMESTAMP DEFAULT NOW()
);

-- Journal d'audit d'un incident : chaque changement de statut, note,
-- réassignation ou escalade y laisse une ligne (preuve en cas de
-- contestation SLA, reconstitution du déroulé par le Chef NOC/Directeur).
CREATE TABLE fact_incident_timeline (
  id            BIGSERIAL PRIMARY KEY,
  incident_id   BIGINT NOT NULL REFERENCES fact_incident(id),
  user_id       INTEGER REFERENCES dim_user(id),  -- null = événement système/ETL
  action        VARCHAR(30) NOT NULL,  -- created|acknowledged|assigned|escalated|commented|resolved|reopened|closed
  note          TEXT,
  created_at    TIMESTAMP DEFAULT NOW()
);

-- Objectifs SLA configurables (au lieu d'une valeur codée en dur), par
-- sévérité et éventuellement par niveau de criticité de site.
CREATE TABLE dim_sla_target (
  id                          SERIAL PRIMARY KEY,
  severity                    VARCHAR(20) NOT NULL,
  locality_criticality_tier   VARCHAR(10),  -- null = s'applique à tous
  target_minutes              INTEGER NOT NULL,
  availability_target_pct     INTEGER DEFAULT 99
);

CREATE INDEX idx_incident_node ON fact_incident(node_id);
CREATE INDEX idx_incident_detected ON fact_incident(detected_at DESC);
CREATE INDEX idx_incident_status ON fact_incident(status);
CREATE INDEX idx_incident_month ON fact_incident(
  DATE_TRUNC('month', detected_at), node_id
);
CREATE INDEX idx_node_locality ON dim_node(locality_id);
CREATE INDEX idx_locality_region ON dim_locality(region_id);

-- Monthly KPIs per node.
--
-- Availability is measured from how long the node was actually down during the
-- month, which is not the same thing as the incidents raised during it:
--
--   * An outage that is still open counts. The earlier version summed
--     downtime_minutes, which is only written when an incident is resolved, so
--     a node down since 2024 contributed nothing and the dashboard reported
--     100% availability next to a thousand open incidents.
--   * An outage counts against every month it spans, clipped to that month,
--     not only the month it was detected in.
--   * Overlapping incidents on one node count once. Summing per-incident
--     downtime double-counts a node with several concurrent alarms, and a
--     node with 27 of them would otherwise report negative availability.
--     range_agg unions the intervals first.
--   * The denominator is the elapsed part of the month, not a flat 30 days,
--     so the current month is not diluted by the days that have not happened.
--
-- total_incidents / resolved / avg_mttr keep their original meaning: incidents
-- *detected* in that month. A node-month can therefore hold 0 incidents and
-- still show degraded availability — that is an outage which started earlier
-- and has not been cleared.
CREATE MATERIALIZED VIEW mv_kpi_node_monthly AS
WITH span AS (
  SELECT
    i.id, i.node_id, i.status, i.mttr_minutes, i.detected_at,
    TSRANGE(
      i.detected_at,
      CASE
        WHEN i.status IN ('open', 'acknowledged')
          THEN GREATEST(NOW()::TIMESTAMP, i.detected_at)
        ELSE GREATEST(COALESCE(i.resolved_at, i.detected_at), i.detected_at)
      END,
      '[)'
    ) AS outage
  FROM fact_incident i
),
node_month AS (
  SELECT DISTINCT s.node_id, m AS month
  FROM span s,
  LATERAL GENERATE_SERIES(
    DATE_TRUNC('month', LOWER(s.outage)),
    DATE_TRUNC('month', UPPER(s.outage)),
    INTERVAL '1 month'
  ) AS m
),
unioned AS (
  SELECT nm.node_id, nm.month,
         RANGE_AGG(s.outage * TSRANGE(nm.month, nm.month + INTERVAL '1 month', '[)')) AS outages
  FROM node_month nm
  JOIN span s
    ON s.node_id = nm.node_id
   AND s.outage && TSRANGE(nm.month, nm.month + INTERVAL '1 month', '[)')
  GROUP BY 1, 2
),
downtime AS (
  SELECT u.node_id, u.month,
         COALESCE(SUM(EXTRACT(EPOCH FROM (UPPER(o) - LOWER(o))) / 60.0), 0) AS total_downtime
  FROM unioned u, LATERAL UNNEST(u.outages) o
  GROUP BY 1, 2
)
SELECT
  nm.month,
  n.id                               AS node_id,
  n.code, n.name, n.source_tool,
  l.id                               AS locality_id,
  l.name                             AS locality,
  r.name                             AS region,
  COUNT(i.id)                        AS total_incidents,
  COUNT(i.id) FILTER (WHERE i.status IN ('resolved', 'closed')) AS resolved,
  AVG(i.mttr_minutes)                AS avg_mttr,
  COALESCE(d.total_downtime, 0)::INTEGER AS total_downtime,
  GREATEST(0, 100.0 - COALESCE(d.total_downtime, 0) / GREATEST(
    EXTRACT(EPOCH FROM (
      LEAST(nm.month + INTERVAL '1 month', NOW()::TIMESTAMP) - nm.month
    )) / 60.0, 1) * 100)             AS availability_pct
FROM node_month nm
JOIN dim_node n ON n.id = nm.node_id
JOIN dim_locality l ON n.locality_id = l.id
JOIN dim_region r ON l.region_id = r.id
LEFT JOIN downtime d ON d.node_id = nm.node_id AND d.month = nm.month
LEFT JOIN fact_incident i
       ON i.node_id = nm.node_id
      AND DATE_TRUNC('month', i.detected_at) = nm.month
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, d.total_downtime
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

-- Interventions terrain — cœur du métier de l'Agent Terrain, voir
-- app/models/operations.py::FieldIntervention.
CREATE TABLE fact_field_intervention (
  id                  BIGSERIAL PRIMARY KEY,
  incident_id         BIGINT REFERENCES fact_incident(id),  -- nullable : tournée de routine
  node_id             INTEGER NOT NULL REFERENCES dim_node(id),
  agent_user_id       INTEGER NOT NULL REFERENCES dim_user(id),

  status              VARCHAR(20) NOT NULL DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled','en_route','on_site','done','cancelled')),
  scheduled_at        TIMESTAMP,
  started_at          TIMESTAMP,
  completed_at        TIMESTAMP,

  checkin_latitude    DECIMAL(9,6),
  checkin_longitude   DECIMAL(9,6),

  report_text         TEXT,
  photo_urls          TEXT,  -- JSON-encodé, liste d'URLs (S3/stockage local)

  created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_field_intervention_agent ON fact_field_intervention(agent_user_id);
CREATE INDEX idx_field_intervention_status ON fact_field_intervention(status);

-- Règle déclenchée par le scheduler Celery : si un incident de sévérité X
-- n'est pas acquitté/résolu après N minutes, il est escaladé automatiquement.
CREATE TABLE dim_escalation_rule (
  id                     SERIAL PRIMARY KEY,
  severity               VARCHAR(20) NOT NULL,
  trigger_after_minutes  INTEGER NOT NULL,
  from_escalation_level  INTEGER NOT NULL,
  escalate_to_role       VARCHAR(20) NOT NULL CHECK (escalate_to_role IN ('chef_noc','directeur')),
  is_active              BOOLEAN DEFAULT TRUE
);

-- Trace de ce qui a été envoyé, à qui, sur quel canal — debug push/SMS et
-- preuve d'audit SLA (une alerte a bien été notifiée).
CREATE TABLE fact_notification_log (
  id            BIGSERIAL PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES dim_user(id),
  incident_id   BIGINT REFERENCES fact_incident(id),
  channel       VARCHAR(20) NOT NULL CHECK (channel IN ('push','sms','email')),
  status        VARCHAR(20) NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','failed','read')),
  sent_at       TIMESTAMP DEFAULT NOW()
);

-- Journal transverse (au-delà des incidents) : connexions, création/
-- modification d'un nœud, changement de rôle, export de rapport... Requis
-- dès qu'un Directeur ou un client externe peut demander "qui a fait quoi".
CREATE TABLE audit_log (
  id           SERIAL PRIMARY KEY,
  user_id      INTEGER REFERENCES dim_user(id),
  action       VARCHAR(50) NOT NULL,
  entity_type  VARCHAR(50),
  entity_id    VARCHAR(50),
  ip_address   VARCHAR(50),
  created_at   TIMESTAMP DEFAULT NOW()
);
