"""portfolio_stress_results with run idempotency

Phase 2 Task 2.2 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

One row per ``(construction_run_id, scenario)`` — the UNIQUE
constraint on that pair is the P5 idempotency contract (DL18).
Re-running stress for the same construction run can upsert via
``INSERT ... ON CONFLICT (construction_run_id, scenario)`` safely.

Scenario taxonomy
-----------------
The 4 canonical preset keys are:

    gfc_2008
    covid_2020
    taper_2013
    rate_shock_200bps

User-authored scenarios go as ``scenario_kind='user_defined'`` with
a free-form ``scenario`` label. The CHECK constraint enumerates only
the 2 kinds; the ``scenario`` text itself is free to avoid gating
the Builder on a migration whenever a new preset is added.

Column split
------------
``nav_impact_pct`` and ``cvar_impact_pct`` are the top-line metrics
the UI shows in the matrix view (Phase 4 Task 4.4 — ScenarioMatrix).
``per_block_impact`` is an array of objects keyed on allocation
block ({block_id, loss_pct}); ``per_instrument_impact`` is an array
keyed on instrument ({instrument_id, weight, loss_pct,
contrib_to_portfolio_loss}).

RLS
---
Subselect-wrapped per CLAUDE.md. No compression (scenarios are
sparse — ~4 rows per run, not a time series).

Downgrade
---------
NO ``IF EXISTS``. Fail loudly per Phase 1/2 convention.

Revision ID: 0101_portfolio_stress_results
Revises: 0100_portfolio_calibration
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0101_portfolio_stress_results"
down_revision: str | None = "0100_portfolio_calibration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE portfolio_stress_results (
            id                        uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id           uuid         NOT NULL,
            portfolio_id              uuid         NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,
            construction_run_id       uuid         NOT NULL
                REFERENCES portfolio_construction_runs(id) ON DELETE CASCADE,

            scenario                  text         NOT NULL,
            scenario_kind             text         NOT NULL,
            scenario_label            text,
            as_of                     date         NOT NULL,
            computed_at               timestamptz  NOT NULL DEFAULT now(),

            -- Top-line ex-ante impact (frontend matrix view)
            nav_impact_pct            numeric(10,6) NOT NULL,
            cvar_impact_pct           numeric(10,6),
            portfolio_loss_usd        numeric(18,2),
            max_drawdown_implied      numeric(10,6),
            recovery_days_estimate    integer,

            -- Per-block / per-instrument decomposition (JSONB arrays)
            per_block_impact          jsonb         NOT NULL DEFAULT '[]'::jsonb,
            per_instrument_impact     jsonb         NOT NULL DEFAULT '[]'::jsonb,

            -- Factor shocks applied (parametric scenarios)
            shock_params              jsonb         NOT NULL DEFAULT '{}'::jsonb,

            CONSTRAINT ck_stress_scenario_kind
                CHECK (scenario_kind IN ('preset', 'user_defined')),
            CONSTRAINT uq_stress_run_scenario
                UNIQUE (construction_run_id, scenario)
        )
        """,
    )

    # ── Indexes ───────────────────────────────────────────────────
    # Hot path 1: "give me all stress results for portfolio X
    # ordered by recency" — the Analytics "Stress" tab.
    op.execute(
        """
        CREATE INDEX ix_stress_portfolio_as_of
        ON portfolio_stress_results (portfolio_id, as_of DESC)
        """,
    )

    # Hot path 2: drill-down from a specific construction run.
    op.execute(
        """
        CREATE INDEX ix_stress_construction_run
        ON portfolio_stress_results (construction_run_id)
        """,
    )

    # ── RLS — subselect pattern ───────────────────────────────────
    op.execute("ALTER TABLE portfolio_stress_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portfolio_stress_results FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY portfolio_stress_results_rls
        ON portfolio_stress_results
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        WITH CHECK (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        """,
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly.
    op.execute("DROP POLICY portfolio_stress_results_rls ON portfolio_stress_results")
    op.execute("DROP INDEX ix_stress_construction_run")
    op.execute("DROP INDEX ix_stress_portfolio_as_of")
    op.execute("DROP TABLE portfolio_stress_results")
