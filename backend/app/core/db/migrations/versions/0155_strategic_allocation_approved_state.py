"""PR-A26.2 — strategic_allocation approved state refactor + allocation_approvals.

Section A — ``strategic_allocation`` schema refactor:

* Drop legacy optimizer-bound columns ``min_weight`` / ``max_weight``.
  Post-A26.2 the propose-then-approve flow owns the bands; the optimizer
  reads ``drift_min / drift_max`` (realize mode) or ``override_min /
  override_max`` (propose mode with operator overrides) instead.
* Add ``drift_min, drift_max`` — approved drift tolerance around
  ``target_weight``; set atomically by the approve-proposal endpoint.
* Add ``override_min, override_max`` — operator-set guard rails that
  apply only on propose runs. Persist across approvals until explicitly
  cleared.
* Add ``approved_from_run_id, approved_at`` — provenance back to the
  ``portfolio_construction_runs`` row that seeded the approved snapshot.
  ``approved_at IS NULL`` is the realize-mode "never approved" sentinel.
* ``approved_by`` already exists (``String(100)``) from migration 0002;
  leave it untouched.
* Index ``(organization_id, profile, approved_at)`` so the realize-mode
  gate's ``COUNT(approved_at IS NOT NULL)`` query is a cheap range scan.
* ``CHECK`` constraints on drift + override bounds — bookkeeping only.

Section B — new ``allocation_approvals`` audit table (global, no RLS).

Both sections live in a single transactional migration; down-migration
reverses the steps in reverse order. The reverse re-creates
``min_weight / max_weight`` as nullable ``NUMERIC(6,4)`` (original
values are lost — documented in the downgrade docstring).
"""
from __future__ import annotations

from alembic import op

revision = "0155_strategic_allocation_approved_state"
down_revision = "0154_portfolio_construction_run_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Section A ─────────────────────────────────────────────────

    # 1. ADD new columns (nullable — seeded by approve-proposal flow).
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ADD COLUMN IF NOT EXISTS drift_min NUMERIC(6,4),
          ADD COLUMN IF NOT EXISTS drift_max NUMERIC(6,4),
          ADD COLUMN IF NOT EXISTS override_min NUMERIC(6,4),
          ADD COLUMN IF NOT EXISTS override_max NUMERIC(6,4),
          ADD COLUMN IF NOT EXISTS approved_from_run_id UUID,
          ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ
        """
    )

    # 2. DROP legacy optimizer-bound columns.
    op.execute(
        """
        ALTER TABLE strategic_allocation
          DROP COLUMN IF EXISTS min_weight,
          DROP COLUMN IF EXISTS max_weight
        """
    )

    # 3. Approval-state index.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategic_allocation_approval_state
          ON strategic_allocation (organization_id, profile, approved_at)
        """
    )

    # 4. CHECK constraints (idempotent).
    op.execute(
        """
        ALTER TABLE strategic_allocation
          DROP CONSTRAINT IF EXISTS chk_drift_bounds
        """
    )
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ADD CONSTRAINT chk_drift_bounds
            CHECK (drift_min IS NULL OR drift_max IS NULL
                   OR drift_min <= drift_max)
        """
    )
    op.execute(
        """
        ALTER TABLE strategic_allocation
          DROP CONSTRAINT IF EXISTS chk_override_bounds
        """
    )
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ADD CONSTRAINT chk_override_bounds
            CHECK (override_min IS NULL OR override_max IS NULL
                   OR override_min <= override_max)
        """
    )

    # ── Section B — allocation_approvals audit table ──────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS allocation_approvals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id UUID NOT NULL,
          organization_id UUID NOT NULL,
          profile VARCHAR(20) NOT NULL,
          approved_by TEXT NOT NULL,
          approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          superseded_at TIMESTAMPTZ,
          cvar_at_approval NUMERIC(6,4),
          expected_return_at_approval NUMERIC(8,6),
          cvar_feasible_at_approval BOOLEAN NOT NULL DEFAULT TRUE,
          operator_message TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_allocation_approvals_org_profile_active
          ON allocation_approvals (organization_id, profile, superseded_at)
          WHERE superseded_at IS NULL
        """
    )

    # ── A25 trigger refresh ───────────────────────────────────────
    # Migration 0153 defined ``fn_enforce_allocation_template_sa`` and
    # ``fn_enforce_allocation_template_blocks`` with INSERTs that
    # reference the now-dropped ``min_weight`` / ``max_weight`` columns.
    # Rebuild both functions without those columns so the canonical
    # template trigger keeps firing post-A26.2.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION fn_enforce_allocation_template_sa()
        RETURNS TRIGGER AS $$
        DECLARE
            missing_block RECORD;
            existing_rows INT;
        BEGIN
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
                    target_weight, risk_budget,
                    rationale, approved_by, effective_from, effective_to,
                    actor_source, excluded_from_portfolio
                )
                VALUES (
                    gen_random_uuid(), NEW.organization_id, NEW.profile,
                    missing_block.block_id,
                    NULL, NULL,
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
                    target_weight, risk_budget,
                    rationale, approved_by, effective_from, effective_to,
                    actor_source, excluded_from_portfolio
                )
                VALUES (
                    gen_random_uuid(), combo.organization_id, combo.profile,
                    NEW.block_id,
                    NULL, NULL,
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


def downgrade() -> None:
    """Reverse the migration.

    WARNING: the original ``min_weight`` / ``max_weight`` values that
    existed before upgrade are irrecoverable — we re-create the columns
    as nullable so the reverse round-trip schema check passes, but the
    data is not restored. Operators that need the pre-A26.2 numbers
    should restore from backup.
    """
    # Drop allocation_approvals + index.
    op.execute("DROP INDEX IF EXISTS ix_allocation_approvals_org_profile_active")
    op.execute("DROP TABLE IF EXISTS allocation_approvals")

    # Drop CHECK constraints.
    op.execute(
        "ALTER TABLE strategic_allocation DROP CONSTRAINT IF EXISTS chk_override_bounds"
    )
    op.execute(
        "ALTER TABLE strategic_allocation DROP CONSTRAINT IF EXISTS chk_drift_bounds"
    )

    # Drop approval-state index.
    op.execute("DROP INDEX IF EXISTS ix_strategic_allocation_approval_state")

    # Drop new columns.
    op.execute(
        """
        ALTER TABLE strategic_allocation
          DROP COLUMN IF EXISTS approved_at,
          DROP COLUMN IF EXISTS approved_from_run_id,
          DROP COLUMN IF EXISTS override_max,
          DROP COLUMN IF EXISTS override_min,
          DROP COLUMN IF EXISTS drift_max,
          DROP COLUMN IF EXISTS drift_min
        """
    )

    # Re-create legacy columns (nullable; original data cannot be restored).
    op.execute(
        """
        ALTER TABLE strategic_allocation
          ADD COLUMN IF NOT EXISTS min_weight NUMERIC(6,4),
          ADD COLUMN IF NOT EXISTS max_weight NUMERIC(6,4)
        """
    )

    # Restore A25 trigger function bodies that reference the re-created
    # ``min_weight`` / ``max_weight`` columns so upstream rollback leaves
    # the canonical template enforcement intact.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION fn_enforce_allocation_template_sa()
        RETURNS TRIGGER AS $$
        DECLARE
            missing_block RECORD;
            existing_rows INT;
        BEGIN
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
