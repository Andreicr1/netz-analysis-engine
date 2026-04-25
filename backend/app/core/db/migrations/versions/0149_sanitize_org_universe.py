"""PR-A21 — sanitize org universe (dedup, taxonomy, backfill cleanup).

Applies four corrective steps inside a single transaction:

1. **D3 remap** — every ``instruments_org`` row with ``block_id =
   'fi_govt'`` is rewritten to ``'fi_us_treasury'``. ``fi_govt`` is the
   legacy alias; the canonical block (per ``block_mapping.py`` and the
   ``StrategicAllocation`` seed) is ``fi_us_treasury``.
2. **D1 dedup** — for any ``(organization_id, instrument_id)`` pair
   with more than one row, keep the highest-priority survivor and
   delete the rest. Priority order is chosen to preserve the row with
   the best block assignment and the earliest audit trail.
3. **D2 null cleanup** — delete rows authored by a backfill source
   (``source LIKE '%backfill%'``) that still have ``block_id IS NULL``.
   Those rows are invisible to the candidate screener and are always
   superseded by a real ``universe_auto_import`` row when one exists.
4. **D3 taxonomy retire** — verify no ``strategic_allocation`` row
   targets ``fi_govt`` (abort with a clear error if any do), then
   delete ``fi_govt`` from ``allocation_blocks``.

The down-migration reinstates the ``fi_govt`` row in
``allocation_blocks`` so the schema can be rolled back. Dedup and
row deletions are inherently destructive and cannot be reversed — a
warning is emitted if ``downgrade`` is invoked.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0149_sanitize_org_universe"
down_revision = "0146_canonical_liquid_beta_backfill"
branch_labels = None
depends_on = None


# Canonical attributes for ``fi_govt`` exactly as seeded by migration
# ``0122_add_fi_benchmark_blocks``. Captured here so ``downgrade`` can
# restore the row without reaching across migration boundaries.
_FI_GOVT_ROW = {
    "block_id": "fi_govt",
    "geography": "us",
    "asset_class": "fixed_income",
    "display_name": "US Government Bond",
    "benchmark_ticker": "GOVT",
}


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1 — D3 remap fi_govt → fi_us_treasury ────────────────
    remap_result = conn.execute(
        sa.text(
            """
            UPDATE instruments_org
               SET block_id = 'fi_us_treasury'
             WHERE block_id = 'fi_govt'
            """
        )
    )
    print(
        "pr_a21_step1_d3_remap "
        f"rows_updated={remap_result.rowcount}"
    )

    # ── Step 2 — D1 dedup ─────────────────────────────────────────
    # ROW_NUMBER priority (first match wins, i.e. row_number = 1):
    #   1. ``universe_auto_import`` with a block_id that exists in
    #      ``allocation_blocks`` (most authoritative).
    #   2. Non-backfill source with a non-null block_id.
    #   3. Any row with a non-null block_id.
    #   4. Oldest ``selected_at`` — preserves audit trail.
    dedup_result = conn.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT io.id,
                       ROW_NUMBER() OVER (
                           PARTITION BY io.organization_id, io.instrument_id
                           ORDER BY
                               CASE
                                   WHEN io.source = 'universe_auto_import'
                                        AND io.block_id IS NOT NULL
                                        AND EXISTS (
                                            SELECT 1 FROM allocation_blocks ab
                                             WHERE ab.block_id = io.block_id
                                        )
                                       THEN 0
                                   WHEN (io.source IS NULL
                                         OR io.source NOT LIKE '%backfill%')
                                        AND io.block_id IS NOT NULL
                                       THEN 1
                                   WHEN io.block_id IS NOT NULL THEN 2
                                   ELSE 3
                               END,
                               io.selected_at ASC,
                               io.id ASC
                       ) AS rn
                  FROM instruments_org io
            )
            DELETE FROM instruments_org
             WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    print(
        "pr_a21_step2_d1_dedup "
        f"rows_deleted={dedup_result.rowcount}"
    )

    # ── Step 3 — D2 null cleanup (backfill rows only) ─────────────
    null_cleanup_result = conn.execute(
        sa.text(
            """
            DELETE FROM instruments_org
             WHERE block_id IS NULL
               AND source LIKE '%backfill%'
            """
        )
    )
    print(
        "pr_a21_step3_d2_null_cleanup "
        f"rows_deleted={null_cleanup_result.rowcount}"
    )

    # ── Step 4 — D3 taxonomy retire ────────────────────────────────
    # Dropping ``fi_govt`` from ``allocation_blocks`` requires every
    # FK-referencing row to be dealt with first. Precedent for this
    # pattern is migration 0144 (legacy fi_aggregate/fi_high_yield/
    # fi_tips retirement).
    sa_fi_govt = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM strategic_allocation
             WHERE block_id = 'fi_govt'
            """
        )
    ).scalar_one()
    if sa_fi_govt:
        raise RuntimeError(
            "pr_a21_abort strategic_allocation still references fi_govt "
            f"(n={sa_fi_govt}); refusing to delete block"
        )

    # benchmark_nav for fi_govt tracks the GOVT ETF; fi_us_treasury
    # tracks IEF. The two benchmarks are materially different — do
    # NOT remap rows across them. Delete the fi_govt history; the
    # canonical series is already being accumulated against
    # fi_us_treasury by benchmark_ingest.
    bench_result = conn.execute(
        sa.text(
            """
            DELETE FROM benchmark_nav
             WHERE block_id = 'fi_govt'
            """
        )
    )

    # funds_universe, tactical_positions: remap to fi_us_treasury —
    # these are allocation assignments and the new canonical block
    # carries equivalent semantics.
    fu_result = conn.execute(
        sa.text(
            """
            UPDATE funds_universe
               SET block_id = 'fi_us_treasury'
             WHERE block_id = 'fi_govt'
            """
        )
    )
    tp_result = conn.execute(
        sa.text(
            """
            UPDATE tactical_positions
               SET block_id = 'fi_us_treasury'
             WHERE block_id = 'fi_govt'
            """
        )
    )

    # blended_benchmark_components row for fi_govt was a weight
    # pointing at the retired benchmark — drop it rather than
    # remapping (different underlying ticker).
    bbc_result = conn.execute(
        sa.text(
            """
            DELETE FROM blended_benchmark_components
             WHERE block_id = 'fi_govt'
            """
        )
    )

    drop_result = conn.execute(
        sa.text(
            """
            DELETE FROM allocation_blocks
             WHERE block_id = 'fi_govt'
            """
        )
    )
    print(
        "pr_a21_step4_taxonomy_retire "
        f"benchmark_nav_deleted={bench_result.rowcount} "
        f"funds_universe_remapped={fu_result.rowcount} "
        f"tactical_positions_remapped={tp_result.rowcount} "
        f"blended_benchmark_components_deleted={bbc_result.rowcount} "
        f"allocation_blocks_deleted={drop_result.rowcount}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Re-insert fi_govt so the FK on instruments_org / strategic_allocation
    # remains satisfiable in a rolled-back world.
    conn.execute(
        sa.text(
            """
            INSERT INTO allocation_blocks
                (block_id, geography, asset_class, display_name,
                 benchmark_ticker)
            VALUES
                (:block_id, :geography, :asset_class, :display_name,
                 :benchmark_ticker)
            ON CONFLICT (block_id) DO NOTHING
            """
        ),
        _FI_GOVT_ROW,
    )
    print(
        "pr_a21_downgrade warning=dedup_and_null_cleanup_not_reversible "
        "fi_govt_block_restored=true"
    )
