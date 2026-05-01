"""PR-BE-4 — multi-portfolio per profile + UNIQUE display_name.

Replaces the legacy ``uq_model_portfolios_org_profile_active`` partial
unique index (introduced in migration 0008) with a narrower
``uq_model_portfolios_primary_live`` index keyed on the new state
machine column (``state='live'``). This allows multiple
``draft``/``constructed``/``validated``/``approved``/``paused``
portfolios per ``(organization_id, profile)`` while still enforcing a
single ``primary_live`` portfolio per profile per org (Andrei v1
decision 2026-04-30, doc §1.1 + §4.4).

Adds a second tenant-scoped UNIQUE index on
``(organization_id, display_name)`` so the create handler can map a
duplicate-name conflict to a structured 409 (the PR-UX-4 dialog
renders this inline). RLS makes the constraint org-isolated by
construction; cross-org duplicate names are accepted.

Pre-flight DB audits performed against local Docker DB
(``netz-analysis-engine-db-1``) before authoring this migration:

- ``SELECT organization_id, display_name, COUNT(*) FROM model_portfolios
  GROUP BY 1,2 HAVING COUNT(*) > 1;`` → 0 rows.
- ``SELECT organization_id, profile, COUNT(*) FROM model_portfolios
  WHERE state='live' GROUP BY 1,2 HAVING COUNT(*) > 1;`` → 0 rows.
- Total rows in ``model_portfolios`` at audit time: 0.

Forward-only — no data migration required because every existing row
that passed the legacy ``status``-based check would also pass the new
``state``-based check (state machine post-0098 keeps the two columns
in sync at create time and only ``state`` is mutated by the lifecycle
transition helper afterwards).

Revision: 0201_q_multi_portfolio_constraints
Down-revision: 0200_q_self_approval_bootstrap_config
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0201_q_multi_portfolio_constraints"
down_revision = "0200_q_self_approval_bootstrap_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Drop the legacy ``status``-based partial unique ───────────
    # The legacy index (migration 0008) prevented multiple non-archived
    # portfolios per profile. v1 multi-portfolio explicitly relaxes
    # that — only the live (state='live') row is unique per profile.
    op.execute(
        "DROP INDEX IF EXISTS uq_model_portfolios_org_profile_active"
    )

    # ── 2. Narrower partial unique on state='live' ───────────────────
    # Single primary_live portfolio per (org, profile). Other states
    # (draft/constructed/validated/approved/paused) are not constrained
    # so the user can stage a new candidate alongside the live one.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_model_portfolios_primary_live
            ON model_portfolios (organization_id, profile)
            WHERE state = 'live'
        """
    )

    # ── 3. UNIQUE (organization_id, display_name) ────────────────────
    # Tenant-scoped. PR-UX-4 dialog catches the IntegrityError at the
    # create handler and surfaces a structured 409 with
    # ``error="duplicate_display_name"``. Cross-org dupes are allowed
    # because RLS already isolates each tenant.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_model_portfolios_org_display_name
            ON model_portfolios (organization_id, display_name)
        """
    )


def downgrade() -> None:
    # Drop the new constraints in reverse order, then restore the
    # legacy partial unique exactly as migration 0008 created it so a
    # rollback returns the schema to the pre-0201 shape.
    op.execute(
        "DROP INDEX IF EXISTS uq_model_portfolios_org_display_name"
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_model_portfolios_primary_live"
    )
    op.create_index(
        "uq_model_portfolios_org_profile_active",
        "model_portfolios",
        ["organization_id", "profile"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('draft', 'backtesting', 'live')"
        ),
    )
