"""portfolio_construction_runs persisted narrative

Phase 1 Task 1.3 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Creates the ``portfolio_construction_runs`` table — the persistent
home for every ``/construct`` invocation. One row per run with the full
optimizer trace, binding constraints, regime context, ex-ante metrics,
factor exposure, advisor advice, validation gate result, narrative
output, and per-instrument rationale (DL4).

The construction_runs table is the load-bearing artifact for the
Builder UI's ``ConstructionNarrative.svelte`` (Phase 4 Task 4.3) and
the Analytics page's "replay any run" feature (Phase 6).

Status enum:
    running — worker accepted the job and the optimizer is executing
    succeeded — optimizer + validation + narrative all completed
    failed — any phase raised; ``optimizer_trace`` carries the error
    superseded — a newer run for the same portfolio replaced this one
                 in the cache (cap is 10 most recent per DL4)

calibration_id FK
-----------------
The FK from ``calibration_id`` to ``portfolio_calibration(id)`` is
intentionally NOT added in this migration — ``portfolio_calibration``
lands in 0100 (Phase 2 Task 2.1) and the FK is added by 0105
(Phase 2 Task 2.6) once both tables coexist. Keeping this migration
free of forward references means it remains independently downgradable.

RLS
---
Subselect-wrapped policy per CLAUDE.md. Without the wrapper, every row
re-evaluates ``current_setting()`` and the index plan loses ~1000x in
latency.

Downgrade
---------
NO ``IF EXISTS``. Fail loudly if the table or any of the indexes are
missing on downgrade — that is structural drift the operator must
investigate before re-running (Phase 1 Task 1.3 Step 4).

Revision ID: 0099_portfolio_construction_runs
Revises: 0098_model_portfolio_lifecycle_state
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0099_portfolio_construction_runs"
down_revision: str | None = "0098_model_portfolio_lifecycle_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS_VALUES = ("running", "succeeded", "failed", "superseded")


def upgrade() -> None:
    # ── Table ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE portfolio_construction_runs (
            id                    uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id       uuid         NOT NULL,
            portfolio_id          uuid         NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,

            -- Cache-key + idempotency
            calibration_id        uuid,
            calibration_hash      text         NOT NULL,
            calibration_snapshot  jsonb        NOT NULL,
            universe_fingerprint  text         NOT NULL,
            as_of_date            date         NOT NULL,

            -- Run lifecycle
            status                text         NOT NULL,
            requested_by          text         NOT NULL,
            requested_at          timestamptz  NOT NULL DEFAULT now(),
            started_at            timestamptz,
            completed_at          timestamptz,
            wall_clock_ms         integer,
            failure_reason        text,

            -- Quant outputs
            optimizer_trace       jsonb        NOT NULL DEFAULT '{}'::jsonb,
            binding_constraints   jsonb        NOT NULL DEFAULT '[]'::jsonb,
            regime_context        jsonb        NOT NULL DEFAULT '{}'::jsonb,
            statistical_inputs    jsonb        NOT NULL DEFAULT '{}'::jsonb,
            ex_ante_metrics       jsonb        NOT NULL DEFAULT '{}'::jsonb,
            ex_ante_vs_previous   jsonb,
            factor_exposure       jsonb,
            stress_results        jsonb        NOT NULL DEFAULT '[]'::jsonb,
            advisor               jsonb,
            validation            jsonb        NOT NULL DEFAULT '{}'::jsonb,
            narrative             jsonb        NOT NULL DEFAULT '{}'::jsonb,
            rationale_per_weight  jsonb        NOT NULL DEFAULT '{}'::jsonb,
            weights_proposed      jsonb        NOT NULL DEFAULT '{}'::jsonb
        )
        """,
    )

    # CHECK constraint on status — exactly the 4 canonical values.
    op.execute(
        f"""
        ALTER TABLE portfolio_construction_runs
            ADD CONSTRAINT portfolio_construction_runs_status_check
            CHECK (status IN (
                {", ".join(f"'{s}'" for s in _STATUS_VALUES)}
            ))
        """,
    )

    # ── Indexes ───────────────────────────────────────────────────
    # Hot path 1: list runs for a portfolio newest-first.
    op.execute(
        """
        CREATE INDEX ix_pcr_portfolio_requested_at
        ON portfolio_construction_runs (portfolio_id, requested_at DESC)
        """,
    )

    # Hot path 2: admin/oncall view of running + failed runs.
    op.execute(
        """
        CREATE INDEX ix_pcr_status_requested_at
        ON portfolio_construction_runs (status, requested_at DESC)
        WHERE status IN ('running', 'failed')
        """,
    )

    # Cache lookup: same calibration hash within TTL window returns
    # the prior run id (Phase 3 Task 3.4 Step 5 — Redis miss path).
    op.execute(
        """
        CREATE INDEX ix_pcr_portfolio_calibration_hash
        ON portfolio_construction_runs (portfolio_id, calibration_hash, requested_at DESC)
        """,
    )

    # ── RLS — subselect pattern ───────────────────────────────────
    op.execute("ALTER TABLE portfolio_construction_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portfolio_construction_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY portfolio_construction_runs_rls
        ON portfolio_construction_runs
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        WITH CHECK (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        """,
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly per Phase 1 Task 1.3 / DB draft §10.
    op.execute("DROP POLICY portfolio_construction_runs_rls ON portfolio_construction_runs")
    op.execute("DROP INDEX ix_pcr_portfolio_calibration_hash")
    op.execute("DROP INDEX ix_pcr_status_requested_at")
    op.execute("DROP INDEX ix_pcr_portfolio_requested_at")
    op.execute(
        "ALTER TABLE portfolio_construction_runs "
        "DROP CONSTRAINT portfolio_construction_runs_status_check",
    )
    op.execute("DROP TABLE portfolio_construction_runs")
