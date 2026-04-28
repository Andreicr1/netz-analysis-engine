"""PR-Q92 — Allow audit_events.organization_id NULL for global events.

Global pipelines (factor_model, macro ingestion, benchmark_ingest) have
no tenant context — they compute over GLOBAL tables (benchmark_nav,
macro_data) shared across all organizations. When these pipelines emit
audit events, ``organization_id`` is unresolvable from RLS context and
``write_audit_event`` was failing with NotNullViolationError.

The error is currently swallowed by try/except in factor_model_service
(emit ``factor_data_gap_audit_failed`` warning), so factor estimation
continues — but the audit trail loses every global event.

Fix:
- Drop NOT NULL on ``audit_events.organization_id``.
- ``audit_events`` has no RLS (verified: ``rowsecurity = false``, 0
  policies), so nullable column is safe — tenant-scoped callers continue
  passing the resolved UUID via ``get_db_with_rls`` SET LOCAL context.
- Tenant-scoped queries already filter by ``organization_id`` in the
  WHERE clause; NULL rows are naturally excluded.

Revision ID: 0195_q92_audit_events_global
Revises: 0194_q91_ucits_data_gate
Create Date: 2026-04-28
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0195_q92_audit_events_global"
down_revision: str | None = "0194_q91_ucits_data_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop NOT NULL on organization_id so global pipelines can audit.
    op.execute("ALTER TABLE audit_events ALTER COLUMN organization_id DROP NOT NULL;")

    # 2. Update the RLS policy (created in migration 0019) to permit
    #    NULL organization_id rows for global pipeline events, while
    #    keeping per-tenant isolation for the rest. The DROP+CREATE is
    #    idempotent regardless of whether RLS is currently enabled on
    #    the table — we don't toggle RLS state here because audit_events
    #    is a TimescaleDB hypertable with columnstore enabled, and
    #    ENABLE/FORCE ROW LEVEL SECURITY is blocked while columnstore is
    #    on. Whatever RLS state exists is preserved.
    op.execute("DROP POLICY IF EXISTS org_isolation ON audit_events;")
    op.execute(
        """
        CREATE POLICY org_isolation ON audit_events
            USING (
                organization_id IS NULL
                OR organization_id = (
                    SELECT current_setting('app.current_organization_id', true)
                )::uuid
            )
            WITH CHECK (
                organization_id IS NULL
                OR organization_id = (
                    SELECT current_setting('app.current_organization_id', true)
                )::uuid
            );
        """,
    )


def downgrade() -> None:
    # Restore the 0019 policy (NULL rows excluded) before re-applying
    # NOT NULL — otherwise the constraint rejects existing NULL rows.
    op.execute("DROP POLICY IF EXISTS org_isolation ON audit_events;")
    op.execute(
        """
        CREATE POLICY org_isolation ON audit_events
            USING (
                organization_id = (
                    SELECT current_setting('app.current_organization_id', true)
                )::uuid
            )
            WITH CHECK (
                organization_id = (
                    SELECT current_setting('app.current_organization_id', true)
                )::uuid
            );
        """,
    )
    op.execute(
        """
        DELETE FROM audit_events WHERE organization_id IS NULL;
        ALTER TABLE audit_events ALTER COLUMN organization_id SET NOT NULL;
        """,
    )
