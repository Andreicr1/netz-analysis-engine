"""model portfolio lifecycle state machine + transition audit

Phase 1 Task 1.1 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Adds the backend-authoritative state machine columns to ``model_portfolios``
and creates the ``portfolio_state_transitions`` audit table that records every
state move with actor, reason, metadata, and timestamp.

State enum (DL3 — locked 2026-04-08):

    draft → constructed → validated → approved → live → paused → archived
                                                              ↘ rejected

Backfill rule (legacy ``status`` column kept per OD-19 deferral):

    legacy ``status='active'``    → new ``state='live'``
    legacy ``status='draft'``     → new ``state='draft'``
    legacy ``status='backtesting'`` → new ``state='constructed'``
    legacy ``status='archived'``  → new ``state='archived'``
    everything else              → new ``state='draft'`` (safe default)

Idempotency
-----------
The new columns have ``DEFAULT 'draft'`` so insert paths that pre-date this
migration keep working unchanged.

RLS
---
``portfolio_state_transitions`` enables RLS via the project-standard
``(SELECT current_setting('app.current_organization_id'))::uuid`` subselect
pattern (CLAUDE.md "RLS subselect" rule). Without the subselect wrapper,
PostgreSQL re-evaluates ``current_setting()`` per row and the index plan
loses ~1000x in latency.

Downgrade
---------
The plan (Phase 1 Task 1.1 Step 3) requires the downgrade to fail loudly:
no ``IF EXISTS``, no defensive guards. If the transition table or any of
the four columns is missing on downgrade, that is a structural drift the
operator must investigate before re-running.

Revision ID: 0098_model_portfolio_lifecycle_state
Revises: 0097_curated_institutions_seed
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0098_model_portfolio_lifecycle_state"
down_revision: str | None = "0097_curated_institutions_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Canonical state set — must stay in sync with
# backend/vertical_engines/wealth/model_portfolio/state_machine.py TRANSITIONS
_STATE_VALUES = (
    "draft",
    "constructed",
    "validated",
    "approved",
    "live",
    "paused",
    "archived",
    "rejected",
)


def upgrade() -> None:
    # ── Columns on model_portfolios ─────────────────────────────────
    op.execute(
        """
        ALTER TABLE model_portfolios
            ADD COLUMN state              text        NOT NULL DEFAULT 'draft',
            ADD COLUMN state_metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN state_changed_at   timestamptz NOT NULL DEFAULT now(),
            ADD COLUMN state_changed_by   text
        """,
    )

    # CHECK constraint enumerating exactly the 8 canonical states.
    op.execute(
        f"""
        ALTER TABLE model_portfolios
            ADD CONSTRAINT model_portfolios_state_check
            CHECK (state IN (
                {", ".join(f"'{s}'" for s in _STATE_VALUES)}
            ))
        """,
    )

    # Backfill from legacy `status` column (OD-19 keeps the column alive
    # for the 3-profile CVaR monitor until a 01xx cleanup migration).
    op.execute(
        """
        UPDATE model_portfolios
        SET state = CASE
            WHEN status = 'active'      THEN 'live'
            WHEN status = 'backtesting' THEN 'constructed'
            WHEN status = 'archived'    THEN 'archived'
            WHEN status = 'draft'       THEN 'draft'
            ELSE 'draft'
        END,
        state_changed_at = now(),
        state_changed_by = 'migration_0098_backfill'
        """,
    )

    # ── portfolio_state_transitions audit table ─────────────────────
    op.execute(
        """
        CREATE TABLE portfolio_state_transitions (
            id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid         NOT NULL,
            portfolio_id    uuid         NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,
            from_state      text,
            to_state        text         NOT NULL,
            actor_id        text         NOT NULL,
            reason          text,
            metadata        jsonb        NOT NULL DEFAULT '{}'::jsonb,
            created_at      timestamptz  NOT NULL DEFAULT now()
        )
        """,
    )

    # CHECK constraint on to_state mirrors the parent column.
    op.execute(
        f"""
        ALTER TABLE portfolio_state_transitions
            ADD CONSTRAINT portfolio_state_transitions_to_state_check
            CHECK (to_state IN (
                {", ".join(f"'{s}'" for s in _STATE_VALUES)}
            ))
        """,
    )

    # Hot-path index — list transitions for a portfolio newest-first.
    op.execute(
        """
        CREATE INDEX ix_pst_portfolio_created
        ON portfolio_state_transitions (portfolio_id, created_at DESC)
        """,
    )

    # Auxiliary index for the org-wide audit feed (admin view).
    op.execute(
        """
        CREATE INDEX ix_pst_org_created
        ON portfolio_state_transitions (organization_id, created_at DESC)
        """,
    )

    # ── RLS — subselect pattern (mandatory per CLAUDE.md) ───────────
    op.execute("ALTER TABLE portfolio_state_transitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portfolio_state_transitions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY portfolio_state_transitions_rls
        ON portfolio_state_transitions
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        WITH CHECK (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        """,
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly if the table or columns are missing
    # (Phase 1 Task 1.1 Step 3 / DB draft §10).
    op.execute("DROP POLICY portfolio_state_transitions_rls ON portfolio_state_transitions")
    op.execute("DROP INDEX ix_pst_org_created")
    op.execute("DROP INDEX ix_pst_portfolio_created")
    op.execute("DROP TABLE portfolio_state_transitions")

    op.execute(
        "ALTER TABLE model_portfolios DROP CONSTRAINT model_portfolios_state_check",
    )
    op.execute(
        """
        ALTER TABLE model_portfolios
            DROP COLUMN state_changed_by,
            DROP COLUMN state_changed_at,
            DROP COLUMN state_metadata,
            DROP COLUMN state
        """,
    )
