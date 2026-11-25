"""Alert acknowledgement and event journal (collector/history.py).

hist_alert keeps the first acknowledgement of each alert; hist_alert_event
keeps every change (opening, acknowledgement, severity, closing).

Revision ID: 0009_alert_events
Revises: 0008_source_supervision
Create Date: 2026-11-24
"""

from alembic import op

revision = "0009_alert_events"
down_revision = "0008_source_supervision"
branch_labels = None
depends_on = None

_SQL = """
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
"""


def upgrade() -> None:
    for statement in (part.strip() for part in _SQL.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hist_alert_event")
    op.execute("DROP INDEX IF EXISTS idx_hist_alert_ack")
    for column in ("ack_source", "acknowledged_by", "acknowledged_at", "acknowledged"):
        op.execute(f"ALTER TABLE hist_alert DROP COLUMN IF EXISTS {column}")
