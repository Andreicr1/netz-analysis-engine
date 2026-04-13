"""Add per-regime ELITE flags to fund_risk_metrics + source discriminator to tactical_positions.

Sprint 2 of Dynamic TAA system. Three new boolean columns on fund_risk_metrics
for regime-specific ELITE sets (RISK_OFF, INFLATION, CRISIS). Existing elite_flag
serves as RISK_ON set (backward compatible). Source column on tactical_positions
distinguishes ic_manual vs regime_auto vs model_signal origins.

Revision ID: 0129_elite_regime_flags
Revises: 0128_taa_config_seed
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0129_elite_regime_flags"
down_revision = "0128_taa_config_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fund_risk_metrics: per-regime ELITE flags ──
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_risk_off", sa.Boolean(), server_default=sa.text("false"), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_inflation", sa.Boolean(), server_default=sa.text("false"), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_crisis", sa.Boolean(), server_default=sa.text("false"), nullable=True),
    )

    # ── tactical_positions: source discriminator ──
    op.add_column(
        "tactical_positions",
        sa.Column(
            "source",
            sa.String(20),
            server_default=sa.text("'ic_manual'"),
            nullable=True,
        ),
    )
    # CHECK constraint for source values
    op.execute(
        """
        ALTER TABLE tactical_positions
        ADD CONSTRAINT ck_tactical_positions_source
        CHECK (source IN ('ic_manual', 'regime_auto', 'model_signal'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tactical_positions DROP CONSTRAINT IF EXISTS ck_tactical_positions_source")
    op.drop_column("tactical_positions", "source")
    op.drop_column("fund_risk_metrics", "elite_crisis")
    op.drop_column("fund_risk_metrics", "elite_inflation")
    op.drop_column("fund_risk_metrics", "elite_risk_off")
