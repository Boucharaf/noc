"""Add the cause field to manually reported incidents.

Revision ID: 0002_manual_incident_cause
Revises: 0001_schema_baseline
Create Date: 2026-10-05
"""

from alembic import op

revision = "0002_manual_incident_cause"
down_revision = "0001_schema_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ops_manual_incident "
        "ADD COLUMN IF NOT EXISTS cause TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ops_manual_incident "
        "DROP COLUMN IF EXISTS cause"
    )
