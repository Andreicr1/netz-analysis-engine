"""Add sec_insider_transactions table and sec_insider_sentiment materialized view.

Form 3/4/5 insider transactions for insider sentiment scoring.
Global table, no RLS, no hypertable (volume ~60k rows/quarter).

DDL applied via Tiger MCP — this migration is a no-op marker to keep
the Alembic chain consistent. The actual CREATE TABLE / CREATE INDEX /
CREATE MATERIALIZED VIEW were executed directly on Timescale Cloud.

Revision ID: 0067_insider_transactions
Revises: 0066_fund_class_xbrl_fees
Create Date: 2026-03-28
"""

from alembic import op

revision = "0067_insider_transactions"
down_revision = "0066_fund_class_xbrl_fees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DDL was applied via Tiger MCP directly to Timescale Cloud.
    # Table: sec_insider_transactions (PK: accession_number, trans_sk)
    # Materialized view: sec_insider_sentiment (unique on issuer_cik, quarter)
    # Indexes: issuer_cik, issuer_ticker, trans_date, trans_code, owner_relationship
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sec_insider_transactions (
            accession_number        VARCHAR NOT NULL,
            trans_sk                BIGINT NOT NULL,
            issuer_cik              VARCHAR NOT NULL,
            issuer_ticker           VARCHAR,
            owner_cik               VARCHAR NOT NULL,
            owner_name              VARCHAR,
            owner_relationship      VARCHAR,
            owner_title             VARCHAR,
            trans_date              DATE NOT NULL,
            period_of_report        DATE,
            document_type           VARCHAR(1),
            trans_code              VARCHAR(2) NOT NULL,
            trans_acquired_disp     VARCHAR(1),
            trans_shares            NUMERIC(20, 4),
            trans_price_per_share   NUMERIC(12, 4),
            trans_value             NUMERIC(20, 2)
                GENERATED ALWAYS AS (trans_shares * trans_price_per_share) STORED,
            shares_owned_after      NUMERIC(20, 4),
            PRIMARY KEY (accession_number, trans_sk)
        );

        CREATE INDEX IF NOT EXISTS idx_insider_trans_issuer_cik
            ON sec_insider_transactions(issuer_cik);
        CREATE INDEX IF NOT EXISTS idx_insider_trans_issuer_ticker
            ON sec_insider_transactions(issuer_ticker)
            WHERE issuer_ticker IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_insider_trans_date
            ON sec_insider_transactions(trans_date);
        CREATE INDEX IF NOT EXISTS idx_insider_trans_code
            ON sec_insider_transactions(trans_code);
        CREATE INDEX IF NOT EXISTS idx_insider_trans_relationship
            ON sec_insider_transactions(owner_relationship);
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS sec_insider_sentiment AS
        SELECT
            issuer_cik,
            MAX(issuer_ticker) AS issuer_ticker,
            date_trunc('quarter', trans_date)::date AS quarter,
            COUNT(*) FILTER (WHERE trans_code = 'P'
                AND owner_relationship NOT IN ('TenPercentOwner', 'TenPercentOwner,Other')
            ) AS buy_count,
            COUNT(*) FILTER (WHERE trans_code = 'S'
                AND owner_relationship NOT IN ('TenPercentOwner', 'TenPercentOwner,Other')
            ) AS sell_count,
            SUM(trans_value) FILTER (WHERE trans_code = 'P'
                AND owner_relationship NOT IN ('TenPercentOwner', 'TenPercentOwner,Other')
            ) AS buy_value,
            SUM(trans_value) FILTER (WHERE trans_code = 'S'
                AND owner_relationship NOT IN ('TenPercentOwner', 'TenPercentOwner,Other')
            ) AS sell_value,
            COUNT(DISTINCT owner_cik) FILTER (WHERE trans_code = 'P') AS unique_buyers,
            COUNT(DISTINCT owner_cik) FILTER (WHERE trans_code = 'S') AS unique_sellers
        FROM sec_insider_transactions
        WHERE trans_code IN ('P', 'S')
        GROUP BY issuer_cik,
                 date_trunc('quarter', trans_date)::date;

        CREATE UNIQUE INDEX IF NOT EXISTS sec_insider_sentiment_cik_quarter
            ON sec_insider_sentiment(issuer_cik, quarter);
        CREATE INDEX IF NOT EXISTS sec_insider_sentiment_ticker
            ON sec_insider_sentiment(issuer_ticker)
            WHERE issuer_ticker IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sec_insider_sentiment")
    op.execute("DROP TABLE IF EXISTS sec_insider_transactions")
