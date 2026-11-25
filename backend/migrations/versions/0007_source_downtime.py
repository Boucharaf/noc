"""Downtime journal copied from the source tools (collector/downtime.py).

NetXMS records every node outage to the second in its `downtime_log` table.
The NOC copies it here and uses it as the master source of availability for
NetXMS nodes, instead of the outages inferred from its own polling.

Revision ID: 0007_source_downtime
Revises: 0006_history_journal
Create Date: 2026-11-21
"""

from alembic import op

revision = "0007_source_downtime"
down_revision = "0006_history_journal"
branch_labels = None
depends_on = None

_SQL = """
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
"""


def upgrade() -> None:
    for statement in (part.strip() for part in _SQL.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hist_source_sync")
    op.execute("DROP TABLE IF EXISTS hist_downtime")
