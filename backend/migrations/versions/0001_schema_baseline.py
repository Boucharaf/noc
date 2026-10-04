"""Baseline for the schema bootstrapped by backend/sql/schema.sql.

Revision ID: 0001_schema_baseline
Revises:
Create Date: 2026-10-04
"""

revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Track the pre-existing bootstrap schema without recreating its tables."""


def downgrade() -> None:
    """The baseline owns no schema objects and has nothing to reverse."""