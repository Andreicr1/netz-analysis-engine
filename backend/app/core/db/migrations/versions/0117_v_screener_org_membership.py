"""v_screener_org_membership security-barrier view.

Pre-joins instruments_org so the screener query can read membership
status (approved / pending / rejected, selection metadata, block_id)
per instrument without a 3-way JOIN on every filter change. The view
uses ``security_barrier=true`` so the RLS predicate on the underlying
``instruments_org`` table is applied before any outer WHERE clause,
preserving tenant isolation even against leaky operators or qual
pushdown optimizations.

The view explicitly re-asserts the tenant predicate with the
mandatory ``(SELECT current_setting(...))`` subselect pattern per
CLAUDE.md Critical Rules — bare ``current_setting()`` evaluates
per-row and causes ~1000x slowdown on large tables.

Exposed columns (match actual instruments_org schema, audited
2026-04-11 via ``\\d instruments_org`` — the brief's placeholder
``fast_track`` / ``approved_at`` / ``approved_by`` do not exist on
this table, the real columns are listed below):

- instrument_id
- organization_id
- block_id
- approval_status   ('pending' | 'approved' | 'rejected')
- selected_at

Revision ID: 0117_v_screener_org_membership
Revises: 0116_mv_fund_risk_latest
Create Date: 2026-04-11
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0117_v_screener_org_membership"
down_revision: str | None = "0116_mv_fund_risk_latest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW v_screener_org_membership
        WITH (security_barrier=true) AS
        SELECT
            io.instrument_id,
            io.organization_id,
            io.block_id,
            io.approval_status,
            io.selected_at
        FROM instruments_org io
        WHERE io.organization_id = (
            SELECT current_setting('app.current_organization_id', true)::uuid
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_screener_org_membership")
