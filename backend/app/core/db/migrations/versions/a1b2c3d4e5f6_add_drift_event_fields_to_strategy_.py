"""add drift event fields to strategy_drift_alerts

Revision ID: a1b2c3d4e5f6
Revises: f5aca0aa8f32
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f5aca0aa8f32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategy_drift_alerts", sa.Column("snapshot_date", sa.Date(), nullable=True))
    op.add_column("strategy_drift_alerts", sa.Column("drift_magnitude", sa.Numeric(10, 6), nullable=True))
    op.add_column("strategy_drift_alerts", sa.Column("drift_threshold", sa.Numeric(10, 6), nullable=True))
    op.add_column("strategy_drift_alerts", sa.Column("rebalance_triggered", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_drift_alerts", "rebalance_triggered")
    op.drop_column("strategy_drift_alerts", "drift_threshold")
    op.drop_column("strategy_drift_alerts", "drift_magnitude")
    op.drop_column("strategy_drift_alerts", "snapshot_date")
