"""Shadow OMS — portfolio_actual_holdings + trade_tickets tables.

Phase 9 Block D: Persists the Live Workbench's drift analysis and
trade execution workflow. Two tables:

1. ``portfolio_actual_holdings`` — one row per live portfolio, JSONB
   of actual holdings. Mutable; updated transactionally when trades
   execute. Fallback logic in the GET endpoint returns
   ``fund_selection_schema.funds`` (target weights) when no row exists,
   establishing zero-drift baseline on Go Live.

2. ``trade_tickets`` — append-only log of individual executed trade
   instructions (BUY / SELL). Each ``execute-trades`` POST inserts
   one row per trade in a single transaction, then updates the
   actual_holdings JSONB atomically.

Both tables are org-scoped with RLS using the ``(SELECT
current_setting(...))`` subselect pattern per CLAUDE.md.

Revision ID: 0107_shadow_oms
Revises: 0106_strategy_drift_alerts_acknowledged
Create Date: 2026-04-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision: str = "0107_shadow_oms"
down_revision: str = "0106_strategy_drift_alerts_acknowledged"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── portfolio_actual_holdings ──────────────────────────────────
    op.create_table(
        "portfolio_actual_holdings",
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("holdings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("last_rebalanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["model_portfolios.id"],
            name="fk_actual_holdings_portfolio",
            ondelete="CASCADE",
        ),
    )
    # RLS with (SELECT current_setting(...)) subselect per CLAUDE.md
    op.execute(
        "ALTER TABLE portfolio_actual_holdings ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """CREATE POLICY portfolio_actual_holdings_rls
           ON portfolio_actual_holdings
           USING (organization_id = (SELECT current_setting('app.current_organization_id'))::uuid)"""
    )

    # ── trade_tickets ─────────────────────────────────────────────
    op.create_table(
        "trade_tickets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("instrument_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("delta_weight", sa.Numeric(10, 6), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executed_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["model_portfolios.id"],
            name="fk_trade_tickets_portfolio",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("action IN ('BUY', 'SELL')", name="ck_trade_tickets_action"),
    )
    op.create_index(
        "ix_trade_tickets_portfolio_executed",
        "trade_tickets",
        ["portfolio_id", "executed_at"],
        postgresql_using="btree",
    )
    op.execute(
        "ALTER TABLE trade_tickets ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """CREATE POLICY trade_tickets_rls
           ON trade_tickets
           USING (organization_id = (SELECT current_setting('app.current_organization_id'))::uuid)"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS trade_tickets_rls ON trade_tickets")
    op.drop_index("ix_trade_tickets_portfolio_executed", table_name="trade_tickets")
    op.drop_table("trade_tickets")
    op.execute("DROP POLICY IF EXISTS portfolio_actual_holdings_rls ON portfolio_actual_holdings")
    op.drop_table("portfolio_actual_holdings")
