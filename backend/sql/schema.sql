-- =====================================================================
--  Base PostgreSQL du NOC — ce que les outils sources ne savent pas.
-- =====================================================================
--
-- CE QUI A DISPARU PAR RAPPORT À LA VERSION PRÉCÉDENTE, et pourquoi :
--
--   metric_value (hypertable TimescaleDB)  — des millions de lignes par
--       jour recopiées de Zabbix. C'était le poste de coût principal.
--       L'historique est désormais lu chez l'outil source à la demande
--       (backend/app/services/history_service.py).
--   fact_incident, dim_node, dim_locality, dim_ministry, dim_region…
--       — l'état courant vit dans Redis et se reconstruit toutes les
--       300 s ; le recopier en base ajoutait un fantôme de plus à chaque
--       équipement retiré de la supervision.
--   L'extension timescaledb elle-même — plus rien ne l'utilise.
--
-- CE QUI RESTE tient en une règle : on ne persiste QUE ce que le NOC
-- produit lui-même. Toutes les données affichées — équipements, alertes,
-- incidents, maintenances, interventions — viennent des API des outils
-- (Zabbix, Centreon, NetXMS, Nagios, NSP, iTop). La base porte les comptes,
-- les objectifs SLA, le journal d'audit, la trace des notifications et les
-- bilans journaliers de la collecte.
--
-- Ce fichier se rejoue sans danger sur une base en service, et c'est ainsi
-- qu'on la met à jour :
--   docker compose exec -T postgres psql -U noc -d noc < backend/sql/schema.sql

