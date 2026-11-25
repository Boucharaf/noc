"""Time weights of the daily availability.

Revision ID: 0013_availability_weights
Revises: 0012_must_change_password
Create Date: 2026-11-24
"""

from alembic import op

revision = "0013_availability_weights"
down_revision = "0012_must_change_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE kpi_daily ADD COLUMN IF NOT EXISTS responding_s DOUBLE PRECISION")
    op.execute("ALTER TABLE kpi_daily ADD COLUMN IF NOT EXISTS supervised_s DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE kpi_daily DROP COLUMN IF EXISTS supervised_s")
    op.execute("ALTER TABLE kpi_daily DROP COLUMN IF EXISTS responding_s")
