"""portfolio_calibration — 63-input tiered calibration surface

Phase 2 Task 2.1 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Backs the Builder's ``CalibrationPanel.svelte`` (Phase 4 Task 4.1).
One row per portfolio (``UNIQUE (portfolio_id)``) — the row is
mutated in-place via Preview/Apply on the Builder. Historical
calibration state for any past ``/construct`` run is preserved via
the ``calibration_snapshot`` JSONB column on ``portfolio_construction_runs``.

Tiered surface (locked via DL5 + stitched plan Task 2.1):

    Basic tier (5 typed columns) — 80% of PM use cases:
        mandate, cvar_limit, max_single_fund_weight,
        turnover_cap, stress_scenarios_active

    Advanced tier (10 typed columns) — regime + BL + GARCH + turnover:
        regime_override, bl_enabled, bl_view_confidence_default,
        garch_enabled, turnover_lambda, stress_severity_multiplier,
        advisor_enabled, cvar_level, lambda_risk_aversion,
        shrinkage_intensity_override

    Expert tier (48 inputs) — JSONB ``expert_overrides`` blob for
    experimental knobs that have not yet graduated to typed columns.

Total typed surface: 5 + 10 = 15 columns. Total reachable inputs
via the panel: 15 typed + 48 via ``expert_overrides`` = 63.

RLS
---
Subselect-wrapped policy per CLAUDE.md. No compression on this
table — it's a one-row-per-portfolio preference table, not a
time series.

Trigger
-------
Creates a shared ``set_updated_at()`` function if missing, then
wires a BEFORE UPDATE trigger so ``updated_at`` is maintained
without the ORM having to remember to set it.

FK to ``portfolio_construction_runs.calibration_id``
----------------------------------------------------
The FK from ``portfolio_construction_runs.calibration_id`` → this
table's ``id`` is ADDED in migration 0105, AFTER this table exists.
Keeping the FK out of this migration avoids forward references and
makes each migration independently downgradable.

Downgrade
---------
NO ``IF EXISTS`` guards. Fail loudly if the table or the trigger
function is missing — that's structural drift the operator must
investigate. The shared ``set_updated_at()`` function is only
dropped if this is the last consumer (idempotency via pg_depend).

Revision ID: 0100_portfolio_calibration
Revises: 0099_portfolio_construction_runs
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0100_portfolio_calibration"
down_revision: str | None = "0099_portfolio_construction_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REGIME_VALUES = ("NORMAL", "RISK_ON", "RISK_OFF", "CRISIS", "INFLATION")


def upgrade() -> None:
    # ── Shared updated_at trigger function ──────────────────────────
    # Created OR REPLACE so the migration is idempotent across
    # downgrade/upgrade roundtrips. Any future table that wants the
    # same trigger semantics references this function.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
    )

    # ── Table ─────────────────────────────────────────────────────
    op.execute(
        f"""
        CREATE TABLE portfolio_calibration (
            id                              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id                 uuid         NOT NULL,
            portfolio_id                    uuid         NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,
            schema_version                  integer      NOT NULL DEFAULT 1,

            -- ── Basic tier (5) ──────────────────────────────────────
            mandate                         text         NOT NULL DEFAULT 'balanced',
            cvar_limit                      numeric(6,4) NOT NULL DEFAULT 0.05,
            max_single_fund_weight          numeric(6,4) NOT NULL DEFAULT 0.10,
            turnover_cap                    numeric(6,4),
            stress_scenarios_active         text[]       NOT NULL
                DEFAULT ARRAY['gfc_2008','covid_2020','taper_2013','rate_shock_200bps']::text[],

            -- ── Advanced tier (10) ──────────────────────────────────
            regime_override                 text,
            bl_enabled                      boolean      NOT NULL DEFAULT true,
            bl_view_confidence_default      numeric(6,4) NOT NULL DEFAULT 1.0,
            garch_enabled                   boolean      NOT NULL DEFAULT true,
            turnover_lambda                 numeric(10,6),
            stress_severity_multiplier      numeric(6,4) NOT NULL DEFAULT 1.0,
            advisor_enabled                 boolean      NOT NULL DEFAULT true,
            cvar_level                      numeric(4,3) NOT NULL DEFAULT 0.95,
            lambda_risk_aversion            numeric(10,6),
            shrinkage_intensity_override    numeric(4,3),

            -- ── Expert tier (48 inputs) ─────────────────────────────
            expert_overrides                jsonb        NOT NULL DEFAULT '{{}}'::jsonb,

            -- ── Audit ───────────────────────────────────────────────
            created_at                      timestamptz  NOT NULL DEFAULT now(),
            updated_at                      timestamptz  NOT NULL DEFAULT now(),
            updated_by                      text,

            CONSTRAINT ck_cvar_limit
                CHECK (cvar_limit > 0 AND cvar_limit <= 1),
            CONSTRAINT ck_max_single_fund_weight
                CHECK (max_single_fund_weight > 0 AND max_single_fund_weight <= 1),
            CONSTRAINT ck_cvar_level
                CHECK (cvar_level BETWEEN 0.80 AND 0.999),
            CONSTRAINT ck_regime_override
                CHECK (
                    regime_override IS NULL
                    OR regime_override IN ({", ".join(f"'{r}'" for r in _REGIME_VALUES)})
                ),
            CONSTRAINT ck_stress_severity_multiplier
                CHECK (stress_severity_multiplier BETWEEN 0.1 AND 5.0),
            CONSTRAINT uq_portfolio_calibration_portfolio_id
                UNIQUE (portfolio_id)
        )
        """,
    )

    # ── Indexes ───────────────────────────────────────────────────
    # UNIQUE constraint above already creates an index on portfolio_id;
    # this named index keeps the name explicit for alembic + tooling.
    # A second index on (organization_id, updated_at DESC) supports
    # the admin view "recently updated calibrations" query.
    op.execute(
        """
        CREATE INDEX ix_portfolio_calibration_org_updated
        ON portfolio_calibration (organization_id, updated_at DESC)
        """,
    )

    # ── updated_at trigger ────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER trg_portfolio_calibration_updated_at
        BEFORE UPDATE ON portfolio_calibration
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at()
        """,
    )

    # ── RLS — subselect pattern ───────────────────────────────────
    op.execute("ALTER TABLE portfolio_calibration ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portfolio_calibration FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY portfolio_calibration_rls
        ON portfolio_calibration
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        WITH CHECK (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        """,
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly per Phase 1/2 convention.
    op.execute("DROP POLICY portfolio_calibration_rls ON portfolio_calibration")
    op.execute("DROP TRIGGER trg_portfolio_calibration_updated_at ON portfolio_calibration")
    op.execute("DROP INDEX ix_portfolio_calibration_org_updated")
    op.execute("DROP TABLE portfolio_calibration")

    # Drop the shared trigger function ONLY if no other table depends
    # on it. This migration is the first consumer; if later migrations
    # wire more triggers to set_updated_at() the pg_depend check will
    # keep the function alive. Idempotent-safe via the dependency scan.
    op.execute(
        """
        DO $$
        DECLARE
            dep_count integer;
        BEGIN
            SELECT COUNT(*) INTO dep_count
            FROM pg_depend d
            JOIN pg_proc p ON p.oid = d.refobjid
            WHERE p.proname = 'set_updated_at'
              AND d.deptype = 'n';
            IF dep_count = 0 THEN
                DROP FUNCTION set_updated_at();
            END IF;
        END $$
        """,
    )
