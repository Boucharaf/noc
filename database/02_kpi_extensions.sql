-- ============================================================================
-- Extension additive à 01_schema.sql — NE PAS modifier 01_schema.sql.
--
-- Sur une base neuve (docker-entrypoint-initdb.d), ce fichier s'exécute après
-- 01_schema.sql grâce au tri alphabétique de Postgres au premier démarrage.
-- Sur une base déjà en service, appliquer manuellement :
--   psql "$DATABASE_URL" -f database/02_kpi_extensions.sql
--
-- Couvre les manques identifiés face au document de KPI de l'agence :
--   1. fact_metric        — métriques de performance (CPU/RAM/bande passante/
--                            latence/perte de paquets/disponibilité), en série
--                            temporelle. Les fonctions ETL qui les collectent
--                            existaient déjà (etl/extract/zabbix.py) mais
--                            n'avaient nulle part où écrire.
--   2. dim_asset           — référentiel du parc total, indépendant des outils
--                            de supervision. Nécessaire pour calculer un vrai
--                            taux de couverture ("équipements non supervisés")
--                            plutôt que de ne compter que ce que les outils
--                            remontent déjà.
--   3. dim_province /
--      dim_organisation    — hiérarchie ministère → province → site, pour le
--                            drill-down demandé (KPI global → ministère →
--                            province → site → équipement → incident).
--   4. dim_maintenance_window — extension pour accepter les fenêtres importées
--                            automatiquement par l'ETL (maintenance.get côté
--                            Zabbix/Centreon/NetXMS), en plus de celles créées
--                            manuellement depuis le dashboard.
-- ============================================================================


-- ── 1. Métriques de performance (série temporelle) ─────────────────────────
--
-- Une seule table pour toutes les métriques de performance ET la
-- disponibilité (metric_type='availability', value=1/0) : les deux sont la
-- même chose du point de vue du stockage — une lecture datée pour un nœud —
-- et ça évite de dupliquer l'ingestion/les index pour un signal de plus.
--
-- Table volumineuse par nature (une ligne par nœud par métrique par poll).
-- Si l'extension TimescaleDB est disponible sur ce Postgres, convertir cette
-- table en hypertable donne un bien meilleur passage à l'échelle et permet la
-- compression + rétention automatique des anciennes données :
--   SELECT create_hypertable('fact_metric', 'collected_at', if_not_exists => TRUE);
-- Sans TimescaleDB, prévoir un job de purge (ex. garder 90 jours de détail,
-- au-delà ne conserver que les agrégats mensuels déjà calculés ailleurs).
CREATE TABLE fact_metric (
  id            BIGSERIAL PRIMARY KEY,
  node_id       INTEGER NOT NULL REFERENCES dim_node(id),
  source_tool   VARCHAR(20) NOT NULL,
  metric_type   VARCHAR(30) NOT NULL CHECK (metric_type IN (
                   'cpu_pct', 'ram_pct', 'bandwidth_in_bps', 'bandwidth_out_bps',
                   'latency_ms', 'packet_loss_pct', 'availability'
                 )),
  value         DOUBLE PRECISION NOT NULL,
  unit          VARCHAR(20),
  collected_at  TIMESTAMP NOT NULL,
  created_at    TIMESTAMP DEFAULT NOW()
);

-- Une lecture par (nœud, métrique, outil, instant) : un poll qui retombe sur
-- la même valeur/le même timestamp que le précédent (ex. Zabbix lastclock
-- inchangé) ne duplique pas la ligne — ON CONFLICT DO NOTHING côté ingestion.
CREATE UNIQUE INDEX idx_metric_dedup
  ON fact_metric(node_id, metric_type, source_tool, collected_at);

-- "Dernière valeur connue par nœud/métrique" est la requête la plus fréquente
-- (équipements DOWN, CPU actuel...) — index descendant pour la servir sans tri.
CREATE INDEX idx_metric_latest ON fact_metric(node_id, metric_type, collected_at DESC);

-- KPI réseau agrégés sur une période (latence moyenne, bande passante...) sur
-- l'ensemble du parc plutôt qu'un nœud précis.
CREATE INDEX idx_metric_type_time ON fact_metric(metric_type, collected_at DESC);


