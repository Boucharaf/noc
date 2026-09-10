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
-- CE QUI RESTE tient en une règle : on ne persiste QUE ce qu'aucun outil
-- source ne saurait nous redonner. Un technicien qui acquitte à 3 h 12
-- avec un commentaire produit une information qui n'existe nulle part
-- ailleurs ; la perdre serait irrattrapable.
--
-- LE CHANGEMENT DE CLÉ, à comprendre avant de lire la suite. L'ancien
-- schéma désignait un incident par `fact_incident.id`, un entier de SA
-- table. Cette table n'existe plus : une alerte est maintenant identifiée
-- par la clé que le collecteur lui donne, `<outil>:<référence>` — par
-- exemple `zabbix:1042`. De même pour un équipement, `<outil>:<réf>` de
-- l'outil qui a servi de pivot à la fusion. Toutes les colonnes de liaison
-- sont donc du TEXTE et non des entiers, et il n'y a PAS de clé étrangère
-- vers l'objet désigné : celui-ci vit dans Redis, ou chez l'outil source.
--
-- Conséquence assumée : une note peut survivre à l'alerte qu'elle
-- commente. C'est voulu — l'historique d'exploitation du NOC doit
-- persister même quand Zabbix a purgé l'événement d'origine.

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
-- avant leur ajout resterait sans elles. Ce fichier se rejoue donc sans
-- danger sur une base en service, et c'est ainsi qu'on la met à jour :
--   docker compose exec -T postgres psql -U noc -d noc < backend/sql/schema.sql
ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS notify_email BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_noc_user_role ON noc_user(role) WHERE is_active;

-- ---------------------------------------------------------------------
-- Travail du NOC sur une alerte
-- ---------------------------------------------------------------------
-- Une ligne par alerte que le NOC a touchée. Les alertes jamais touchées
-- n'ont PAS de ligne ici : la table ne double pas l'instantané Redis,
-- elle ne porte que la valeur ajoutée humaine.
CREATE TABLE IF NOT EXISTS ops_alert_state (
    alert_key            TEXT PRIMARY KEY,
    -- Recopiés au moment de la prise en charge pour que la fiche reste
    -- lisible quand l'alerte a disparu de l'instantané. C'est la SEULE
    -- duplication tolérée, et elle est figée : on ne la rafraîchit jamais.
    node_key             TEXT,
    node_name            TEXT,
    severity_at_pickup   TEXT,
    message_at_pickup    TEXT,
    detected_at          TIMESTAMPTZ,

    acknowledged_by      INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    acknowledged_at      TIMESTAMPTZ,
    assigned_to          INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    assigned_at          TIMESTAMPTZ,
    escalation_level     INTEGER NOT NULL DEFAULT 0,
    escalated_at         TIMESTAMPTZ,
    -- Cause retenue par l'exploitant. Aucun outil ne la connaît : c'est un
    -- diagnostic humain, et c'est la donnée la plus précieuse de ce schéma.
    cause                TEXT,
    resolution_note      TEXT,
    resolved_at          TIMESTAMPTZ,
    -- Ticket ITSM ouvert depuis le NOC, quand il l'a été.
    ticket_ref           TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_alert_state_assigned
    ON ops_alert_state(assigned_to) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_ops_alert_state_detected
    ON ops_alert_state(detected_at DESC);

-- Journal des actions. Séparé de l'état ci-dessus parce que l'état répond
-- à « où en est-on ? » et le journal à « que s'est-il passé ? » — deux
-- questions distinctes, l'une écrasée à chaque changement, l'autre jamais.
CREATE TABLE IF NOT EXISTS ops_alert_timeline (
    id          SERIAL PRIMARY KEY,
    alert_key   TEXT NOT NULL,
    user_id     INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_timeline_alert
    ON ops_alert_timeline(alert_key, created_at DESC);

-- ---------------------------------------------------------------------
-- Incidents signalés à la main
-- ---------------------------------------------------------------------
-- Un agent de terrain constate une coupure qu'aucune sonde ne voit
-- (câble sectionné sur un site sans supervision, groupe électrogène en
-- panne). Ces incidents n'ont pas d'outil source : ils vivent ici, et le
-- backend les fusionne avec les alertes de l'instantané au moment de
-- servir le mur d'alertes.
CREATE TABLE IF NOT EXISTS ops_manual_incident (
    id              SERIAL PRIMARY KEY,
    node_key        TEXT,
    node_name       TEXT,
    site            TEXT,
    severity        TEXT NOT NULL DEFAULT 'medium',
    title           TEXT NOT NULL,
    description     TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    created_by      INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_manual_open
    ON ops_manual_incident(detected_at DESC) WHERE resolved_at IS NULL;

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
-- Maintenances planifiées
-- ---------------------------------------------------------------------
-- Les alertes qui tombent dans une fenêtre active sont marquées comme
-- telles et exclues des indicateurs : une coupure voulue n'est pas une
-- panne, et la compter fausse à la fois le volume d'incidents et le SLA.
CREATE TABLE IF NOT EXISTS ops_maintenance_window (
    id              SERIAL PRIMARY KEY,
    node_key        TEXT,
    site            TEXT,
    reason          TEXT NOT NULL,
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    suppress_alerts BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Une fenêtre doit couvrir un équipement OU un site, jamais ni l'un ni
    -- l'autre : sans cette contrainte, une fenêtre vide s'appliquerait à
    -- tout le parc et éteindrait la supervision entière.
    CONSTRAINT ops_maintenance_scope
        CHECK (node_key IS NOT NULL OR site IS NOT NULL),
    CONSTRAINT ops_maintenance_period CHECK (ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS idx_ops_maintenance_active
    ON ops_maintenance_window(starts_at, ends_at);

-- ---------------------------------------------------------------------
-- Interventions de terrain
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_field_intervention (
    id                  SERIAL PRIMARY KEY,
    alert_key           TEXT,
    node_key            TEXT NOT NULL,
    node_name           TEXT,
    agent_user_id       INTEGER NOT NULL REFERENCES noc_user(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'scheduled',
    scheduled_at        TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    -- Position relevée au pointage, pour attester la présence sur site.
    checkin_latitude    DOUBLE PRECISION,
    checkin_longitude   DOUBLE PRECISION,
    report_text         TEXT,
    photo_urls          JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_field_agent
    ON ops_field_intervention(agent_user_id, status);

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
    fleet_availability_pct  DOUBLE PRECISION,
    PRIMARY KEY (day, site)
);

-- PostgreSQL considère deux NULL comme distincts dans une clé primaire,
-- ce qui autoriserait plusieurs lignes « tous sites » pour un même jour et
-- ferait échouer le ON CONFLICT du collecteur. Cet index unique partiel
-- rétablit la contrainte pour la ligne de total.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_daily_total
    ON kpi_daily(day) WHERE site IS NULL;

CREATE INDEX IF NOT EXISTS idx_kpi_daily_site
    ON kpi_daily(site, day DESC);
