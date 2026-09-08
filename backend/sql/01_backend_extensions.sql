-- =====================================================================
-- Extensions BACKEND de l'entrepôt NOC.
--
-- À exécuter APRÈS les trois DDL de l'ETL, dans la MÊME base :
--     psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_dimensions.sql
--     psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_facts.sql
--     psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_timescale.sql
--     psql "$NOC_WAREHOUSE_DSN" -f backend/sql/01_backend_extensions.sql
--
-- RÈGLE ABSOLUE : ce fichier est STRICTEMENT ADDITIF.
-- Il ne modifie ni ne supprime aucune colonne créée par l'ETL. Il ajoute
-- uniquement :
--   1. des colonnes NULLABLES sur dim_user (besoins d'authentification
--      backend absents du schéma ETL) ;
--   2. des tables préfixées `ops_` (opérationnel humain : timeline,
--      interventions terrain, maintenance, notifications, audit) ;
--   3. des fonctions + vues de NORMALISATION, qui traduisent les valeurs
--      brutes par outil (severity, status) vers un vocabulaire unique.
--
-- Conséquence : ré-exécuter les DDL de l'ETL ne casse rien ici, et ce
-- fichier est idempotent (IF NOT EXISTS / OR REPLACE partout).
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. dim_user : colonnes nécessaires au backend
--
-- L'ETL crée dim_user avec (id, username, full_name, role, password_hash,
-- is_active, last_login_at). Le backend a besoin en plus du PIN de
-- connexion rapide (terrain), du périmètre géographique et des données
-- de contact pour les alertes SMS.
-- ---------------------------------------------------------------------
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS pin_hash      TEXT;
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS region_id     INT REFERENCES dim_region(id);
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS locality_id   INT REFERENCES dim_locality(id);
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS ministry_id   INT REFERENCES dim_ministry(id);
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS phone_number  TEXT;
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS employee_code TEXT;
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS team          TEXT;
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_dim_user_pin_hash
    ON dim_user (pin_hash) WHERE pin_hash IS NOT NULL;

-- Le rôle est contraint aux 4 valeurs du cahier des charges. NOT VALID :
-- la contrainte s'applique aux écritures futures sans faire échouer
-- l'installation si des lignes de test antérieures portent autre chose.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_dim_user_role'
    ) THEN
        ALTER TABLE dim_user ADD CONSTRAINT chk_dim_user_role
            CHECK (role IN ('directeur', 'chef_noc', 'technicien', 'agent_terrain'))
            NOT VALID;
    END IF;
END $$;


