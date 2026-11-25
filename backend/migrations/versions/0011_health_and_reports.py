"""Tool health history and frozen monthly reports.

Revision ID: 0011_health_and_reports
Revises: 0010_asset_identity
Create Date: 2026-11-24
"""

from alembic import op

revision = "0011_health_and_reports"
down_revision = "0010_asset_identity"
branch_labels = None
depends_on = None

_TABLES = """
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
"""

_FUNCTION = """
CREATE OR REPLACE FUNCTION refuse_report_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'un rapport figé ne se modifie ni ne se supprime';
END $$;
"""

_TRIGGERS = (
    """CREATE OR REPLACE TRIGGER report_snapshot_frozen
    BEFORE UPDATE OR DELETE ON report_snapshot
    FOR EACH ROW EXECUTE FUNCTION refuse_report_change()""",
    """CREATE OR REPLACE TRIGGER report_snapshot_no_truncate
    BEFORE TRUNCATE ON report_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_report_change()""",
)


def upgrade() -> None:
    for statement in (part.strip() for part in _TABLES.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))
    op.execute(_FUNCTION)
    for statement in _TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_snapshot")
    op.execute("DROP FUNCTION IF EXISTS refuse_report_change()")
    op.execute("DROP TABLE IF EXISTS hist_tool_health")
