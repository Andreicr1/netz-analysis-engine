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
    """Refuse downgrade if multi-active state exists (Codex P2 fix).

    The legacy ``uq_model_portfolios_org_profile_active`` partial unique
    keyed on ``status IN ('draft','backtesting','live')`` cannot coexist
    with the post-0201 multi-draft pattern: re-creating it on a DB that
    has accumulated two or more drafts per ``(organization_id, profile)``
    would fail with a duplicate-key error and leave the rollback halfway
    applied (legacy unique missing, new constraints already dropped).

    Rather than silently mutate or destroy production data — which would
    be opaque to the operator and irrecoverable — we refuse the
    downgrade with a structured ``RuntimeError`` listing the offending
    ``(organization_id, profile)`` pair. The operator must consciously
    archive the duplicate non-live rows (or delete drafts) before
    retrying the rollback. Suggested cleanup:

    .. code-block:: sql

        -- Inspect the duplicates
        SELECT organization_id, profile, COUNT(*) AS dup
        FROM model_portfolios
        WHERE status IN ('draft', 'backtesting', 'live')
        GROUP BY 1, 2
        HAVING COUNT(*) > 1;

        -- Archive duplicates per (org, profile), keeping the most recent
        UPDATE model_portfolios SET status = 'archived'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY organization_id, profile
                    ORDER BY created_at DESC
                ) AS rn
                FROM model_portfolios
                WHERE status IN ('draft', 'backtesting', 'live')
            ) ranked WHERE rn > 1
        );

    On a fresh DB (no model_portfolios rows) this pre-check returns no
    rows and the downgrade proceeds normally — preserving symmetry with
    upgrade for dev / CI workflows.
    """
    op.execute(
        "DROP INDEX IF EXISTS uq_model_portfolios_org_display_name"
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_model_portfolios_primary_live"
    )

    # ── Pre-check: refuse on multi-active state ──────────────────────
    conn = op.get_bind()
    duplicate = conn.execute(
        sa.text(
            """
            SELECT organization_id, profile, COUNT(*) AS dup
            FROM model_portfolios
            WHERE status IN ('draft', 'backtesting', 'live')
            GROUP BY 1, 2
            HAVING COUNT(*) > 1
            ORDER BY dup DESC
            LIMIT 1
            """
        )
    ).fetchone()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade migration 0201 — multi-active portfolios "
            f"detected (organization_id={duplicate[0]}, "
            f"profile={duplicate[1]!r}, count={duplicate[2]}). "
            "Recreating the legacy uq_model_portfolios_org_profile_active "
            "unique index would fail on duplicate keys. "
            "Manual cleanup required: archive the duplicate non-live rows "
            "before retrying the rollback. See the docstring of this "
            "migration for the cleanup SQL."
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
