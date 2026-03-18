"""Fix instruments universe RLS: add FORCE + WITH CHECK (AUTH-04).

Migration 0012 created instruments_universe, instrument_screening_metrics,
screening_runs, and screening_results with ENABLE ROW LEVEL SECURITY but
missing FORCE ROW LEVEL SECURITY and WITH CHECK clauses.

Without FORCE: table owner bypasses RLS policies entirely.
Without WITH CHECK: INSERT/UPDATE can write rows for any tenant.

This migration adds the missing security primitives to match the pattern
established in 0003, 0008, 0009, 0014 migrations.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_TABLES_TO_FIX = [
    "instruments_universe",
    "instrument_screening_metrics",
    "screening_runs",
    "screening_results",
]


def upgrade() -> None:
    for table in _TABLES_TO_FIX:
        # Add FORCE ROW LEVEL SECURITY (was missing in 0012)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        # Replace USING-only policy with USING + WITH CHECK
        # 0012 used {table}_org_isolation naming convention
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")

        # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
        op.execute(f"""
            CREATE POLICY {table}_org_isolation ON {table}
                USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
                WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)


def downgrade() -> None:
    for table in reversed(_TABLES_TO_FIX):
        # Restore original 0012 pattern (USING only, no FORCE)
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY {table}_org_isolation ON {table}
                USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)
        # Note: cannot un-FORCE without disabling+re-enabling RLS.
        # Downgrade preserves FORCE since it's strictly more secure.
