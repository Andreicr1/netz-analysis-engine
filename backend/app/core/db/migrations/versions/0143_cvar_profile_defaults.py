"""PR-A12.2: profile-differentiated CVaR defaults backfill.

Update existing ``portfolio_calibration`` rows to use the institutional
starting defaults per profile (Conservative 2.5%, Moderate 5%, Growth
8%, Aggressive 10%). Only rows still at the legacy uniform 5% default
are touched — operator-customized values (anything other than ``0.0500``)
are preserved.

No schema change. The migration 0100 server default stays at 0.05 as a
safe fallback for any insert path that bypasses both
``create_portfolio`` and ``_ensure_calibration``; the helper in
``app.domains.wealth.models.model_portfolio.default_cvar_limit_for_profile``
is now the authoritative default for new rows produced by application
code.

Revision ID: 0143_cvar_profile_defaults
Revises: 0142_construction_cascade_telemetry
Create Date: 2026-04-17
"""
from __future__ import annotations

from alembic import op

revision: str = "0143_cvar_profile_defaults"
down_revision: str | None = "0142_construction_cascade_telemetry"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Backfill cvar_limit by profile, preserving operator customizations."""
    op.execute(
        """
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
          AND pc.cvar_limit = 0.0500;
        """,
    )


def downgrade() -> None:
    """Best-effort reverse — restore uniform 5% on non-moderate profiles.

    Cannot distinguish between "we set it" and "operator set it back to
    5%"; acceptable for a cosmetic data backfill.
    """
    op.execute(
        """
        UPDATE portfolio_calibration pc
        SET cvar_limit = 0.0500
        FROM model_portfolios mp
        WHERE pc.portfolio_id = mp.id
          AND mp.profile IN ('conservative', 'growth', 'aggressive');
        """,
    )
