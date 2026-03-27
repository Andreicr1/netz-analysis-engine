"""Add indexes for screener redesign + US Fund Analysis performance.

Covers:
- sec_managers: AUM sorting for advisers, client_types GIN for strategy filter,
  last_adv_filed_at for Last Filing column, partial index for Registered advisers
- instruments_global: exchange, market_cap, JSONB attributes GIN
- sec_manager_funds: fund_type for aggregation

depends_on: 0046 (screener_indexes).
"""

from alembic import op

revision = "0047_screener_redesign_indexes"
down_revision = "0046_screener_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sec_managers ──────────────────────────────────────────────────

    # Partial index: Registered advisers sorted by AUM (Funds tab + US Fund Analysis)
    # Covers: WHERE registration_status = 'Registered' ORDER BY aum_total DESC
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_registered_aum
        ON sec_managers (aum_total DESC NULLS LAST)
        WHERE registration_status = 'Registered'
        """,
    )

    # GIN on client_types JSONB for strategy/SIC filtering
    # Covers: WHERE client_types @> '{"sic": "6726"}' and general containment queries
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_client_types_gin
        ON sec_managers USING gin (client_types jsonb_path_ops)
        WHERE client_types IS NOT NULL
        """,
    )

    # Last ADV filing date for "Last Filing" column sort + display
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_last_adv_filed
        ON sec_managers (last_adv_filed_at DESC NULLS LAST)
        WHERE last_adv_filed_at IS NOT NULL
        """,
    )

    # Composite: registration_status + AUM for filtered sort (covers both tabs)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_status_aum
        ON sec_managers (registration_status, aum_total DESC NULLS LAST)
        """,
    )

    # ── instruments_global ────────────────────────────────────────────

    # Exchange for SOURCE badge filtering (NMS, NYQ, PCX etc.)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_instruments_global_exchange
        ON instruments_global (exchange)
        WHERE exchange IS NOT NULL
        """,
    )

    # Market cap for Equities tab min filter + sort
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_instruments_global_market_cap
        ON instruments_global (market_cap DESC NULLS LAST)
        WHERE market_cap IS NOT NULL
        """,
    )

    # GIN on attributes JSONB for ETF/Bond tab-specific filters
    # Covers: attributes->>'expense_ratio', attributes->>'ytm', attributes->>'fund_family'
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_instruments_global_attributes_gin
        ON instruments_global USING gin (attributes jsonb_path_ops)
        """,
    )

    # Composite: instrument_type + market_cap (Equities tab sorted by cap)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_instruments_global_type_cap
        ON instruments_global (instrument_type, market_cap DESC NULLS LAST)
        """,
    )

    # ── sec_manager_funds ─────────────────────────────────────────────

    # Fund type for strategy aggregation per manager
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_manager_funds_type
        ON sec_manager_funds (fund_type)
        WHERE fund_type IS NOT NULL
        """,
    )

    # CRD + fund type composite for per-manager strategy breakdown
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_manager_funds_crd_type
        ON sec_manager_funds (crd_number, fund_type)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sec_manager_funds_crd_type")
    op.execute("DROP INDEX IF EXISTS idx_sec_manager_funds_type")
    op.execute("DROP INDEX IF EXISTS idx_instruments_global_type_cap")
    op.execute("DROP INDEX IF EXISTS idx_instruments_global_attributes_gin")
    op.execute("DROP INDEX IF EXISTS idx_instruments_global_market_cap")
    op.execute("DROP INDEX IF EXISTS idx_instruments_global_exchange")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_status_aum")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_last_adv_filed")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_client_types_gin")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_registered_aum")
