"""PR-A18: recalibrate profile-differentiated CVaR defaults to institutional-realistic values.

Updates existing portfolio_calibration rows where cvar_limit matches an A12.2
default (0.0250, 0.0500, 0.0800, 0.1000) to the new PR-A18 values
(0.0500, 0.0750, 0.1000, 0.1250). Operator-customized values (anything
outside that whitelist) are preserved.
"""
from alembic import op

revision = "0145_cvar_profile_defaults_recalibration"
down_revision = "0144_drop_legacy_allocation_block_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE portfolio_calibration pc
        SET cvar_limit = CASE mp.profile
            WHEN 'conservative' THEN 0.0500
            WHEN 'moderate'     THEN 0.0750
            WHEN 'growth'       THEN 0.1000
            WHEN 'aggressive'   THEN 0.1250
            ELSE pc.cvar_limit
        END
        FROM model_portfolios mp
        WHERE pc.portfolio_id = mp.id
          AND pc.cvar_limit IN (0.0250, 0.0500, 0.0800, 0.1000);
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE portfolio_calibration pc
        SET cvar_limit = CASE mp.profile
            WHEN 'conservative' THEN 0.0250
            WHEN 'moderate'     THEN 0.0500
            WHEN 'growth'       THEN 0.0800
            WHEN 'aggressive'   THEN 0.1000
            ELSE pc.cvar_limit
        END
        FROM model_portfolios mp
        WHERE pc.portfolio_id = mp.id
          AND pc.cvar_limit IN (0.0500, 0.0750, 0.1000, 0.1250);
    """)
