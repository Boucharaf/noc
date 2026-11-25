"""Stable equipment identity registry (collector/identity.py).

Revision ID: 0010_asset_identity
Revises: 0009_alert_events
Create Date: 2026-11-24
"""

from alembic import op

revision = "0010_asset_identity"
down_revision = "0009_alert_events"
branch_labels = None
depends_on = None

_SQL = """
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
-- référence a été réattribuée à cette date, avant, elle désignait un autre.
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
"""


def upgrade() -> None:
    for statement in (part.strip() for part in _SQL.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))


def downgrade() -> None:
    for table in ("noc_asset_event", "noc_asset_source", "noc_asset"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
