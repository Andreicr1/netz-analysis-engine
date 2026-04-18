"""PR-A19.1 Section A — canonical liquid beta backfill.

Every wealth-enabled org must have the canonical liquid-beta set
(SPY, IVV, VTI, AGG, BND, IEF, TLT, SHY, GLD, VTEB) approved in
``instruments_org`` so the optimizer universe is never structurally
ill-conditioned.

Pre-A19.1 symptom (evidence file §4): 135-146 fund universes whose
min-achievable CVaR was 7.36-10.08% — no genuinely low-tail asset
(Treasury / IG duration) available. Balanced delivered 0.83% E[r]
at 7.5% CVaR because Phase 1 exhausted the CVaR budget spreading
weight across muni/gold/equity rather than picking SPY with an
AGG sleeve.

Block assignments use the existing ``allocation_blocks`` seed
(migrations 0122 + 0126). Tickers without a matching block
(GLD, VTEB) land with ``block_id=NULL`` and a structured warning;
operators remap via the Builder UI.

Data-only: no schema change. Safe to re-run — INSERT uses
ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0146_canonical_liquid_beta_backfill"
down_revision = "0145_cvar_profile_defaults_recalibration"
branch_labels = None
depends_on = None


# Ticker → existing allocation_blocks.block_id. Derived from migrations
# 0122 (fi_* benchmarks) and 0126 (na_equity_large). Tickers without a
# pre-seeded block map to NULL and a warning is emitted below.
CANONICAL_BLOCK_MAP: dict[str, str | None] = {
    "SPY": "na_equity_large",
    "IVV": "na_equity_large",
    "VTI": "na_equity_large",
    "AGG": "fi_aggregate",
    "BND": "fi_aggregate",
    "IEF": "fi_govt",
    "TLT": "fi_govt",
    "SHY": "fi_short_term",
    "GLD": None,   # no alternatives_gold block in allocation_blocks
    "VTEB": None,  # no fixed_income_muni block in allocation_blocks
}


def upgrade() -> None:
    conn = op.get_bind()

    # Validate every canonical ticker is present in instruments_universe.
    # Hard-fail if missing — upstream universe_sync issue, not this
    # migration's concern.
    values_clause = ", ".join(f"('{t}')" for t in CANONICAL_BLOCK_MAP)
    missing_rows = conn.execute(
        sa.text(
            f"""
            SELECT t.ticker
            FROM (VALUES {values_clause}) AS t(ticker)
            LEFT JOIN instruments_universe iu ON iu.ticker = t.ticker
            WHERE iu.instrument_id IS NULL
            """
        )
    ).fetchall()
    missing: list[str] = [r[0] for r in missing_rows] if missing_rows else []
    if missing:
        # Warn-and-skip (spec revision 2026-04-17): upstream universe_sync
        # gaps must not block backfilling the tickers that ARE present. SPY
        # absence from instruments_org was the root A19.1 complaint — hard-
        # failing on IVV/BND/TLT/SHY would block that fix indefinitely.
        # Missing tickers are tracked separately (universe_sync backlog).
        print(
            f"WARNING canonical_ticker_missing tickers={missing} — "
            "skipped from backfill; upstream universe_sync gap"
        )

    # Warn on missing blocks (non-blocking — NULL block_id is acceptable).
    missing_set = set(missing)
    resolved_map: dict[str, str | None] = {}
    for ticker, block_id in CANONICAL_BLOCK_MAP.items():
        if ticker in missing_set:
            continue  # upstream catalog gap, skip
        if block_id is None:
            resolved_map[ticker] = None
            continue
        exists = conn.execute(
            sa.text("SELECT 1 FROM allocation_blocks WHERE block_id = :bid"),
            {"bid": block_id},
        ).scalar()
        if not exists:
            print(
                f"WARNING canonical_block_missing ticker={ticker} "
                f"block_id={block_id} — inserting with NULL block_id"
            )
            resolved_map[ticker] = None
        else:
            resolved_map[ticker] = block_id

    # Per-org insert. For each organization × canonical ticker pair,
    # insert into instruments_org with approval_status='approved' and
    # source='pr_a19_1_backfill'. ON CONFLICT DO NOTHING preserves any
    # existing operator-chosen block / status.
    for ticker, block_id in resolved_map.items():
        block_expr = "NULL" if block_id is None else f"'{block_id}'"
        op.execute(
            f"""
            INSERT INTO instruments_org
                (organization_id, instrument_id, block_id, approval_status,
                 source, block_overridden)
            SELECT
                o.id,
                iu.instrument_id,
                {block_expr},
                'approved',
                'pr_a19_1_backfill',
                FALSE
            FROM (
                SELECT DISTINCT organization_id AS id FROM instruments_org
                UNION
                SELECT DISTINCT organization_id AS id FROM model_portfolios
            ) o
            CROSS JOIN instruments_universe iu
            WHERE iu.ticker = '{ticker}'
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    # Remove only rows this migration wrote.
    op.execute(
        """
        DELETE FROM instruments_org
        WHERE source = 'pr_a19_1_backfill'
        """
    )
