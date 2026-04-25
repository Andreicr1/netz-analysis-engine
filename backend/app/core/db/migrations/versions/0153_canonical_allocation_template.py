"""PR-A25 — canonical allocation template schema + taxonomy normalization.

Establishes the 18-block canonical template that every `(org, profile)`
pair must share. Profiles differ only in `(target, min, max, risk_budget)`
per block and the profile-level CVaR limit — never in the block set.

2026-04-24 patch: Step 4 inline-seeds the 18 canonical blocks with
ON CONFLICT DO NOTHING so fresh DBs (dev, CI) can run this migration
without an external seed. No-op in prod (rows already exist).

Ordered steps (all inside one transaction):

1. Add ``allocation_blocks.is_canonical`` and
   ``strategic_allocation.excluded_from_portfolio`` columns.
2. Relax NOT NULL on ``strategic_allocation.(target|min|max)_weight`` so
   the backfill can seed rows without forcing arbitrary numeric values —
   PR-A26 will own the propose-then-approve flow that fills them.
3. Rename ``fi_short_term → fi_us_short_term`` across every FK-dependent
   table (same pattern A21 used for ``fi_govt → fi_us_treasury``).
4. Seed missing canonical blocks (ON CONFLICT DO NOTHING — idempotent).
5. Flip ``is_canonical = true`` on the 18 canonical block IDs; assert
   the set is complete.
6. Fix the ``effective_to`` bit-rot that caused the A22 validator to see
   empty allocations in dev (12-day-stale seed).
7. Create the ``allocation_template_audit`` table (global, no RLS).
8. Backfill missing canonical rows into ``strategic_allocation`` for
   every existing ``(organization_id, profile)`` combo — NULL weights,
   ``excluded_from_portfolio = false``, ``actor_source = 'migration_0153'``.
   Matching audit entries written with ``trigger_reason = 'manual_backfill'``.
9. Install triggers:
   - ``trg_enforce_allocation_template_sa`` on INSERT to
     ``strategic_allocation`` auto-populates the remaining canonical rows
     whenever a fresh ``(org, profile)`` combo lands.
   - ``trg_enforce_allocation_template_blocks`` on UPDATE of
     ``allocation_blocks.is_canonical`` → true inserts the newly-canonical
     block across every existing ``(org, profile)``.
   Every trigger action is logged to ``allocation_template_audit``.

``winner_signal = 'template_incomplete'`` is stored free-form in
``cascade_telemetry`` JSONB — no schema change required for the enum;
the Python-side enum extension lives in ``schemas/sanitized.py``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0153_canonical_allocation_template"
down_revision = "0152_exclude_muni_auto_import"
branch_labels = None
depends_on = None


# The 18 canonical allocation blocks — single source of truth for this
# migration. They are seeded inline at Step 4 below (ON CONFLICT DO
# NOTHING — idempotent in prod).
_CANONICAL_BLOCKS: tuple[str, ...] = (
    "na_equity_large",
    "na_equity_growth",
    "na_equity_value",
    "na_equity_small",
    "dm_europe_equity",
    "dm_asia_equity",
    "em_equity",
    "fi_us_aggregate",
    "fi_us_treasury",
    "fi_us_short_term",
    "fi_us_high_yield",
    "fi_us_tips",
    "fi_ig_corporate",
    "fi_em_debt",
    "alt_real_estate",
    "alt_gold",
    "alt_commodities",
    "cash",
)

# Seed data for the 18 canonical blocks. Used by Step 4 to idempotently
# populate fresh DBs (dev, CI, rebuild). ON CONFLICT DO NOTHING makes
# this a no-op in prod where rows already exist.
# (block_id, geography, asset_class, display_name, benchmark_ticker)
_CANONICAL_SEED: tuple[tuple[str, str, str, str, str], ...] = (
    ("na_equity_large",   "north_america",    "equity",       "North America Large Cap Equity",  "SPY"),
    ("na_equity_growth",  "north_america",    "equity",       "North America Growth Equity",     "QQQ"),
    ("na_equity_value",   "north_america",    "equity",       "North America Value Equity",      "IWD"),
    ("na_equity_small",   "north_america",    "equity",       "North America Small Cap Equity",  "IWM"),
    ("dm_europe_equity",  "dm_europe",        "equity",       "Developed Europe Equity",         "VGK"),
    ("dm_asia_equity",    "dm_asia",          "equity",       "Developed Asia Pacific Equity",   "EWJ"),
    ("em_equity",         "emerging_markets", "equity",       "Emerging Markets Equity",         "EEM"),
    ("fi_us_aggregate",   "north_america",    "fixed_income", "US Aggregate Bond",               "AGG"),
    ("fi_us_treasury",    "north_america",    "fixed_income", "US Treasury",                     "IEF"),
    ("fi_us_short_term",  "north_america",    "fixed_income", "US Short Term Treasury",          "SHY"),
    ("fi_us_high_yield",  "north_america",    "fixed_income", "US High Yield",                   "HYG"),
    ("fi_us_tips",        "north_america",    "fixed_income", "US TIPS",                         "TIP"),
    ("fi_ig_corporate",   "north_america",    "fixed_income", "Investment Grade Corporate",      "LQD"),
    ("fi_em_debt",        "emerging_markets", "fixed_income", "Emerging Markets Debt",           "EMB"),
    ("alt_real_estate",   "global",           "alternatives", "Global REITs",                    "VNQ"),
    ("alt_gold",          "global",           "alternatives", "Gold",                            "GLD"),
    ("alt_commodities",   "global",           "alternatives", "Broad Commodities",               "DBC"),
    ("cash",              "global",           "cash",         "Cash / Money Market",             "BIL"),
)

# Tables carrying a FK/logical reference to ``allocation_blocks.block_id``.
# Discovered via grep of ``ForeignKey("allocation_blocks.block_id"…)`` in
# the ORM models as of 2026-04-18. Mirrors migration 0149's list with the
# addition of ``funds_universe`` (fund.py).
_FK_DEPENDENT_TABLES: tuple[str, ...] = (
    "strategic_allocation",
    "instruments_org",
    "benchmark_nav",
    "funds_universe",
    "tactical_positions",
    "blended_benchmark_components",
)


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1 — add columns ─────────────────────────────────────
    op.execute(
        """
        ALTER TABLE allocation_blocks
          ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ADD COLUMN IF NOT EXISTS excluded_from_portfolio BOOLEAN NOT NULL
              DEFAULT false
        """
    )

    # ── Step 2 — relax NOT NULL on weights (backfill seeds NULLs) ──
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ALTER COLUMN target_weight DROP NOT NULL,
          ALTER COLUMN min_weight DROP NOT NULL,
          ALTER COLUMN max_weight DROP NOT NULL
        """
    )

    # ── Step 3 — rename fi_short_term → fi_us_short_term ──────────
    # Duplicate the row first so FK-dependent rows can retarget before
    # the old block is deleted. If the destination row already exists
    # (partial prior run), abort — manual reconciliation only.
    existing_new = conn.execute(
        sa.text(
            """
            SELECT 1 FROM allocation_blocks
             WHERE block_id = 'fi_us_short_term'
            """
        )
    ).scalar()
    existing_old = conn.execute(
        sa.text(
            """
            SELECT 1 FROM allocation_blocks
             WHERE block_id = 'fi_short_term'
            """
        )
    ).scalar()

    if existing_new and existing_old:
        raise RuntimeError(
            "pr_a25_abort both 'fi_us_short_term' and 'fi_short_term' "
            "exist as distinct blocks — manual reconciliation required "
            "before migration 0153 can proceed"
        )

    if existing_old and not existing_new:
        # Clone fi_short_term row with new id, then remap every
        # FK-dependent table, then delete the old row.
        conn.execute(
            sa.text(
                """
                INSERT INTO allocation_blocks
                    (block_id, geography, asset_class, display_name,
                     benchmark_ticker)
                SELECT 'fi_us_short_term', geography, asset_class,
                       display_name, benchmark_ticker
                  FROM allocation_blocks
                 WHERE block_id = 'fi_short_term'
                """
            )
        )
        for tbl in _FK_DEPENDENT_TABLES:
            result = conn.execute(
                sa.text(
                    f"""
                    UPDATE {tbl}
                       SET block_id = 'fi_us_short_term'
                     WHERE block_id = 'fi_short_term'
                    """
                )
            )
            print(
                f"[0153] renamed fi_short_term->fi_us_short_term "
                f"table={tbl} rows={result.rowcount}",
                flush=True,
            )
        # Drop the old block row now that nothing references it.
        conn.execute(
            sa.text(
                """
                DELETE FROM allocation_blocks
                 WHERE block_id = 'fi_short_term'
                """
            )
        )
        print("[0153] deleted legacy block fi_short_term", flush=True)
    elif not existing_old and not existing_new:
        # Neither exists — insert the canonical block with a sane default
        # so Step 4's assertion holds. SHY is the conventional 1-3Y UST.
        conn.execute(
            sa.text(
                """
                INSERT INTO allocation_blocks
                    (block_id, geography, asset_class, display_name,
                     benchmark_ticker)
                VALUES
                    ('fi_us_short_term', 'us', 'fixed_income',
                     '1-3 Year Treasury', 'SHY')
                """
            )
        )
        print("[0153] inserted fi_us_short_term (no prior row)", flush=True)
    # else: existing_new and not existing_old — nothing to do.

    # ── Step 4 — seed missing canonical blocks ────────────────────
    # Inline seed: fresh DBs (dev, CI, clean rebuild) never had a
    # prior migration that populated the 18 canonical rows — the
    # original 0153 docstring referenced a "prior migration" that
    # never existed. Prod already has all 18 (seeded manually pre-
    # deploy), so ON CONFLICT DO NOTHING makes this a safe no-op
    # there. Rows beyond the canonical 18 (alt_hedge_fund, etc.) are
    # left untouched.
    for block_id, geo, asset_class, display, ticker in _CANONICAL_SEED:
        conn.execute(
            sa.text(
                """
                INSERT INTO allocation_blocks
                    (block_id, geography, asset_class, display_name, benchmark_ticker)
                VALUES
                    (:block_id, :geo, :asset_class, :display, :ticker)
                ON CONFLICT (block_id) DO NOTHING
                """
            ),
            {"block_id": block_id, "geo": geo, "asset_class": asset_class, "display": display, "ticker": ticker},
        )

    # ── Step 5 — mark canonical set ───────────────────────────────
    # Flip is_canonical = true for the 18 IDs. Missing rows at this
    # point mean the catalog is under-seeded; surface loudly rather
    # than silently proceed.
    missing_rows = conn.execute(
        sa.text(
            """
            SELECT t.block_id
              FROM (SELECT unnest(CAST(:canon AS text[])) AS block_id) t
             LEFT JOIN allocation_blocks ab ON ab.block_id = t.block_id
             WHERE ab.block_id IS NULL
            """
        ),
        {"canon": list(_CANONICAL_BLOCKS)},
    ).fetchall()
    missing = [r[0] for r in missing_rows]
    if missing:
        raise RuntimeError(
            "pr_a25_abort allocation_blocks is missing canonical rows "
            f"{missing} — seed them before running migration 0153"
        )
    conn.execute(
        sa.text(
            """
            UPDATE allocation_blocks
               SET is_canonical = true
             WHERE block_id = ANY(CAST(:canon AS text[]))
            """
        ),
        {"canon": list(_CANONICAL_BLOCKS)},
    )
    canon_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM allocation_blocks WHERE is_canonical = true"
        )
    ).scalar_one()
    if canon_count != len(_CANONICAL_BLOCKS):
        raise RuntimeError(
            f"pr_a25_abort canonical count={canon_count}, expected "
            f"{len(_CANONICAL_BLOCKS)} — investigate allocation_blocks"
        )
    print(f"[0153] marked {canon_count} canonical blocks", flush=True)

    # ── Step 6 — fix effective_to bit-rot ─────────────────────────
    bitrot = conn.execute(
        sa.text(
            """
            UPDATE strategic_allocation
               SET effective_to = NULL
             WHERE effective_to IS NOT NULL
            """
        )
    )
    print(
        f"[0153] effective_to bit-rot cleared rows={bitrot.rowcount}",
        flush=True,
    )

    # ── Step 7 — create allocation_template_audit ─────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS allocation_template_audit (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            trigger_reason TEXT NOT NULL,
            organization_id UUID NOT NULL,
            profile VARCHAR(20) NOT NULL,
            block_id VARCHAR(80) NOT NULL,
            action VARCHAR(20) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_alloc_template_audit_org_profile
          ON allocation_template_audit (organization_id, profile,
                                        triggered_at DESC)
        """
    )

    # ── Step 8 — backfill missing canonical rows ──────────────────
    backfill = conn.execute(
        sa.text(
            """
            WITH combo AS (
                SELECT DISTINCT organization_id, profile
                  FROM strategic_allocation
            ),
            canon AS (
                SELECT block_id FROM allocation_blocks
                 WHERE is_canonical = true
            ),
            missing AS (
                SELECT c.organization_id, c.profile, k.block_id
                  FROM combo c
                 CROSS JOIN canon k
             LEFT JOIN strategic_allocation sa
                    ON sa.organization_id = c.organization_id
                   AND sa.profile = c.profile
                   AND sa.block_id = k.block_id
                 WHERE sa.allocation_id IS NULL
            )
            INSERT INTO strategic_allocation (
                allocation_id, organization_id, profile, block_id,
                target_weight, min_weight, max_weight, risk_budget,
                rationale, approved_by, effective_from, effective_to,
                actor_source, excluded_from_portfolio
            )
            SELECT gen_random_uuid(), m.organization_id, m.profile,
                   m.block_id,
                   NULL, NULL, NULL, NULL,
                   'Auto-backfilled by migration 0153 for template completeness',
                   'system', CURRENT_DATE, NULL,
                   'migration_0153', false
              FROM missing m
            RETURNING organization_id, profile, block_id
            """
        )
    )
    inserted_rows = backfill.fetchall()
    print(
        f"[0153] backfilled {len(inserted_rows)} strategic_allocation rows",
        flush=True,
    )

    # Matching audit trail entries.
    if inserted_rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO allocation_template_audit
                    (trigger_reason, organization_id, profile, block_id,
                     action, details)
                SELECT 'manual_backfill', r.organization_id, r.profile,
                       r.block_id, 'inserted',
                       jsonb_build_object('source', 'migration_0153')
                  FROM unnest(CAST(:orgs AS uuid[]),
                              CAST(:profiles AS text[]),
                              CAST(:blocks AS text[]))
                    AS r(organization_id, profile, block_id)
                """
            ),
            {
                "orgs": [str(r[0]) for r in inserted_rows],
                "profiles": [r[1] for r in inserted_rows],
                "blocks": [r[2] for r in inserted_rows],
            },
        )

    # ── Step 9 — triggers for ongoing template enforcement ────────
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION fn_enforce_allocation_template_sa()
        RETURNS TRIGGER AS $$
        DECLARE
            missing_block RECORD;
            existing_rows INT;
        BEGIN
            -- Only act on the FIRST row for this (org, profile). The
            -- AFTER-INSERT timing means NEW is already visible, hence
            -- the 'existing = 1' comparison.
            SELECT COUNT(*)
              INTO existing_rows
              FROM strategic_allocation
             WHERE organization_id = NEW.organization_id
               AND profile = NEW.profile;
            IF existing_rows <> 1 THEN
                RETURN NEW;
            END IF;

            FOR missing_block IN
                SELECT block_id FROM allocation_blocks
                 WHERE is_canonical = true
                   AND block_id <> NEW.block_id
            LOOP
                INSERT INTO strategic_allocation (
                    allocation_id, organization_id, profile, block_id,
                    target_weight, min_weight, max_weight, risk_budget,
                    rationale, approved_by, effective_from, effective_to,
                    actor_source, excluded_from_portfolio
                )
                VALUES (
                    gen_random_uuid(), NEW.organization_id, NEW.profile,
                    missing_block.block_id,
                    NULL, NULL, NULL, NULL,
                    'Auto-inserted by enforce_allocation_template trigger',
                    'system', CURRENT_DATE, NULL,
                    'trigger_enforce', false
                );

                INSERT INTO allocation_template_audit (
                    trigger_reason, organization_id, profile, block_id,
                    action, details
                )
                VALUES (
                    'new_profile_created', NEW.organization_id,
                    NEW.profile, missing_block.block_id, 'inserted',
                    jsonb_build_object('source_row_id', NEW.allocation_id)
                );
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_enforce_allocation_template_sa
          ON strategic_allocation
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_allocation_template_sa
          AFTER INSERT ON strategic_allocation
          FOR EACH ROW EXECUTE FUNCTION fn_enforce_allocation_template_sa()
        """
    )

    # Sibling trigger: is_canonical flips to true → backfill that block
    # across every (org, profile) that exists today.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION fn_enforce_allocation_template_blocks()
        RETURNS TRIGGER AS $$
        DECLARE
            combo RECORD;
        BEGIN
            IF NOT (NEW.is_canonical = true AND
                    COALESCE(OLD.is_canonical, false) = false) THEN
                RETURN NEW;
            END IF;

            FOR combo IN
                SELECT DISTINCT organization_id, profile
                  FROM strategic_allocation
                 WHERE NOT EXISTS (
                     SELECT 1 FROM strategic_allocation sa
                      WHERE sa.organization_id = strategic_allocation.organization_id
                        AND sa.profile = strategic_allocation.profile
                        AND sa.block_id = NEW.block_id
                 )
            LOOP
                INSERT INTO strategic_allocation (
                    allocation_id, organization_id, profile, block_id,
                    target_weight, min_weight, max_weight, risk_budget,
                    rationale, approved_by, effective_from, effective_to,
                    actor_source, excluded_from_portfolio
                )
                VALUES (
                    gen_random_uuid(), combo.organization_id, combo.profile,
                    NEW.block_id,
                    NULL, NULL, NULL, NULL,
                    'Auto-inserted by enforce_allocation_template_blocks trigger',
                    'system', CURRENT_DATE, NULL,
                    'trigger_enforce', false
                );

                INSERT INTO allocation_template_audit (
                    trigger_reason, organization_id, profile, block_id,
                    action, details
                )
                VALUES (
                    'block_marked_canonical', combo.organization_id,
                    combo.profile, NEW.block_id, 'inserted',
                    jsonb_build_object('source_block_id', NEW.block_id)
                );
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_enforce_allocation_template_blocks
          ON allocation_blocks
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_allocation_template_blocks
          AFTER UPDATE OF is_canonical ON allocation_blocks
          FOR EACH ROW EXECUTE FUNCTION fn_enforce_allocation_template_blocks()
        """
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop triggers + functions first so later DML doesn't fire them.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_enforce_allocation_template_blocks "
        "ON allocation_blocks"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_enforce_allocation_template_sa "
        "ON strategic_allocation"
    )
    op.execute("DROP FUNCTION IF EXISTS fn_enforce_allocation_template_blocks()")
    op.execute("DROP FUNCTION IF EXISTS fn_enforce_allocation_template_sa()")

    # Delete backfilled rows (identified by actor_source).
    conn.execute(
        sa.text(
            """
            DELETE FROM strategic_allocation
             WHERE actor_source IN ('migration_0153', 'trigger_enforce')
            """
        )
    )

    # Drop audit table.
    op.execute("DROP TABLE IF EXISTS allocation_template_audit")

    # Reverse rename: fi_us_short_term → fi_short_term.
    existing_old = conn.execute(
        sa.text(
            "SELECT 1 FROM allocation_blocks WHERE block_id = 'fi_short_term'"
        )
    ).scalar()
    existing_new = conn.execute(
        sa.text(
            "SELECT 1 FROM allocation_blocks WHERE block_id = 'fi_us_short_term'"
        )
    ).scalar()
    if existing_new and not existing_old:
        conn.execute(
            sa.text(
                """
                INSERT INTO allocation_blocks
                    (block_id, geography, asset_class, display_name,
                     benchmark_ticker)
                SELECT 'fi_short_term', geography, asset_class,
                       display_name, benchmark_ticker
                  FROM allocation_blocks
                 WHERE block_id = 'fi_us_short_term'
                """
            )
        )
        for tbl in _FK_DEPENDENT_TABLES:
            conn.execute(
                sa.text(
                    f"UPDATE {tbl} SET block_id = 'fi_short_term' "
                    "WHERE block_id = 'fi_us_short_term'"
                )
            )
        conn.execute(
            sa.text(
                "DELETE FROM allocation_blocks "
                "WHERE block_id = 'fi_us_short_term'"
            )
        )

    # Drop added columns.
    op.execute(
        "ALTER TABLE strategic_allocation "
        "DROP COLUMN IF EXISTS excluded_from_portfolio"
    )
    op.execute(
        "ALTER TABLE allocation_blocks DROP COLUMN IF EXISTS is_canonical"
    )

    # Restore NOT NULL only if every remaining row has a value — otherwise
    # leave columns nullable and surface a warning. Forcing NOT NULL when
    # NULLs exist would fail at a confusing point in the rollback.
    null_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM strategic_allocation
             WHERE target_weight IS NULL
                OR min_weight IS NULL
                OR max_weight IS NULL
            """
        )
    ).scalar_one()
    if null_count == 0:
        op.execute(
            """
            ALTER TABLE strategic_allocation
              ALTER COLUMN target_weight SET NOT NULL,
              ALTER COLUMN min_weight SET NOT NULL,
              ALTER COLUMN max_weight SET NOT NULL
            """
        )
    else:
        print(
            f"[0153-down] WARNING {null_count} strategic_allocation rows "
            "carry NULL weights — leaving columns nullable. Populate them "
            "before re-attempting to restore NOT NULL.",
            flush=True,
        )
