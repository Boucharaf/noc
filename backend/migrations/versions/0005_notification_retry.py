"""Keep failed notifications for retry instead of dropping them.

A failed email or SMS (SMTP or SMS gateway down) used to be logged and never
sent again, because ops_alert_notified had already been claimed. Failed
sends are now kept in ops_notification_retry and retried with backoff.

Revision ID: 0005_notification_retry
Revises: 0004_drop_unused_tables
Create Date: 2026-10-29
"""

from alembic import op

revision = "0005_notification_retry"
down_revision = "0004_drop_unused_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops_notification_retry (
            id              SERIAL PRIMARY KEY,
            alert_key       TEXT NOT NULL,
            channel         TEXT NOT NULL CHECK (channel IN ('email', 'sms')),
            subject         TEXT,
            text_body       TEXT NOT NULL,
            html_body       TEXT,
            site            TEXT,
            recipients      TEXT,
            attempts        INTEGER NOT NULL DEFAULT 1,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sent', 'abandoned')),
            last_error      TEXT,
            next_attempt_at TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (alert_key, channel)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ops_notification_retry_due "
        "ON ops_notification_retry(status, next_attempt_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_notification_retry")
