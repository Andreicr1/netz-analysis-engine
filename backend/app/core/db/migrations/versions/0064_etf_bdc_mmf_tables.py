"""Dedicated tables for ETFs, BDCs, and Money Market Funds.

Migrates etf/bdc/money_market rows out of sec_registered_funds into
purpose-built tables with EDGAR-derived schemas (N-CEN + N-MFP).
sec_mmf_metrics is a TimescaleDB hypertable for daily MMF time-series.

All four tables are GLOBAL: no organization_id, no RLS.

Revision ID: 0064_etf_bdc_mmf_tables
Revises: 0063_add_strategy_label
Create Date: 2026-03-28
"""

from alembic import op

revision = "0064_etf_bdc_mmf_tables"
down_revision = "0063_add_strategy_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. sec_etfs ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sec_etfs (
            series_id                   VARCHAR PRIMARY KEY,
            cik                         VARCHAR NOT NULL,
            fund_id                     VARCHAR,
            fund_name                   VARCHAR NOT NULL,
            lei                         VARCHAR,
            ticker                      VARCHAR,
            isin                        VARCHAR,

            strategy_label              VARCHAR,
            asset_class                 VARCHAR,
            index_tracked               VARCHAR,
            is_index                    BOOLEAN DEFAULT TRUE,
            is_in_kind_etf              BOOLEAN,

            creation_unit_size          INTEGER,
            pct_in_kind_creation        NUMERIC(8, 4),
            pct_in_kind_redemption      NUMERIC(8, 4),
            tracking_difference_gross   NUMERIC(8, 4),
            tracking_difference_net     NUMERIC(8, 4),

            management_fee              NUMERIC(8, 4),
            net_operating_expenses      NUMERIC(8, 4),
            return_before_fees          NUMERIC(8, 4),
            return_after_fees           NUMERIC(8, 4),

            monthly_avg_net_assets      NUMERIC(20, 2),
            daily_avg_net_assets        NUMERIC(20, 2),
            nav_per_share               NUMERIC(12, 4),
            market_price_per_share      NUMERIC(12, 4),

            is_sec_lending_authorized   BOOLEAN,
            did_lend_securities         BOOLEAN,
            has_expense_limit           BOOLEAN,

            ncen_report_date            DATE,
            domicile                    VARCHAR(2) DEFAULT 'US',
            currency                    VARCHAR(3) DEFAULT 'USD',
            inception_date              DATE,
            created_at                  TIMESTAMPTZ DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_sec_etfs_cik ON sec_etfs(cik);")
    op.execute("CREATE INDEX idx_sec_etfs_ticker ON sec_etfs(ticker) WHERE ticker IS NOT NULL;")
    op.execute("CREATE INDEX idx_sec_etfs_strategy ON sec_etfs(strategy_label) WHERE strategy_label IS NOT NULL;")

    # ── 2. sec_bdcs ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sec_bdcs (
            series_id                   VARCHAR PRIMARY KEY,
            cik                         VARCHAR NOT NULL,
            fund_id                     VARCHAR,
            fund_name                   VARCHAR NOT NULL,
            lei                         VARCHAR,
            ticker                      VARCHAR,
            isin                        VARCHAR,

            strategy_label              VARCHAR DEFAULT 'Private Credit',
            investment_focus            VARCHAR,

            management_fee              NUMERIC(8, 4),
            net_operating_expenses      NUMERIC(8, 4),
            return_before_fees          NUMERIC(8, 4),
            return_after_fees           NUMERIC(8, 4),

            monthly_avg_net_assets      NUMERIC(20, 2),
            daily_avg_net_assets        NUMERIC(20, 2),
            nav_per_share               NUMERIC(12, 4),
            market_price_per_share      NUMERIC(12, 4),

            is_externally_managed       BOOLEAN,
            is_sec_lending_authorized   BOOLEAN,
            has_line_of_credit          BOOLEAN,
            has_interfund_borrowing     BOOLEAN,

            ncen_report_date            DATE,
            domicile                    VARCHAR(2) DEFAULT 'US',
            currency                    VARCHAR(3) DEFAULT 'USD',
            inception_date              DATE,
            created_at                  TIMESTAMPTZ DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_sec_bdcs_cik ON sec_bdcs(cik);")
    op.execute("CREATE INDEX idx_sec_bdcs_ticker ON sec_bdcs(ticker) WHERE ticker IS NOT NULL;")

    # ── 3. sec_money_market_funds ────────────────────────────────────
    op.execute("""
        CREATE TABLE sec_money_market_funds (
            series_id                   VARCHAR PRIMARY KEY,
            cik                         VARCHAR NOT NULL,
            accession_number            VARCHAR,
            fund_name                   VARCHAR NOT NULL,
            lei_series                  VARCHAR,
            lei_registrant              VARCHAR,

            mmf_category                VARCHAR NOT NULL
                CHECK (mmf_category IN ('Government', 'Prime', 'Other Tax Exempt', 'Single State')),
            strategy_label              VARCHAR,
            is_govt_fund                BOOLEAN,
            is_retail                   BOOLEAN,
            is_exempt_retail            BOOLEAN,

            weighted_avg_maturity       INTEGER,
            weighted_avg_life           INTEGER,
            seven_day_gross_yield       NUMERIC(8, 4),

            net_assets                  NUMERIC(20, 2),
            shares_outstanding          NUMERIC(20, 2),
            total_portfolio_securities  NUMERIC(20, 2),
            cash                        NUMERIC(20, 2),

            pct_daily_liquid_latest     NUMERIC(8, 4),
            pct_weekly_liquid_latest    NUMERIC(8, 4),

            seeks_stable_nav            BOOLEAN,
            stable_nav_price            NUMERIC(12, 6),

            reporting_period            DATE,
            investment_adviser          VARCHAR,
            domicile                    VARCHAR(2) DEFAULT 'US',
            currency                    VARCHAR(3) DEFAULT 'USD',
            created_at                  TIMESTAMPTZ DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_sec_mmf_cik ON sec_money_market_funds(cik);")
    op.execute("CREATE INDEX idx_sec_mmf_category ON sec_money_market_funds(mmf_category);")

    # ── 4. sec_mmf_metrics (hypertable) ──────────────────────────────
    op.execute("""
        CREATE TABLE sec_mmf_metrics (
            metric_date                 DATE NOT NULL,
            series_id                   VARCHAR NOT NULL
                REFERENCES sec_money_market_funds(series_id),
            class_id                    VARCHAR NOT NULL,
            accession_number            VARCHAR NOT NULL,

            seven_day_net_yield         NUMERIC(8, 4),

            daily_gross_subscriptions   NUMERIC(20, 2),
            daily_gross_redemptions     NUMERIC(20, 2),

            pct_daily_liquid            NUMERIC(8, 4),
            pct_weekly_liquid           NUMERIC(8, 4),
            total_daily_liquid_assets   NUMERIC(20, 2),
            total_weekly_liquid_assets  NUMERIC(20, 2),

            PRIMARY KEY (metric_date, series_id, class_id)
        );
    """)
    op.execute("""
        SELECT create_hypertable(
            'sec_mmf_metrics',
            'metric_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    """)
    op.execute("""
        ALTER TABLE sec_mmf_metrics SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'series_id,class_id'
        );
    """)
    op.execute("""
        SELECT add_compression_policy('sec_mmf_metrics', INTERVAL '3 months', if_not_exists => TRUE);
    """)

    # ── 5. Data migration from sec_registered_funds ──────────────────
    op.execute("""
        INSERT INTO sec_etfs (series_id, cik, fund_name, ticker, isin,
            strategy_label, monthly_avg_net_assets, inception_date, currency)
        SELECT COALESCE(series_id, cik), cik, fund_name, ticker, isin,
            strategy_label, total_assets, inception_date, currency
        FROM sec_registered_funds WHERE fund_type = 'etf'
        ON CONFLICT (series_id) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO sec_bdcs (series_id, cik, fund_name, ticker, isin,
            strategy_label, monthly_avg_net_assets, inception_date, currency)
        SELECT COALESCE(series_id, cik), cik, fund_name, ticker, isin,
            strategy_label, total_assets, inception_date, currency
        FROM sec_registered_funds WHERE fund_type = 'bdc'
        ON CONFLICT (series_id) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO sec_money_market_funds (series_id, cik, fund_name,
            mmf_category, strategy_label, currency)
        SELECT COALESCE(series_id, cik), cik, fund_name,
            CASE
                WHEN strategy_label ILIKE '%government%' THEN 'Government'
                WHEN strategy_label ILIKE '%tax%exempt%' THEN 'Other Tax Exempt'
                ELSE 'Prime'
            END,
            strategy_label, currency
        FROM sec_registered_funds WHERE fund_type = 'money_market'
        ON CONFLICT (series_id) DO NOTHING;
    """)

    # Remove migrated rows
    op.execute("""
        DELETE FROM sec_registered_funds
        WHERE fund_type IN ('etf', 'bdc', 'money_market');
    """)

    # Update check constraint
    op.execute("""
        ALTER TABLE sec_registered_funds
            DROP CONSTRAINT IF EXISTS sec_registered_funds_fund_type_check;
    """)
    op.execute("""
        ALTER TABLE sec_registered_funds
            ADD CONSTRAINT sec_registered_funds_fund_type_check
            CHECK (fund_type IN ('mutual_fund', 'closed_end', 'interval_fund'));
    """)

    # ── 6. Record in alembic_version ─────────────────────────────────
    # (Handled automatically by alembic when run via CLI)


def downgrade() -> None:
    # Move data back
    op.execute("""
        INSERT INTO sec_registered_funds (cik, fund_name, fund_type, ticker, isin,
            strategy_label, total_assets, inception_date, currency, series_id)
        SELECT cik, fund_name, 'etf', ticker, isin,
            strategy_label, monthly_avg_net_assets, inception_date, currency, series_id
        FROM sec_etfs
        ON CONFLICT (cik) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO sec_registered_funds (cik, fund_name, fund_type, ticker, isin,
            strategy_label, total_assets, inception_date, currency, series_id)
        SELECT cik, fund_name, 'bdc', ticker, isin,
            strategy_label, monthly_avg_net_assets, inception_date, currency, series_id
        FROM sec_bdcs
        ON CONFLICT (cik) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO sec_registered_funds (cik, fund_name, fund_type, ticker, isin,
            strategy_label, currency, series_id)
        SELECT cik, fund_name, 'money_market', NULL, NULL,
            strategy_label, currency, series_id
        FROM sec_money_market_funds
        ON CONFLICT (cik) DO NOTHING;
    """)

    # Restore constraint
    op.execute("ALTER TABLE sec_registered_funds DROP CONSTRAINT IF EXISTS sec_registered_funds_fund_type_check;")

    # Drop tables in reverse order (FK dependency)
    op.execute("DROP TABLE IF EXISTS sec_mmf_metrics;")
    op.execute("DROP TABLE IF EXISTS sec_money_market_funds;")
    op.execute("DROP TABLE IF EXISTS sec_bdcs;")
    op.execute("DROP TABLE IF EXISTS sec_etfs;")
