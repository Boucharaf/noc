"""Provisional passwords must be changed at first login.

Revision ID: 0012_must_change_password
Revises: 0011_health_and_reports
Create Date: 2026-11-24
"""

from alembic import op

revision = "0012_must_change_password"
down_revision = "0011_health_and_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE noc_user ADD COLUMN IF NOT EXISTS "
        "must_change_password BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE noc_user DROP COLUMN IF EXISTS must_change_password")
