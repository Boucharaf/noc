-- Dimensions de l'entrepôt NOC.
-- Découpage ministère/région/localité laissé volontairement souple
-- (external_ref nullable, pas de contrainte de hiérarchie stricte) :
-- il sera affiné une fois la hiérarchie réelle RESINA confirmée. Voir
-- scripts/discover_geography.py qui la déduit de ce que les API renvoient
-- plutôt que de l'imposer a priori.

CREATE TABLE IF NOT EXISTS dim_ministry (
    id          SERIAL PRIMARY KEY,
    external_ref TEXT UNIQUE,   -- org_id iTop, ou identifiant de groupe si iTop absent
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_region (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_locality (
    id          SERIAL PRIMARY KEY,
    external_ref TEXT UNIQUE,  -- location_id iTop si disponible
    region_id   INT REFERENCES dim_region(id),
    code        TEXT,
    name        TEXT NOT NULL,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS dim_node (
    id          SERIAL PRIMARY KEY,
    ministry_id INT REFERENCES dim_ministry(id),
    locality_id INT REFERENCES dim_locality(id),
    name        TEXT NOT NULL,
    ip_address  TEXT,
    node_type   TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (name, ip_address)
);

CREATE TABLE IF NOT EXISTS dim_link (
    id                      SERIAL PRIMARY KEY,
    node_a_id               INT REFERENCES dim_node(id),
    node_b_id               INT REFERENCES dim_node(id),
    code                    TEXT,
    bandwidth_capacity_mbps DOUBLE PRECISION
);

-- Correspondance d'identité inter-outils : un dim_node peut avoir
-- plusieurs lignes ici (une par outil qui le supervise).
CREATE TABLE IF NOT EXISTS dim_node_source_map (
    node_id       INT NOT NULL REFERENCES dim_node(id),
    source_tool   TEXT NOT NULL,
    external_ref  TEXT NOT NULL,
    PRIMARY KEY (source_tool, external_ref)
);
CREATE INDEX IF NOT EXISTS idx_node_source_map_node ON dim_node_source_map(node_id);

CREATE TABLE IF NOT EXISTS dim_cause (
    id       SERIAL PRIMARY KEY,
    category TEXT UNIQUE NOT NULL,
    label    TEXT
);

CREATE TABLE IF NOT EXISTS dim_user (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    full_name     TEXT,
    role          TEXT NOT NULL,   -- directeur | chef_noc | technicien | agent_terrain
    password_hash TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ
);
