"""Alert and state history journal (collector/history.py).

One row per state period of each node and watched link, one row per alert
(opening, closing). Gives per-node and per-link availability over time,
technical MTTR, and rebuilding missing daily aggregates.

Revision ID: 0006_history_journal
Revises: 0005_notification_retry
Create Date: 2026-10-29
"""

from alembic import op

revision = "0006_history_journal"
down_revision = "0005_notification_retry"
branch_labels = None
depends_on = None

_SQL = """
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
"""


def upgrade() -> None:
    for statement in (part.strip() for part in _SQL.split(";")):
        lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
        if "".join(lines).strip():
            op.execute("\n".join(lines))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hist_alert")
    op.execute("DROP TABLE IF EXISTS hist_state")