-- ---------------------------------------------------------------------
-- Comptes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS noc_user (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'agent_terrain',
    password_hash   TEXT,
    -- Code court saisi sur mobile par les agents de terrain, distinct du
    -- mot de passe : taper une phrase de passe sur un téléphone, gants aux
    -- mains, au sommet d'un pylône, n'est pas réaliste.
    pin_hash        TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    -- Rattachement géographique et organisationnel, en TEXTE et non par
    -- clé étrangère : la géographie appartient désormais aux outils
    -- sources (groupes Zabbix/Centreon, Location iTop), et le NOC n'en
    -- tient plus de référentiel propre qui divergerait du leur.
    site            TEXT,
    organisation    TEXT,
    phone_number    TEXT,
    employee_code   TEXT,
    team            TEXT,
    -- Adresse de notification. Distincte de l'identifiant : un agent peut
    -- vouloir recevoir les alertes sur une boîte d'astreinte plutôt que la
    -- sienne.
    email           TEXT,
    -- Abonnement aux alertes graves par courriel. Désactivé par défaut :
    -- une alerte que tout le monde reçoit est une alerte que personne ne lit.
    notify_email    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Colonnes apparues après la première mise en service. CREATE TABLE IF NOT
-- EXISTS ne modifie pas une table existante : sans ces ALTER, une base créée
-- avant leur ajout resterait sans elles.
ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS email TEXT;
-- Mot de passe provisoire (compte créé ou réinitialisé par un tiers) : à changer
-- avant toute autre action.
ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS notify_email BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_noc_user_role ON noc_user(role) WHERE is_active;

-- ---------------------------------------------------------------------
-- Engagements de service
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_sla_target (
    id                      SERIAL PRIMARY KEY,
    severity                TEXT NOT NULL UNIQUE,
    tta_target_minutes      INTEGER NOT NULL,
    ttr_target_minutes      INTEGER NOT NULL,
    availability_target_pct DOUBLE PRECISION NOT NULL DEFAULT 99.0
);

-- Valeurs de départ, alignées sur les pratiques courantes d'un NOC.
-- Elles sont là pour que les écrans SLA ne soient pas vides au premier
-- démarrage ; l'agence les ajuste dans l'interface. Ce ne sont pas des
-- données fictives : ce sont des paramètres, et un paramètre a une
-- valeur par défaut.
INSERT INTO ops_sla_target (severity, tta_target_minutes, ttr_target_minutes, availability_target_pct)
VALUES
    ('critical', 15,  240,  99.9),
    ('high',     30,  480,  99.5),
    ('medium',   120, 1440, 99.0),
    ('low',      480, 4320, 98.0)
ON CONFLICT (severity) DO NOTHING;

-- ---------------------------------------------------------------------
-- Notifications
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_push_subscription (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES noc_user(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops_notification_log (
    id          SERIAL PRIMARY KEY,
    alert_key   TEXT,
    channel     TEXT NOT NULL,
    recipient   TEXT,
    status      TEXT NOT NULL,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_notification_alert
    ON ops_notification_log(alert_key, created_at DESC);

-- Empêche la double notification d'une même alerte. La contrainte
-- d'unicité EST le verrou : deux backends qui traiteraient la même alerte
-- au même instant, l'un des deux se verra refuser l'insertion et
-- n'enverra rien. C'est plus sûr qu'un verrou applicatif, qui ne survit
-- pas à un redémarrage.
CREATE TABLE IF NOT EXISTS ops_alert_notified (
    alert_key   TEXT PRIMARY KEY,
    notified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Envois échoués en attente d'une nouvelle tentative (serveur SMTP ou
-- passerelle SMS indisponible). ops_alert_notified décide QUI envoie ; cette
-- table garde ce qui n'est pas parti. Un backend prend une ligne échue
-- avec FOR UPDATE SKIP LOCKED : deux backends ne retentent jamais le même
-- envoi. Courriel : destinataires relus à chaque tentative ; SMS : seuls
-- les numéros encore en échec sont gardés.
CREATE TABLE IF NOT EXISTS ops_notification_retry (
    id              SERIAL PRIMARY KEY,
    alert_key       TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK (channel IN ('email', 'sms')),
    subject         TEXT,
    text_body       TEXT NOT NULL,
    html_body       TEXT,
    site            TEXT,
    recipients      TEXT,
    attempts        INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'abandoned')),
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (alert_key, channel)
);

CREATE INDEX IF NOT EXISTS idx_ops_notification_retry_due
    ON ops_notification_retry(status, next_attempt_at);

-- ---------------------------------------------------------------------
-- Journal d'audit
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_audit_log (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    detail      JSONB,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_audit_created
    ON ops_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_audit_user
    ON ops_audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_audit_action
    ON ops_audit_log(action, created_at DESC);

-- ---------------------------------------------------------------------
-- Agrégats journaliers
-- ---------------------------------------------------------------------
-- Écrits une fois par jour par le collecteur (collector/rollup.py).
--
-- POURQUOI ILS EXISTENT malgré la règle « on ne recopie pas l'historique » :
-- le tableau Direction demande l'évolution sur douze mois. Y répondre par
-- fédération obligerait à interroger Zabbix, Centreon et iTop sur 365 jours
-- à chaque affichage. Une ligne par jour et par site coûte quelques
-- mégaoctets par an — sans commune mesure avec les millions de lignes
-- quotidiennes de l'ancienne hypertable.
--
-- CE N'EST PAS UNE COPIE DE L'HISTORIQUE : on n'y retrouve aucun incident
-- particulier, seulement des comptes et des moyennes. Pour un incident
-- précis, la réponse reste chez l'outil source. C'est cette frontière qui
-- garde la table petite, et elle doit le rester.
CREATE TABLE IF NOT EXISTS kpi_daily (
    day                     DATE NOT NULL,
    -- NULL = tous sites confondus. Sans cette ligne de total, la somme des
    -- sites ne ferait pas le parc : les équipements sans localité connue
    -- en seraient absents.
    site                    TEXT,
    samples                 INTEGER NOT NULL,
    avg_nodes               DOUBLE PRECISION,
    avg_up                  DOUBLE PRECISION,
    avg_down                DOUBLE PRECISION,
    avg_degraded            DOUBLE PRECISION,
    avg_alerts              DOUBLE PRECISION,
    avg_critical            DOUBLE PRECISION,
    fleet_availability_pct  DOUBLE PRECISION
);

-- La ligne de total porte site=NULL : une PK sur (day, site) interdirait
-- cette valeur. L'index d'expression garantit une seule ligne par jour/site,
-- en traitant NULL comme la valeur vide pour l'unicité.
ALTER TABLE kpi_daily DROP CONSTRAINT IF EXISTS kpi_daily_pkey;
ALTER TABLE kpi_daily ALTER COLUMN site DROP NOT NULL;
DROP INDEX IF EXISTS idx_kpi_daily_total;
UPDATE kpi_daily SET site = NULL WHERE site = '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_daily_day_site
    ON kpi_daily(day, (COALESCE(site, '')));

-- Secondes-équipement où l'équipement répond (en service ou dégradé) et
-- secondes supervisées : une moyenne sur plusieurs jours se pondère par le
-- temps supervisé (INC-01), pas par le nombre de jours.
ALTER TABLE kpi_daily ADD COLUMN IF NOT EXISTS responding_s DOUBLE PRECISION;
ALTER TABLE kpi_daily ADD COLUMN IF NOT EXISTS supervised_s DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_kpi_daily_site
    ON kpi_daily(site, day DESC);

-- ---------------------------------------------------------------------
-- Journal historique (collector/history.py)
-- ---------------------------------------------------------------------
-- La seule exception, assumée, à « ne rien recopier » : non pas les
-- mesures, mais les CHANGEMENTS d'état. Une ligne par période d'état d'un
-- équipement ou d'un lien, une ligne par alerte (ouverture, fermeture).
-- Quelques Mo par mois. C'est ce qui donne la disponibilité par équipement
-- et par lien sur la durée, le MTTR technique, et le recalcul des bilans
-- journaliers manquants.
--
-- Une période ouverte a ended_at NULL. last_seen_at est la dernière
-- observation : au-delà de trois cycles sans observation (collecteur
-- arrêté, outil muet), la période est close à sa dernière observation et le
-- temps qui suit est compté « non observé », jamais « disponible ».
CREATE TABLE IF NOT EXISTS hist_state (
    id              BIGSERIAL PRIMARY KEY,
    subject_kind    TEXT NOT NULL CHECK (subject_kind IN ('node', 'link')),
    subject_id      TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    name            TEXT,
    site            TEXT,
    province        TEXT,
    region          TEXT,
    tools           TEXT,
    state           TEXT NOT NULL,
    measured_state  TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ NOT NULL
);

-- Une seule période ouverte par sujet : deux collecteurs lancés par erreur
-- ne peuvent pas ouvrir deux périodes concurrentes.
CREATE UNIQUE INDEX IF NOT EXISTS idx_hist_state_open
    ON hist_state(subject_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_hist_state_subject
    ON hist_state(subject_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_state_node
    ON hist_state(node_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_state_window
    ON hist_state(subject_kind, started_at, ended_at);

CREATE TABLE IF NOT EXISTS hist_alert (
    id              BIGSERIAL PRIMARY KEY,
    alert_key       TEXT NOT NULL,
    tool            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    node_id         TEXT,
    node_name       TEXT,
    site            TEXT,
    province        TEXT,
    region          TEXT,
    severity        TEXT NOT NULL,
    message         TEXT,
    opened_at       TIMESTAMPTZ NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hist_alert_open
    ON hist_alert(alert_key) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_hist_alert_node
    ON hist_alert(node_id, opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_alert_window
    ON hist_alert(opened_at, closed_at);

-- Acquittement de l'alerte. acknowledged : état actuel, NULL tant que le
-- collecteur ne l'a pas lu (lignes antérieures à ces colonnes).
-- acknowledged_at : PREMIER acquittement, jamais réécrit. ack_source dit ce
-- que vaut cette date : tool (datée par l'outil), observed (vue au cycle, à
-- COLLECT_INTERVAL_S près), undated (date inconnue, hors MTTA).
ALTER TABLE hist_alert ADD COLUMN IF NOT EXISTS acknowledged BOOLEAN;
ALTER TABLE hist_alert ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
ALTER TABLE hist_alert ADD COLUMN IF NOT EXISTS acknowledged_by TEXT;
ALTER TABLE hist_alert ADD COLUMN IF NOT EXISTS ack_source TEXT;
CREATE INDEX IF NOT EXISTS idx_hist_alert_ack
    ON hist_alert(acknowledged_at) WHERE acknowledged_at IS NOT NULL;

-- Vie de l'alerte : une ligne par changement (ouverture, acquittement,
-- gravité, fermeture). Ajout seulement, rien n'y est réécrit.
CREATE TABLE IF NOT EXISTS hist_alert_event (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        BIGINT NOT NULL REFERENCES hist_alert(id) ON DELETE CASCADE,
    event           TEXT NOT NULL CHECK (event IN
                    ('opened', 'acknowledged', 'unacknowledged', 'severity', 'closed')),
    at              TIMESTAMPTZ NOT NULL,
    from_value      TEXT,
    to_value        TEXT,
    actor           TEXT,
    source          TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hist_alert_event_alert
    ON hist_alert_event(alert_id, at);
CREATE INDEX IF NOT EXISTS idx_hist_alert_event_at
    ON hist_alert_event(at);

-- ---------------------------------------------------------------------
-- Identité des équipements (collector/identity.py)
-- ---------------------------------------------------------------------
-- Registre d'identité : un identifiant par équipement, donné une fois. id est
-- opaque (celui de la fusion au moment de la création). merged_into : réuni à
-- un autre équipement, qui continue.
CREATE TABLE IF NOT EXISTS noc_asset (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL,
    merged_into     TEXT REFERENCES noc_asset(id)
);
CREATE INDEX IF NOT EXISTS idx_noc_asset_seen ON noc_asset(last_seen_at);

-- À quel équipement appartient chaque référence d'outil. valid_from : la
-- référence a été réattribuée à cette date ; avant, elle désignait un autre.
CREATE TABLE IF NOT EXISTS noc_asset_source (
    tool            TEXT NOT NULL,
    ref             TEXT NOT NULL,
    asset_id        TEXT NOT NULL REFERENCES noc_asset(id),
    name            TEXT,
    ip              TEXT,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    valid_from      TIMESTAMPTZ,
    PRIMARY KEY (tool, ref)
);
CREATE INDEX IF NOT EXISTS idx_noc_asset_source_asset ON noc_asset_source(asset_id);

-- Décisions d'identité, en ajout seulement.
CREATE TABLE IF NOT EXISTS noc_asset_event (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        TEXT NOT NULL REFERENCES noc_asset(id),
    event           TEXT NOT NULL,
    at              TIMESTAMPTZ NOT NULL,
    source          TEXT,
    from_value      TEXT,
    to_value        TEXT
);
CREATE INDEX IF NOT EXISTS idx_noc_asset_event_asset ON noc_asset_event(asset_id, at);
CREATE INDEX IF NOT EXISTS idx_noc_asset_event_at ON noc_asset_event(at);

-- ---------------------------------------------------------------------
-- Santé des outils, rapports figés
-- ---------------------------------------------------------------------
-- Santé des outils dans le temps (collector/tool_health.py).
CREATE TABLE IF NOT EXISTS hist_tool_health (
    id              BIGSERIAL PRIMARY KEY,
    tool            TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('up', 'partial', 'down')),
    error           TEXT,
    version         TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hist_tool_health_open
    ON hist_tool_health(tool) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_hist_tool_health_window
    ON hist_tool_health(started_at, ended_at);

-- Rapports mensuels figés (backend, report_archive_service.py). data est du
-- TEXTE : son empreinte porte sur les octets exacts.
CREATE TABLE IF NOT EXISTS report_snapshot (
    id              SERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    revision        INTEGER NOT NULL,
    complete        BOOLEAN NOT NULL,
    reason          TEXT,
    data            TEXT NOT NULL,
    data_sha256     TEXT NOT NULL,
    pdf             BYTEA NOT NULL,
    pdf_sha256      TEXT NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL,
    generated_by    TEXT NOT NULL,
    UNIQUE (kind, year, month, revision)
);
CREATE OR REPLACE FUNCTION refuse_report_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'un rapport figé ne se modifie ni ne se supprime';
END $$;
CREATE OR REPLACE TRIGGER report_snapshot_frozen
    BEFORE UPDATE OR DELETE ON report_snapshot
    FOR EACH ROW EXECUTE FUNCTION refuse_report_change();
CREATE OR REPLACE TRIGGER report_snapshot_no_truncate
    BEFORE TRUNCATE ON report_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_report_change();

-- ---------------------------------------------------------------------
-- Pannes enregistrées par les outils (collector/downtime.py)
-- ---------------------------------------------------------------------
-- Copie, à la seconde, du journal de pannes de NetXMS (downtime_log) : la
-- source maître de la disponibilité des équipements NetXMS. Une ligne par
-- panne ; ended_at NULL = panne en cours. Relue et mise à jour à chaque
-- synchronisation (une panne close voit sa fin enregistrée).
CREATE TABLE IF NOT EXISTS hist_downtime (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    object_ref      TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    name            TEXT,
    tag             TEXT NOT NULL DEFAULT '',
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, object_ref, tag, started_at)
);
CREATE INDEX IF NOT EXISTS idx_hist_downtime_node
    ON hist_downtime(node_id, started_at);

-- Dernière synchronisation réussie, par source : au-delà de quelques heures
-- sans succès, le NOC revient à ses propres observations.
CREATE TABLE IF NOT EXISTS hist_source_sync (
    source          TEXT PRIMARY KEY,
    synced_at       TIMESTAMPTZ NOT NULL,
    rows_read       INTEGER NOT NULL DEFAULT 0
);

-- Fenêtre de supervision de chaque équipement selon sa source maître
-- (NetXMS : date de création de l'objet). Permet d'exploiter tout
-- l'historique de hist_downtime, y compris avant que le NOC observe
-- l'équipement. horizon_at (hist_source_sync) : jusqu'où la source sait.
CREATE TABLE IF NOT EXISTS hist_source_object (
    source          TEXT NOT NULL,
    object_ref      TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    name            TEXT,
    site            TEXT,
    province        TEXT,
    region          TEXT,
    tools           TEXT,
    supervised_since TIMESTAMPTZ,
    managed         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, object_ref)
);
CREATE INDEX IF NOT EXISTS idx_hist_source_object_node
    ON hist_source_object(source, node_id);
ALTER TABLE hist_source_sync ADD COLUMN IF NOT EXISTS horizon_at TIMESTAMPTZ;
-- Depuis quand le journal de pannes copié est complet (NetXMS efface les
-- pannes terminées au-delà de sa rétention ; le NOC garde tout ce qu'il a
-- copié, donc cette date ne fait que reculer — LEAST à chaque synchronisation).
ALTER TABLE hist_source_sync ADD COLUMN IF NOT EXISTS complete_since TIMESTAMPTZ;

-- ---------------------------------------------------------------------
-- Tables retirées
-- ---------------------------------------------------------------------
-- Toutes les données d'exploitation viennent désormais des outils : les
-- alertes s'acquittent et se résolvent dans l'outil ou dans iTop, les
-- incidents ne se signalent plus à la main, maintenances et interventions
-- se lisent dans iTop et Zabbix. Supprimées ici pour qu'une base existante
-- soit mise à jour en rejouant ce fichier (migration 0004 pour Alembic).
DROP TABLE IF EXISTS ops_alert_timeline;
DROP TABLE IF EXISTS ops_alert_state;
DROP TABLE IF EXISTS ops_manual_incident;
DROP TABLE IF EXISTS ops_maintenance_window;
DROP TABLE IF EXISTS ops_field_intervention;
