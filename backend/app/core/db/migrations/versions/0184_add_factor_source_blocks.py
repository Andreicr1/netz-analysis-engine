"""add_factor_source_blocks_iwf_efa

Revision ID: 0184_factor_source_blocks
Revises: 0183_mv_unified_funds_ucits_share_classes
Create Date: 2026-04-26

PR-Q28 — Add IWF (Russell 1000 Growth Factor) and EFA (MSCI EAFE) as
canonical factor-source allocation blocks. These blocks are NOT used in
strategic allocation templates; they exist purely so benchmark_ingest
worker fetches their NAV time-series into benchmark_nav, which the
fundamental factor model requires for the value factor (IWD-IWF) and
international factor (EFA-SPY).

Without this fix, factor_model_service silently degrades to 6/8 factors,
producing ill-conditioned covariance and forcing all 3 construction
profiles to fall to heuristic fallback.

Reference: docs/audits/construction-pipeline-runtime-validation.md F04.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0184_factor_source_blocks"
down_revision: str | None = "0183_mv_unified_funds_ucits_share_classes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO allocation_blocks (
            block_id,
            geography,
            asset_class,
            display_name,
            description,
            benchmark_ticker,
            is_active,
            is_canonical,
            created_at,
            updated_at
        ) VALUES
        (
            'factor_source_us_growth',
            'US',
            'equity',
            'US Growth Factor (factor source)',
            'Russell 1000 Growth ETF (IWF). Factor-model NAV source only — not used in strategic allocation templates. Required for the value factor spread (IWD - IWF) in factor_model_service.',
            'IWF',
            true,
            true,
            now(),
            now()
        ),
        (
            'factor_source_intl_developed',
            'INTL',
            'equity',
            'Intl Developed Broad (factor source)',
            'iShares MSCI EAFE ETF (EFA). Factor-model NAV source only — not used in strategic allocation templates. Required for the international factor spread (EFA - SPY) in factor_model_service.',
            'EFA',
            true,
            true,
            now(),
            now()
        )
        ON CONFLICT (block_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM allocation_blocks
        WHERE block_id IN ('factor_source_us_growth', 'factor_source_intl_developed');
    """)
