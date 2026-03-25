"""Add sec_registered_funds and sec_fund_style_snapshots tables.

Registered fund catalog (mutual funds, ETFs, closed-end, interval funds)
discovered via EDGAR N-PORT filings, plus style classification snapshots
derived from N-PORT holdings.

GLOBAL TABLES: No organization_id, no RLS.
"""

revision = "0054_sec_registered_funds"
down_revision = "0053_widen_instrument_isin"

from alembic import op


def upgrade() -> None:
    # ── sec_registered_funds ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sec_registered_funds (
            cik                          TEXT PRIMARY KEY,
            crd_number                   TEXT REFERENCES sec_managers(crd_number) ON DELETE SET NULL,
            fund_name                    TEXT NOT NULL,
            fund_type                    TEXT NOT NULL
                CHECK (fund_type IN ('mutual_fund', 'etf', 'closed_end', 'interval_fund')),
            ticker                       TEXT,
            isin                         TEXT,
            series_id                    TEXT,
            class_id                     TEXT,
            total_assets                 BIGINT,
            total_shareholder_accounts   INTEGER,
            inception_date               DATE,
            fiscal_year_end              TEXT,
            currency                     TEXT NOT NULL DEFAULT 'USD',
            domicile                     TEXT NOT NULL DEFAULT 'US',
            last_nport_date              DATE,
            aum_below_threshold          BOOLEAN NOT NULL DEFAULT FALSE,
            data_fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_registered_funds_crd
            ON sec_registered_funds (crd_number) WHERE crd_number IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_registered_funds_type
            ON sec_registered_funds (fund_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_registered_funds_ticker
            ON sec_registered_funds (ticker) WHERE ticker IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_registered_funds_assets
            ON sec_registered_funds (total_assets DESC NULLS LAST)
            WHERE aum_below_threshold = FALSE
    """)

    # ── sec_fund_style_snapshots ───────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sec_fund_style_snapshots (
            cik              TEXT NOT NULL,
            report_date      DATE NOT NULL,
            style_label      TEXT NOT NULL,
            growth_tilt      FLOAT NOT NULL,
            sector_weights   JSONB NOT NULL,
            equity_pct       FLOAT,
            fixed_income_pct FLOAT,
            cash_pct         FLOAT,
            confidence       FLOAT NOT NULL,
            PRIMARY KEY (cik, report_date)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_fund_style_cik_date
            ON sec_fund_style_snapshots (cik, report_date DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sec_fund_style_snapshots")
    op.execute("DROP TABLE IF EXISTS sec_registered_funds")
