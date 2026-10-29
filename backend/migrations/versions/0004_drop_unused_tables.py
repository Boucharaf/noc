"""Drop the tables no longer fed since all NOC data comes from the tool APIs.

Alerts are acknowledged and resolved in their tool or in iTop, incidents are
no longer reported by hand, maintenance windows and field interventions are
read from iTop and Zabbix. Also indexes the audit log, now written again.

Revision ID: 0004_drop_unused_tables
Revises: 0003_maintenance_node_selection
Create Date: 2026-10-28
"""

from alembic import op

revision = "0004_drop_unused_tables"
down_revision = "0003_maintenance_node_selection"
branch_labels = None
depends_on = None

_DROPPED = (
    "ops_alert_timeline",
    "ops_alert_state",
    "ops_manual_incident",
    "ops_maintenance_window",
    "ops_field_intervention",
)


def upgrade() -> None:
    for table in _DROPPED:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_audit_user "
        "ON ops_audit_log(user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_audit_action "
        "ON ops_audit_log(action, created_at DESC)"
    )


def downgrade() -> None:
    """Recreates the structures, empty: the dropped rows are not restored."""
    op.execute("DROP INDEX IF EXISTS idx_ops_audit_action")
    op.execute("DROP INDEX IF EXISTS idx_ops_audit_user")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_alert_state (
            alert_key TEXT PRIMARY KEY,
            node_key TEXT, node_name TEXT, severity_at_pickup TEXT,
            message_at_pickup TEXT, detected_at TIMESTAMPTZ,
            acknowledged_by INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
            acknowledged_at TIMESTAMPTZ,
            assigned_to INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
            assigned_at TIMESTAMPTZ,
            escalation_level INTEGER NOT NULL DEFAULT 0, escalated_at TIMESTAMPTZ,
            cause TEXT, resolution_note TEXT, resolved_at TIMESTAMPTZ, ticket_ref TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_alert_timeline (
            id SERIAL PRIMARY KEY, alert_key TEXT NOT NULL,
            user_id INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
            action TEXT NOT NULL, note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_manual_incident (
            id SERIAL PRIMARY KEY, node_key TEXT, node_name TEXT, site TEXT,
            severity TEXT NOT NULL DEFAULT 'medium', title TEXT NOT NULL,
            description TEXT, cause TEXT,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now(), resolved_at TIMESTAMPTZ,
            created_by INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_maintenance_window (
            id SERIAL PRIMARY KEY, node_key TEXT, node_keys JSONB, site TEXT,
            reason TEXT NOT NULL, starts_at TIMESTAMPTZ NOT NULL,
            ends_at TIMESTAMPTZ NOT NULL,
            suppress_alerts BOOLEAN NOT NULL DEFAULT TRUE,
            created_by INTEGER REFERENCES noc_user(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ops_maintenance_scope CHECK (node_key IS NOT NULL OR site IS NOT NULL),
            CONSTRAINT ops_maintenance_period CHECK (ends_at > starts_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_field_intervention (
            id SERIAL PRIMARY KEY, alert_key TEXT, node_key TEXT NOT NULL,
            node_name TEXT,
            agent_user_id INTEGER NOT NULL REFERENCES noc_user(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'scheduled', scheduled_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
            checkin_latitude DOUBLE PRECISION, checkin_longitude DOUBLE PRECISION,
            report_text TEXT, photo_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
