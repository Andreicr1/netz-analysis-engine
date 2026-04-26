"""add_factor_source_blocks_iwf_efa

Revision ID: 0184_factor_source_blocks
Revises: 0183_mv_unified_funds_ucits_share_classes
Create Date: 2026-04-26

PR-Q28 — Add IWF (Russell 1000 Growth Factor) and EFA (MSCI EAFE) as
factor-source allocation blocks. These blocks are NOT used in strategic
allocation templates; they exist purely so benchmark_ingest worker fetches
their NAV time-series into benchmark_nav, which the fundamental factor
model requires for the value factor (IWD-IWF) and international factor
(EFA-SPY).

Without this fix, factor_model_service silently degrades to 6/8 factors,
producing ill-conditioned covariance and forcing all 3 construction
profiles to fall to heuristic fallback.

Pre-merge dry-run findings (orchestrator, 2026-04-26):

1. ``geography`` is lowercase by convention — using ``'north_america'`` and
   ``'global'`` (matching the 18 canonical blocks from migration 0153).
   Uppercase ``'US'`` / ``'INTL'`` would persist but break consistency.

2. ``is_canonical=false`` is INTENTIONAL. The trigger
   ``trg_enforce_allocation_template_sa`` (AFTER INSERT on
   ``strategic_allocation``) auto-populates new ``(organization_id, profile)``
   tuples with every block where ``is_canonical=true``. Marking these
   factor-source blocks canonical would silently inject IWF/EFA into every
   newly onboarded client's strategic allocation template with
   ``target_weight=NULL`` — an institutional silent-corruption pattern.

Filters that matter for the consumers:
- ``benchmark_ingest._do_ingest`` filters by ``is_active=true AND benchmark_ticker IS NOT NULL`` (no canonical check). Confirmed at ``benchmark_ingest.py:85-88``.
- ``factor_model_service`` joins ``benchmark_nav`` to ``allocation_blocks``
  by ``block_id`` and filters by ``benchmark_ticker``. Confirmed at
  ``factor_model_service.py:66-77``. No canonical check.

Both consumers will pick up the new blocks regardless of canonical status.

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
            'north_america',
            'equity',
            'US Growth Factor (factor source)',
            'Russell 1000 Growth ETF (IWF). Factor-model NAV source only — not used in strategic allocation templates. Required for the value factor spread (IWD - IWF) in factor_model_service. is_canonical=false intentionally to bypass strategic_allocation auto-populate trigger (trg_enforce_allocation_template_sa).',
            'IWF',
            true,
            false,
            now(),
            now()
        ),
        (
            'factor_source_intl_developed',
            'global',
            'equity',
            'Intl Developed Broad (factor source)',
            'iShares MSCI EAFE ETF (EFA). Factor-model NAV source only — not used in strategic allocation templates. Required for the international factor spread (EFA - SPY) in factor_model_service. is_canonical=false intentionally to bypass strategic_allocation auto-populate trigger.',
            'EFA',
            true,
            false,
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
