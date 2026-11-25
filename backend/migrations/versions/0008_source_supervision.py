"""Supervision windows of source objects (collector/downtime.py).

NetXMS knows since when it supervises each node (object creation time) and up
to when its database knows anything (horizon). With them, the whole history of
hist_downtime is usable, including before the NOC itself observed the node.

Revision ID: 0008_source_supervision
Revises: 0007_source_downtime
Create Date: 2026-11-22
"""

from alembic import op

revision = "0008_source_supervision"
down_revision = "0007_source_downtime"
branch_labels = None
depends_on = None

_SQL = """
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
"""


def upgrade() -> None:
    for statement in (part.strip() for part in _SQL.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))


def downgrade() -> None:
    op.execute("ALTER TABLE hist_source_sync DROP COLUMN IF EXISTS complete_since")
    op.execute("ALTER TABLE hist_source_sync DROP COLUMN IF EXISTS horizon_at")
    op.execute("DROP TABLE IF EXISTS hist_source_object")
