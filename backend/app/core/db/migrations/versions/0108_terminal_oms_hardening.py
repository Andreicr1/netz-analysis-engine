"""Terminal OMS Hardening — execution_venue, fill_status, holdings_version.

Phase 1 of the Terminal Live Workspace epic. Adds:

1. ``trade_tickets.execution_venue`` — nullable venue identifier for
   future real OMS integration (simulated for now).
2. ``trade_tickets.fill_status`` — 5-state CHECK constraint tracking
   order lifecycle: simulated → pending → filled → partial → rejected.
3. ``trade_tickets`` composite index on (portfolio_id, executed_at DESC,
   id DESC) for the new paginated trade-tickets listing endpoint.
4. ``portfolio_actual_holdings.holdings_version`` — monotonic integer
   for optimistic locking on trade execution.

Revision ID: 0108_terminal_oms_hardening
Revises: 0107_shadow_oms
Create Date: 2026-04-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0108_terminal_oms_hardening"
down_revision: str = "0107_shadow_oms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── trade_tickets: execution_venue ────────────────────────────
    op.add_column(
        "trade_tickets",
        sa.Column("execution_venue", sa.String(50), nullable=True),
    )

    # ── trade_tickets: fill_status with CHECK constraint ──────────
    op.add_column(
        "trade_tickets",
        sa.Column(
            "fill_status",
            sa.String(20),
            nullable=False,
            server_default="simulated",
        ),
    )
    op.create_check_constraint(
        "ck_trade_tickets_fill_status",
        "trade_tickets",
        "fill_status IN ('simulated', 'pending', 'filled', 'partial', 'rejected')",
    )

    # ── trade_tickets: composite index for paginated listing ──────
    op.create_index(
        "ix_trade_tickets_portfolio_executed_id",
        "trade_tickets",
        ["portfolio_id", sa.text("executed_at DESC"), sa.text("id DESC")],
    )

    # ── portfolio_actual_holdings: holdings_version ───────────────
    op.add_column(
        "portfolio_actual_holdings",
        sa.Column(
            "holdings_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("portfolio_actual_holdings", "holdings_version")
    op.drop_index("ix_trade_tickets_portfolio_executed_id", table_name="trade_tickets")
    op.drop_constraint("ck_trade_tickets_fill_status", "trade_tickets", type_="check")
    op.drop_column("trade_tickets", "fill_status")
    op.drop_column("trade_tickets", "execution_venue")
