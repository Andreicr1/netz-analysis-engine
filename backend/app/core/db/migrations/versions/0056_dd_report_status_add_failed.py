"""Add 'failed' to dd_reports status check constraint.

Revision ID: 0056_dd_report_status_add_failed
Revises: 0055_model_portfolio_nav
Create Date: 2026-03-27
"""

from alembic import op

revision = "0056_dd_report_status_add_failed"
down_revision = "0055_model_portfolio_nav"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dd_reports DROP CONSTRAINT IF EXISTS chk_dd_report_status")
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT chk_dd_report_status
        CHECK (status IN (
            'draft', 'generating', 'critic_review',
            'pending_approval', 'approved', 'rejected', 'failed'
        ))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE dd_reports DROP CONSTRAINT IF EXISTS chk_dd_report_status")
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT chk_dd_report_status
        CHECK (status IN (
            'draft', 'generating', 'critic_review',
            'pending_approval', 'approved', 'rejected'
        ))
    """)
