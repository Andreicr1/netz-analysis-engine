"""Drop legacy allocation_block aliases (fi_aggregate, fi_high_yield, fi_tips).

Three legacy block_ids shared benchmark_ticker with the current regional
naming (fi_us_aggregate, fi_us_high_yield, fi_us_tips), producing duplicate
(nav_date, ticker) rows in the factor_model_service pivot and silently
breaking the factor-model fallback path since at least 2026-04-17 09:51 UTC.

Verified 2026-04-17 pre-migration:
  - zero references in instruments_org
  - zero references in strategic_allocation
  - 100% identical return_1d + nav across legacy vs current benchmark_nav
    (AGG 5,670 rows, HYG 4,781 rows, TIP 5,621 rows — 16,072 total)

Data-only migration; no schema change. No reliable downgrade path —
restore from backup if rollback is required.

Revision ID: 0144_drop_legacy_allocation_block_aliases
Revises: 0143_cvar_profile_defaults
Create Date: 2026-04-17
"""
from __future__ import annotations

from alembic import op

revision = "0144_drop_legacy_allocation_block_aliases"
down_revision = "0143_cvar_profile_defaults"
branch_labels = None
depends_on = None

_LEGACY_BLOCKS_SQL = "('fi_aggregate', 'fi_high_yield', 'fi_tips')"


def upgrade() -> None:
    # Step 1: remove duplicate benchmark_nav rows pointing at legacy blocks.
    op.execute(f"""
        DELETE FROM benchmark_nav
        WHERE block_id IN {_LEGACY_BLOCKS_SQL};
    """)
    # Step 2: remove the legacy allocation_blocks rows themselves.
    op.execute(f"""
        DELETE FROM allocation_blocks
        WHERE block_id IN {_LEGACY_BLOCKS_SQL};
    """)


def downgrade() -> None:
    # Cannot reliably reconstruct legacy rows from current state without the
    # exact historical seed data. Restore from backup if a rollback is needed.
    pass