-- ---------------------------------------------------------------------
-- 2. Normalisation severity / status
--
-- POURQUOI : l'ETL stocke la sévérité et le statut BRUTS, tels que
-- l'outil source les renvoie (voir etl/transform/normalize_incidents.py,
-- qui ne les traduit volontairement pas). Concrètement fact_incident
-- contient aujourd'hui, dans la même colonne :
--   zabbix   -> "0".."5"   (0 non classé ... 5 désastre)
--   netxms   -> "0".."4"   (0 normal ... 4 critique)
--   centreon -> "0".."3"   (état de service : 2 = CRITICAL)
--   nagios   -> "0".."3"   (idem)
--   nsp      -> "critical" | "major" | "minor" | "warning" | ...
--   itop     -> "1".."4"   (priorité, 1 = la plus forte)
--   manual   -> "critical" | "high" | "medium" | "low"
--
-- Idem pour status : iTop renvoie "new"/"assigned"/"pending"/"closed"
-- là où les outils de supervision renvoient "open"/"resolved".
--
-- Traduire ces valeurs en Python obligerait à ramener toutes les lignes
-- pour pouvoir filtrer ou grouper dessus. Les fonctions ci-dessous
-- permettent de le faire EN SQL : filtres, GROUP BY et index restent
-- côté PostgreSQL.
--
-- Si un jour l'ETL normalise lui-même la sévérité, ces fonctions
-- deviennent des passe-plats ('critical' -> 'critical') sans rien casser.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION noc_norm_severity(p_source_tool TEXT, p_severity TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_severity IS NULL THEN 'unknown'

        -- Valeurs déjà normalisées (incidents manuels, ou ETL futur)
        WHEN lower(p_severity) IN ('critical', 'high', 'medium', 'low', 'info')
            THEN lower(p_severity)

        -- Nokia NSP : vocabulaire X.733
        WHEN lower(p_severity) = 'major'         THEN 'high'
        WHEN lower(p_severity) = 'minor'         THEN 'medium'
        WHEN lower(p_severity) = 'warning'       THEN 'low'
        WHEN lower(p_severity) IN ('cleared', 'indeterminate') THEN 'info'

        -- Zabbix : 0 non classé, 1 information, 2 avertissement,
        --          3 moyen, 4 élevé, 5 désastre
        WHEN p_source_tool = 'zabbix' AND p_severity IN ('0', '1') THEN 'info'
        WHEN p_source_tool = 'zabbix' AND p_severity = '2'         THEN 'low'
        WHEN p_source_tool = 'zabbix' AND p_severity = '3'         THEN 'medium'
        WHEN p_source_tool = 'zabbix' AND p_severity = '4'         THEN 'high'
        WHEN p_source_tool = 'zabbix' AND p_severity = '5'         THEN 'critical'

        -- NetXMS : 0 normal, 1 warning, 2 minor, 3 major, 4 critical
        WHEN p_source_tool = 'netxms' AND p_severity = '0' THEN 'info'
        WHEN p_source_tool = 'netxms' AND p_severity = '1' THEN 'low'
        WHEN p_source_tool = 'netxms' AND p_severity = '2' THEN 'medium'
        WHEN p_source_tool = 'netxms' AND p_severity = '3' THEN 'high'
        WHEN p_source_tool = 'netxms' AND p_severity = '4' THEN 'critical'

        -- Centreon / Nagios : état de service
        -- 0 OK, 1 WARNING, 2 CRITICAL, 3 UNKNOWN
        WHEN p_source_tool IN ('centreon', 'nagios') AND p_severity = '0' THEN 'info'
        WHEN p_source_tool IN ('centreon', 'nagios') AND p_severity = '1' THEN 'medium'
        WHEN p_source_tool IN ('centreon', 'nagios') AND p_severity = '2' THEN 'critical'
        WHEN p_source_tool IN ('centreon', 'nagios') AND p_severity = '3' THEN 'low'

        -- iTop : priorité, 1 = la plus forte
        WHEN p_source_tool = 'itop' AND p_severity = '1' THEN 'critical'
        WHEN p_source_tool = 'itop' AND p_severity = '2' THEN 'high'
        WHEN p_source_tool = 'itop' AND p_severity = '3' THEN 'medium'
        WHEN p_source_tool = 'itop' AND p_severity = '4' THEN 'low'

        ELSE 'unknown'
    END;
$$;

CREATE OR REPLACE FUNCTION noc_norm_status(p_source_tool TEXT, p_status TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_status IS NULL THEN 'open'
        WHEN lower(p_status) IN ('open', 'acknowledged', 'resolved', 'closed')
            THEN lower(p_status)

        -- Vocabulaire iTop (Ticket / UserRequest / Incident)
        WHEN lower(p_status) IN ('new', 'dispatched', 'redispatched') THEN 'open'
        WHEN lower(p_status) IN ('assigned', 'pending', 'escalated_tto',
                                 'escalated_ttr', 'waiting_for_approval') THEN 'acknowledged'
        WHEN lower(p_status) = 'resolved'  THEN 'resolved'
        WHEN lower(p_status) IN ('closed', 'rejected') THEN 'closed'

        ELSE 'open'
    END;
$$;

-- Ordre de gravité, pour trier "les plus critiques d'abord" en SQL.
CREATE OR REPLACE FUNCTION noc_severity_rank(p_norm_severity TEXT)
RETURNS INT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_norm_severity
        WHEN 'critical' THEN 0
        WHEN 'high'     THEN 1
        WHEN 'medium'   THEN 2
        WHEN 'low'      THEN 3
        WHEN 'info'     THEN 4
        ELSE 5
    END;
$$;


-- ---------------------------------------------------------------------
-- 3. Vues de lecture consommées par le backend
--
-- Le backend ne lit JAMAIS fact_incident / dim_node directement : il
-- passe par ces vues. Cela concentre en un seul endroit toute la
-- traduction entre le schéma ETL et ce dont le dashboard a besoin
-- (sévérité normalisée, code d'équipement, hiérarchie géographique
-- aplatie). Si le schéma ETL évolue, seul ce fichier change.
-- ---------------------------------------------------------------------

-- v_node : équipement enrichi de sa géographie et de ses outils de
-- supervision. `code` n'existe pas dans dim_node (l'ETL ne le produit
-- pas) : on expose le nom comme code, ce que le frontend attend.
CREATE OR REPLACE VIEW v_node AS
SELECT
    n.id                       AS node_id,
    n.name                     AS code,
    n.name                     AS name,
    n.ip_address,
    n.node_type,
    n.is_active,
    n.ministry_id,
    m.name                     AS ministry,
    n.locality_id,
    l.name                     AS locality,
    l.code                     AS locality_code,
    l.latitude,
    l.longitude,
    l.region_id,
    r.name                     AS region,
    r.code                     AS region_code,
    COALESCE(src.tools, ARRAY[]::TEXT[])      AS source_tools,
    COALESCE(array_length(src.tools, 1), 0)   AS nb_source_tools,
    src.primary_tool           AS source_tool
FROM dim_node n
LEFT JOIN dim_ministry m ON m.id = n.ministry_id
LEFT JOIN dim_locality l ON l.id = n.locality_id
LEFT JOIN dim_region   r ON r.id = l.region_id
LEFT JOIN LATERAL (
    SELECT array_agg(s.source_tool ORDER BY s.source_tool) AS tools,
           min(s.source_tool)                              AS primary_tool
    FROM dim_node_source_map s
    WHERE s.node_id = n.id
) src ON TRUE;

-- ---------------------------------------------------------------------
-- 4. Tables opérationnelles du backend (préfixe `ops_`)
--
-- Aucune n'est écrite par l'ETL. Le préfixe rend la propriété évidente :
-- tout ce qui commence par dim_/fact_/metric_ appartient à l'ETL, tout
-- ce qui commence par ops_ appartient au backend.
-- ---------------------------------------------------------------------

-- Journal d'audit d'un incident : qui a acquitté, assigné, escaladé,
-- commenté, résolu. L'ETL ne connaît que les horodatages ; la trace des
-- actions humaines vit ici.
CREATE TABLE IF NOT EXISTS ops_incident_timeline (
    id          BIGSERIAL PRIMARY KEY,
    incident_id INT NOT NULL REFERENCES fact_incident(id) ON DELETE CASCADE,
    user_id     INT REFERENCES dim_user(id),   -- NULL = événement système/ETL
    action      TEXT NOT NULL,                 -- created|acknowledged|assigned|
                                               -- escalated|commented|resolved|reopened
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ops_timeline_incident
    ON ops_incident_timeline(incident_id, created_at DESC);

-- Assignation / escalade. Table séparée plutôt que colonnes ajoutées sur
-- fact_incident : fact_incident est écrite par l'ETL en UPSERT, et une
-- colonne d'assignation y serait écrasée à chaque cycle de collecte.
CREATE TABLE IF NOT EXISTS ops_incident_assignment (
    incident_id         INT PRIMARY KEY REFERENCES fact_incident(id) ON DELETE CASCADE,
    assigned_to_user_id INT REFERENCES dim_user(id),
    escalation_level    INT NOT NULL DEFAULT 0,   -- 0 technicien, 1 chef NOC, 2 directeur
    escalated_at        TIMESTAMPTZ,
    escalated_to_user_id INT REFERENCES dim_user(id),
    impact_scope        INT NOT NULL DEFAULT 1,
    incident_type       TEXT,                     -- network|hardware|power|software|security
    reopened_count      INT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ops_assignment_user
    ON ops_incident_assignment(assigned_to_user_id);

-- Objectifs SLA, configurables plutôt que codés en dur.
CREATE TABLE IF NOT EXISTS ops_sla_target (
    id                     SERIAL PRIMARY KEY,
    severity               TEXT NOT NULL UNIQUE,  -- sévérité NORMALISÉE
    ttr_target_minutes     INT NOT NULL,
    tta_target_minutes     INT NOT NULL,
    availability_target_pct DOUBLE PRECISION NOT NULL DEFAULT 99.0
);

INSERT INTO ops_sla_target (severity, ttr_target_minutes, tta_target_minutes, availability_target_pct)
VALUES ('critical',  60,  15, 99.5),
       ('high',     240,  30, 99.0),
       ('medium',   480,  60, 98.0),
       ('low',     1440, 240, 95.0)
ON CONFLICT (severity) DO NOTHING;

-- Fenêtres de maintenance planifiée (référencée par la vue v_incident,
-- donc créée avant elle à la ré-exécution — l'ordre importe peu ici car
-- CREATE OR REPLACE VIEW échouerait sinon ; voir la note en fin de
-- fichier sur l'ordre d'exécution).
CREATE TABLE IF NOT EXISTS ops_maintenance_window (
    id                 SERIAL PRIMARY KEY,
    node_id            INT REFERENCES dim_node(id),
    locality_id        INT REFERENCES dim_locality(id),
    reason             TEXT NOT NULL,
    starts_at          TIMESTAMPTZ NOT NULL,
    ends_at            TIMESTAMPTZ NOT NULL,
    suppress_alerts    BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id INT REFERENCES dim_user(id),
    source_tool        TEXT,       -- NULL = créée manuellement au dashboard
    external_id        TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at),
    CHECK (node_id IS NOT NULL OR locality_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_ops_maintenance_period
    ON ops_maintenance_window(starts_at, ends_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ops_maintenance_external
    ON ops_maintenance_window(source_tool, external_id)
    WHERE source_tool IS NOT NULL;

-- Interventions terrain (métier de l'Agent Terrain).
CREATE TABLE IF NOT EXISTS ops_field_intervention (
    id                BIGSERIAL PRIMARY KEY,
    incident_id       INT REFERENCES fact_incident(id) ON DELETE SET NULL,
    node_id           INT NOT NULL REFERENCES dim_node(id),
    agent_user_id     INT NOT NULL REFERENCES dim_user(id),
    status            TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled|en_route|on_site|done|cancelled
    scheduled_at      TIMESTAMPTZ,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    checkin_latitude  DOUBLE PRECISION,
    checkin_longitude DOUBLE PRECISION,
    report_text       TEXT,
    photo_urls        JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ops_field_agent
    ON ops_field_intervention(agent_user_id, status);

-- Abonnements Web Push (navigateur / PWA).
CREATE TABLE IF NOT EXISTS ops_push_subscription (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES dim_user(id) ON DELETE CASCADE,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trace des notifications envoyées (preuve d'alerte pour l'audit SLA).
CREATE TABLE IF NOT EXISTS ops_notification_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INT REFERENCES dim_user(id),
    incident_id INT REFERENCES fact_incident(id) ON DELETE SET NULL,
    channel     TEXT NOT NULL,                    -- push|sms|email
    status      TEXT NOT NULL DEFAULT 'sent',     -- sent|failed
    detail      TEXT,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ops_notification_incident
    ON ops_notification_log(incident_id);

-- Journal transverse (connexions, exports, modifications de compte).
CREATE TABLE IF NOT EXISTS ops_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INT REFERENCES dim_user(id),
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ops_audit_created ON ops_audit_log(created_at DESC);

-- Suivi des incidents déjà notifiés, pour ne pas ré-alerter à chaque
-- passage du veilleur (voir services/watcher_service.py).
CREATE TABLE IF NOT EXISTS ops_incident_notified (
    incident_id  INT PRIMARY KEY REFERENCES fact_incident(id) ON DELETE CASCADE,
    notified_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
-- 5. Libellés de cause
--
-- dim_cause est créée par l'ETL mais jamais peuplée : fact_incident.cause_category
-- porte directement la catégorie produite par etl/transform/causes.py.
-- On y insère les libellés lisibles correspondant EXACTEMENT aux
-- catégories de ce module — toute nouvelle règle regex ajoutée côté ETL
-- doit recevoir sa ligne ici, sinon la cause s'affichera sans libellé.
-- ---------------------------------------------------------------------
INSERT INTO dim_cause (category, label) VALUES
    ('lien_down',        'Lien ou interface hors service'),
    ('perte_paquets',    'Perte de paquets'),
    ('latence',          'Latence excessive'),
    ('cpu',              'Charge CPU'),
    ('memoire',          'Saturation mémoire'),
    ('alimentation',     'Défaut d''alimentation électrique'),
    ('equipement_down',  'Équipement injoignable'),
    ('seuil_trafic',     'Seuil de trafic dépassé'),
    ('non_identifie',    'Cause non identifiée')
ON CONFLICT (category) DO UPDATE SET label = EXCLUDED.label;


-- ---------------------------------------------------------------------
-- 6. Index de lecture pour le dashboard
--
-- L'ETL indexe ce dont l'écriture a besoin. Ces index-ci servent les
-- lectures du dashboard : filtres par période combinés au statut, et
-- agrégats mensuels.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_incident_status_detected
    ON fact_incident (status, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_fact_incident_source_detected
    ON fact_incident (source_tool, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_fact_incident_cause
    ON fact_incident (cause_category);
CREATE INDEX IF NOT EXISTS idx_dim_locality_region
    ON dim_locality (region_id);


-- ---------------------------------------------------------------------
-- 7. v_incident
--
-- Définie ici et non avec v_node plus haut : elle référence
-- ops_maintenance_window, qu'il faut donc avoir créée d'abord —
-- PostgreSQL résout les dépendances d'une vue au moment du CREATE.
--
-- is_maintenance neutralise les alertes tombant dans une fenêtre de
-- maintenance planifiée, pour qu'elles ne comptent pas comme des
-- violations de SLA.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_incident AS
SELECT
    i.id,
    i.source_tool,
    i.external_id,
    i.node_id,
    i.link_id,
    i.itop_ticket_ref,
    i.severity                                              AS severity_raw,
    noc_norm_severity(i.source_tool, i.severity)            AS severity,
    noc_severity_rank(noc_norm_severity(i.source_tool, i.severity)) AS severity_rank,
    i.status                                                AS status_raw,
    noc_norm_status(i.source_tool, i.status)                AS status,
    i.cause_category,
    c.label                                                 AS cause_label,
    i.detected_at,
    i.acknowledged_at,
    i.resolved_at,
    i.mtta_minutes,
    i.mttr_minutes,
    i.downtime_minutes,
    i.description,
    n.code                                                  AS node_code,
    n.name                                                  AS node_name,
    n.locality_id,
    n.locality,
    n.region_id,
    n.region,
    n.ministry_id,
    n.ministry,
    EXTRACT(HOUR FROM i.detected_at)::INT                   AS detected_hour,
    EXISTS (
        SELECT 1 FROM ops_maintenance_window w
        WHERE w.suppress_alerts
          AND i.detected_at BETWEEN w.starts_at AND w.ends_at
          AND (w.node_id = i.node_id OR w.locality_id = n.locality_id)
    )                                                       AS is_maintenance
FROM fact_incident i
LEFT JOIN v_node n    ON n.node_id = i.node_id
LEFT JOIN dim_cause c ON c.category = i.cause_category;
