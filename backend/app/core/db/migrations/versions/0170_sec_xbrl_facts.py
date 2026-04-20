"""Add sec_xbrl_facts hypertable.

Revision ID: 0170_sec_xbrl_facts
Revises: 0169_add_cvar_evt_cols
Create Date: 2026-04-20
"""

from alembic import op

revision = "0170_sec_xbrl_facts"
down_revision = "0169_add_cvar_evt_cols"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Create table
    op.execute("""
        CREATE TABLE sec_xbrl_facts (
            cik BIGINT NOT NULL,
            taxonomy TEXT NOT NULL,
            concept TEXT NOT NULL,
            unit TEXT NOT NULL,
            period_end DATE NOT NULL,
            period_start DATE,
            val NUMERIC,
            val_text TEXT,
            accn TEXT NOT NULL,
            fy INT,
            fp TEXT,
            form TEXT NOT NULL,
            filed DATE NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (cik, taxonomy, concept, unit, period_end, accn)
        );
    """)

    # 2. Convert to hypertable
    op.execute("""
        SELECT create_hypertable(
            'sec_xbrl_facts', 
            'period_end', 
            chunk_time_interval => INTERVAL '1 year', 
            if_not_exists => TRUE
        );
    """)

    # 3. Create indexes
    op.execute("CREATE INDEX ix_sec_xbrl_facts_analytical ON sec_xbrl_facts (cik, taxonomy, concept, period_end DESC);")
    op.execute("CREATE INDEX ix_sec_xbrl_facts_cross_sectional ON sec_xbrl_facts (concept, period_end DESC) WHERE taxonomy = 'us-gaap';")
    op.execute("CREATE INDEX ix_sec_xbrl_facts_filed ON sec_xbrl_facts (filed DESC);")

    # 4. Compression
    op.execute("""
        ALTER TABLE sec_xbrl_facts SET (
            timescaledb.compress, 
            timescaledb.compress_segmentby = 'cik, concept', 
            timescaledb.compress_orderby = 'period_end DESC, accn'
        );
    """)
    op.execute("SELECT add_compression_policy('sec_xbrl_facts', INTERVAL '180 days');")


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('sec_xbrl_facts', if_exists => true);")
    op.execute("DROP TABLE IF EXISTS sec_xbrl_facts CASCADE;")