-- ── 2. Référentiel de couverture (parc total vs supervisé) ──────────────────
--
-- Indépendant de dim_node : dim_node ne contient que ce que les outils de
-- supervision remontent déjà, donc il est structurellement impossible d'y
-- calculer un taux de couverture. dim_asset est peuplée depuis l'inventaire
-- CMDB complet d'iTop (tous les CI, qu'ils soient supervisés ou non), puis
-- rapprochée de dim_node pour savoir lesquels le sont effectivement.
CREATE TABLE dim_asset (
  id             SERIAL PRIMARY KEY,
  locality_id    INTEGER REFERENCES dim_locality(id),
  itop_ci_id     VARCHAR(50) UNIQUE NOT NULL,
  name           VARCHAR(200) NOT NULL,
  asset_type     VARCHAR(50),
  is_monitored   BOOLEAN NOT NULL DEFAULT FALSE,
  node_id        INTEGER REFERENCES dim_node(id),  -- NULL tant que non supervisé
  last_synced_at TIMESTAMP,
  created_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_asset_locality ON dim_asset(locality_id);
CREATE INDEX idx_asset_monitored ON dim_asset(is_monitored);

-- Vue de couverture par site/région — pas de matérialisation nécessaire, le
-- volume (taille du parc, pas des incidents) reste largement dans les
-- capacités d'une vue classique.
CREATE VIEW v_kpi_coverage_locality AS
SELECT
  l.id                                                    AS locality_id,
  l.name                                                  AS locality,
  r.id                                                    AS region_id,
  r.name                                                  AS region,
  COUNT(a.id)                                             AS total_assets,
  COUNT(a.id) FILTER (WHERE a.is_monitored)                AS monitored_assets,
  COUNT(a.id) FILTER (WHERE NOT a.is_monitored)            AS unmonitored_assets,
  CASE WHEN COUNT(a.id) = 0 THEN NULL
       ELSE ROUND(100.0 * COUNT(a.id) FILTER (WHERE a.is_monitored) / COUNT(a.id), 1)
  END                                                      AS coverage_pct
FROM dim_locality l
JOIN dim_region r ON r.id = l.region_id
LEFT JOIN dim_asset a ON a.locality_id = l.id
GROUP BY l.id, l.name, r.id, r.name;


-- ── 3. Hiérarchie organisationnelle (ministère / province) ──────────────────
CREATE TABLE dim_organisation (
  id         SERIAL PRIMARY KEY,
  code       VARCHAR(20) UNIQUE NOT NULL,
  name       VARCHAR(200) NOT NULL,
  org_type   VARCHAR(30),  -- ministere | institution | structure_rattachee ...
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE dim_province (
  id         SERIAL PRIMARY KEY,
  region_id  INTEGER NOT NULL REFERENCES dim_region(id),
  code       VARCHAR(10) UNIQUE NOT NULL,
  name       VARCHAR(100) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE dim_locality
  ADD COLUMN province_id     INTEGER REFERENCES dim_province(id),
  ADD COLUMN organisation_id INTEGER REFERENCES dim_organisation(id);

CREATE INDEX idx_locality_province ON dim_locality(province_id);
CREATE INDEX idx_locality_organisation ON dim_locality(organisation_id);


-- ── 4. Fenêtres de maintenance importées automatiquement ────────────────────
--
-- La table existante suppose une création humaine depuis le dashboard
-- (created_by_user_id NOT NULL). Une fenêtre déclarée dans Zabbix/Centreon/
-- NetXMS n'a pas d'utilisateur dashboard associé — on la distingue par
-- source_tool/external_id (NULL tous les deux = origine manuelle, comme
-- avant) et created_by_user_id devient nullable pour ce cas.
ALTER TABLE dim_maintenance_window
  ALTER COLUMN created_by_user_id DROP NOT NULL,
  ADD COLUMN source_tool VARCHAR(20),
  ADD COLUMN external_id VARCHAR(100);

-- Empêche de réimporter la même fenêtre à chaque poll (5 min) — index partiel
-- car les fenêtres manuelles n'ont pas d'external_id.
CREATE UNIQUE INDEX idx_maintenance_window_import
  ON dim_maintenance_window(source_tool, external_id)
  WHERE source_tool IS NOT NULL AND external_id IS NOT NULL;

ALTER TABLE dim_maintenance_window
  ADD CONSTRAINT chk_maintenance_origin CHECK (
    (source_tool IS NULL AND external_id IS NULL AND created_by_user_id IS NOT NULL)
    OR
    (source_tool IS NOT NULL AND external_id IS NOT NULL AND created_by_user_id IS NULL)
  );


-- ── 5. mv_kpi_node_monthly : exclure les incidents corrélés cross-outils ───
--
-- La corrélation cross-outils (voir incident_service.find_correlated_incident)
-- rattache un événement secondaire (ex. NetXMS) à l'incident déjà ouvert par
-- un autre outil (ex. Zabbix) sur le même nœud via parent_incident_id, plutôt
-- que de créer un second incident indépendant. Sans ce correctif, ces lignes
-- enfants restent comptées dans total_incidents/resolved par
-- mv_kpi_node_monthly — exactement le double-comptage que la corrélation est
-- censée éliminer. Le calcul de disponibilité (span/unioned/downtime) n'a en
-- revanche pas besoin d'être touché : RANGE_AGG fusionne déjà les plages de
-- panne qui se chevauchent, qu'elles proviennent d'un parent ou d'un enfant.
--
-- Recréée à l'identique du 01_schema.sql, seul le filtre
-- "i.parent_incident_id IS NULL" change sur les deux COUNT(i.id).
DROP MATERIALIZED VIEW mv_kpi_node_monthly;

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
  COUNT(i.id) FILTER (WHERE i.parent_incident_id IS NULL) AS total_incidents,
  COUNT(i.id) FILTER (
    WHERE i.parent_incident_id IS NULL AND i.status IN ('resolved', 'closed')
  )                                  AS resolved,
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
