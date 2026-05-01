"""PR-BE-7 — consolidate legacy ``aggressive`` profile/mandate into ``growth``.

Defensive backfill across every wealth surface that historically carried
the ``aggressive`` slug. Per the F1 audit (2026-04-30), the local docker
DB and the Timescale Cloud target both have **zero** rows referencing
the legacy slug — ``aggressive`` was a development artefact, not a
canonical product profile, and never made it into a tenant snapshot.
The migration runs anyway as a one-time hygiene sweep so any developer
fixture or stale environment is brought into line with the
post-PR-BE-7 enum (``conservative`` / ``moderate`` / ``growth``).

The application-layer alias normaliser (introduced alongside this
migration) keeps URL- and mandate-level callers backward compatible
through 2026-10-30 (180 days post-merge); the DB layer is the
authoritative truth source from this revision onward.

Revision ID: 0199_q165_consolidate_aggressive_into_growth
Revises: 0198_q159_rebuild_mv_nport_sector_attribution
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op

# Revision identifiers, used by Alembic.
revision = "0199_q165_consolidate_aggressive_into_growth"
down_revision = "0198_q159_rebuild_mv_nport_sector_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Phase 1 — pre-UPDATE collision dedup (Codex P2/P3 catches) ──
    # Five public-schema tables enforce uniqueness on a key tuple that
    # includes ``profile``. On environments with both ``aggressive``
    # AND ``growth`` rows for the same logical key, the blanket UPDATE
    # in phase 2 would raise a unique-violation and abort the whole
    # migration. Strategy: ``aggressive`` is a development artefact
    # per the F1 audit narrative (2026-04-30); on a true collision we
    # delete the ``aggressive`` row and keep ``growth`` as canonical.
    # Each DELETE is scoped to the same partial-index predicate as
    # the unique constraint it shadows, so non-colliding rows survive
    # and get rewritten in phase 2.
    #
    # Conflict surfaces:
    #   model_portfolios     | uq_model_portfolios_org_profile_active
    #                          (organization_id, profile)
    #                          WHERE status IN ('draft','backtesting','live')
    #   portfolio_snapshots  | uq_portfolio_snapshots_org_profile_date
    #                          (organization_id, profile, snapshot_date)
    #   rebalance_events     | uq_rebalance_event_pending_drift_per_profile
    #                          (organization_id, profile)
    #                          WHERE status='pending'
    #                            AND event_type='drift_rebalance'
    #   taa_regime_state     | uq_taa_regime_state_org_profile_date
    #                          (organization_id, profile, as_of_date)
    #   tactical_positions   | uq_tactical_one_active_per_block
    #                          (organization_id, profile, block_id)
    #                          WHERE valid_to IS NULL

    # model_portfolios — collide on (org, status_active)
    op.execute(
        """
        DELETE FROM model_portfolios mp_a
        WHERE mp_a.profile = 'aggressive'
          AND mp_a.status IN ('draft', 'backtesting', 'live')
          AND EXISTS (
              SELECT 1 FROM model_portfolios mp_g
              WHERE mp_g.organization_id = mp_a.organization_id
                AND mp_g.profile = 'growth'
                AND mp_g.status IN ('draft', 'backtesting', 'live')
          )
        """,
    )

    # portfolio_snapshots — collide on (org, snapshot_date)
    op.execute(
        """
        DELETE FROM portfolio_snapshots ps_a
        WHERE ps_a.profile = 'aggressive'
          AND EXISTS (
              SELECT 1 FROM portfolio_snapshots ps_g
              WHERE ps_g.organization_id = ps_a.organization_id
                AND ps_g.profile = 'growth'
                AND ps_g.snapshot_date = ps_a.snapshot_date
          )
        """,
    )

    # rebalance_events — collide on (org) within pending drift partial index
    op.execute(
        """
        DELETE FROM rebalance_events re_a
        WHERE re_a.profile = 'aggressive'
          AND re_a.status = 'pending'
          AND re_a.event_type = 'drift_rebalance'
          AND EXISTS (
              SELECT 1 FROM rebalance_events re_g
              WHERE re_g.organization_id = re_a.organization_id
                AND re_g.profile = 'growth'
                AND re_g.status = 'pending'
                AND re_g.event_type = 'drift_rebalance'
          )
        """,
    )

    # taa_regime_state — collide on (org, as_of_date)
    op.execute(
        """
        DELETE FROM taa_regime_state ts_a
        WHERE ts_a.profile = 'aggressive'
          AND EXISTS (
              SELECT 1 FROM taa_regime_state ts_g
              WHERE ts_g.organization_id = ts_a.organization_id
                AND ts_g.profile = 'growth'
                AND ts_g.as_of_date = ts_a.as_of_date
          )
        """,
    )

    # tactical_positions — collide on (org, block_id) within active partial index
    op.execute(
        """
        DELETE FROM tactical_positions tp_a
        WHERE tp_a.profile = 'aggressive'
          AND tp_a.valid_to IS NULL
          AND EXISTS (
              SELECT 1 FROM tactical_positions tp_g
              WHERE tp_g.organization_id = tp_a.organization_id
                AND tp_g.profile = 'growth'
                AND tp_g.block_id = tp_a.block_id
                AND tp_g.valid_to IS NULL
          )
        """,
    )

    # ── Phase 2 — full sweep of stored profile slugs ───────────────
    # Every public-schema table with a stored profile slug must be
    # rewritten in lockstep with the route-layer alias normaliser —
    # otherwise queries canonicalised to ``growth`` would silently
    # miss legacy ``aggressive`` rows during the 180-day compatibility
    # window, producing a data-visibility regression (Codex P2 catch
    # on PR #463). Audit source:
    #   SELECT table_name FROM information_schema.columns
    #   WHERE table_schema='public' AND column_name='profile';
    #   SELECT table_name FROM information_schema.columns
    #   WHERE table_schema='public' AND column_name='portfolio_profile';
    _PROFILE_TABLES = (
        "model_portfolios",
        "strategic_allocation",
        "allocation_approvals",
        "allocation_template_audit",
        "backtest_runs",
        "portfolio_snapshots",
        "rebalance_events",
        "taa_regime_state",
        "tactical_positions",
    )
    for table in _PROFILE_TABLES:
        op.execute(
            f"UPDATE {table} SET profile = 'growth' "
            f"WHERE profile = 'aggressive'",
        )

    # Blended benchmarks use ``portfolio_profile`` instead of ``profile``.
    # Keep stored data aligned with ``routes/blended_benchmark.py`` where
    # legacy URL params are canonicalised through ``_validate_profile`` before
    # querying by ``portfolio_profile``.
    op.execute(
        """
        UPDATE blended_benchmarks
        SET portfolio_profile = 'growth'
        WHERE portfolio_profile = 'aggressive'
        """,
    )

    # ── Phase 3 — mandate namespace ────────────────────────────────
    # ``portfolio_calibration.mandate`` is a ``String(64)`` column with
    # no DB-level CHECK constraint and no profile-based uniqueness
    # (UNIQUE on ``portfolio_id`` alone), so the legacy ``aggressive``
    # value is a free-form artefact. Plain UPDATE is collision-free.
    op.execute(
        "UPDATE portfolio_calibration SET mandate = 'growth' WHERE mandate = 'aggressive'",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "PR-BE-7 consolidates the legacy 'aggressive' profile/mandate "
        "into 'growth'. The original distinction was a development "
        "artefact, not a canonical product setting, so a reversible "
        "downgrade would have to invent which rows were originally "
        "'aggressive' vs which were 'growth'. Restore from a "
        "pre-migration backup if you genuinely need the legacy split.",
    )
