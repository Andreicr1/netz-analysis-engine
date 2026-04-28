"""Backfill is_ucits_etf boolean tag on UCITS instruments.

UCITS is a regulatory umbrella covering both ETFs (intraday tradeable on
LSE/Xetra/Borsa/Euronext) and mutual funds (cut-off subscription T+1/T+2).
This tag differentiates the two for UI badges, frontend filters, DD reports,
and portfolio construction strategy. NOT a Layer 1 gate (Q79 removed
structure-based gating).

Derived from case-insensitive word-boundary regex on instrument name
matching "ETF" or "exchange-traded".

Idempotent: skips rows that already have the is_ucits_etf attribute.

Revision ID: 0188_ucits_etf_tag_backfill
Revises: 0187_screener_l1_remove_domicile_structure
Create Date: 2026-04-28
"""

from alembic import op

revision = "0188_ucits_etf_tag_backfill"
down_revision = "0187_screener_l1_remove_domicile_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE instruments_universe
        SET attributes = attributes || jsonb_build_object(
            'is_ucits_etf',
            name ~* '\\m(etf|exchange.traded)\\M'
        )
        WHERE attributes->>'fund_subtype' = 'ucits'
          AND NOT (attributes ? 'is_ucits_etf')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE instruments_universe
        SET attributes = attributes - 'is_ucits_etf'
        WHERE attributes->>'fund_subtype' = 'ucits'
    """)
