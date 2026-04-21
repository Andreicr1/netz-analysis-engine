"""Widen audit_events.action from VARCHAR(32) to VARCHAR(64).

Revision ID: 0074_widen_audit_action
Revises: 0073_add_vintage_year
Create Date: 2026-03-30

Fixes StringDataRightTruncationError for action values like
'WEALTH_INGESTION_WORKER_TRIGGERED' (35 chars > 32 limit).
"""
import sqlalchemy as sa

from alembic import op

revision = "0074_widen_audit_action"
down_revision = "0073_add_vintage_year"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_events",
        "action",
        type_=sa.String(64),
        existing_type=sa.String(32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_events",
        "action",
        type_=sa.String(32),
        existing_type=sa.String(64),
        existing_nullable=False,
    )
