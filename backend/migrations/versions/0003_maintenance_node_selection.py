"""Support selecting multiple equipment in a maintenance window.

Revision ID: 0003_maintenance_node_selection
Revises: 0002_manual_incident_cause
Create Date: 2026-10-05
"""

from alembic import op

revision = "0003_maintenance_node_selection"
down_revision = "0002_manual_incident_cause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ops_maintenance_window "
        "ADD COLUMN IF NOT EXISTS node_keys JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ops_maintenance_window "
        "DROP COLUMN IF EXISTS node_keys"
    )
