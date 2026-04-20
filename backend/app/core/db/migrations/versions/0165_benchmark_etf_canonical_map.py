"""benchmark_etf_canonical_map + primary_benchmark on sec_registered_funds.

PR-Q5 (G3 Fase 3): canonical lookup table resolving any free-text fund
benchmark string ("S&P 500", "Bloomberg US Agg") to a single proxy ETF.
Feeds the Brinson-Fachler proxy rail when holdings-based attribution
degrades.

Global table (no RLS, no organization_id) — the map is universal. Low
cardinality (~20 rows at seed; expected <50 long-run), so a regular
CREATE TABLE (not a hypertable).

Also adds ``sec_registered_funds.primary_benchmark TEXT`` so the resolver
has a source field to read from. Populated by a later worker (PR-Q7
Tiingo fundamentals / N-CEN enrichment).

Spec: docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md §1.

depends_on: 0164 (CUSIP Tiingo enrichment).
"""

from __future__ import annotations

from alembic import op

revision = "0165_benchmark_etf_canonical_map"
down_revision = "0164_cusip_map_tiingo_enrichment"
branch_labels = None
depends_on = None


# Asset class taxonomy — matches the 20-row seed below. Extend with
# follow-up audit data rather than stuffing this file.
_ENUM_DDL = """
DO $$ BEGIN
    CREATE TYPE benchmark_asset_class AS ENUM (
        'equity_us_large', 'equity_us_mid', 'equity_us_small',
        'equity_intl_dev', 'equity_em',
        'fi_us_agg', 'fi_us_treasury', 'fi_us_hy', 'fi_us_ig', 'fi_us_muni',
        'fi_intl', 'commodities', 'reits', 'other'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""


_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS benchmark_etf_canonical_map (
    id                         BIGSERIAL PRIMARY KEY,
    benchmark_name_canonical   TEXT NOT NULL,
    benchmark_name_aliases     TEXT[] NOT NULL DEFAULT '{}',
    proxy_etf_ticker           TEXT NOT NULL,
    proxy_etf_cik              TEXT,
    proxy_etf_series_id        TEXT,
    asset_class                benchmark_asset_class NOT NULL,
    fit_quality_score          NUMERIC(4,3) NOT NULL DEFAULT 1.0
        CHECK (fit_quality_score >= 0 AND fit_quality_score <= 1),
    source                     TEXT NOT NULL DEFAULT 'manual_seed',
    notes                      TEXT,
    effective_from             DATE NOT NULL DEFAULT '1900-01-01',
    effective_to               DATE NOT NULL DEFAULT '9999-12-31',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_canonical_effective UNIQUE (benchmark_name_canonical, effective_from),
    CONSTRAINT chk_effective_range CHECK (effective_to > effective_from),
    CONSTRAINT chk_proxy_identifier CHECK (proxy_etf_cik IS NOT NULL OR proxy_etf_series_id IS NOT NULL OR proxy_etf_ticker IS NOT NULL)
)
"""


_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_benchmark_map_canonical_trgm "
    "ON benchmark_etf_canonical_map USING GIN (benchmark_name_canonical gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_benchmark_map_aliases_gin "
    "ON benchmark_etf_canonical_map USING GIN (benchmark_name_aliases)",
    "CREATE INDEX IF NOT EXISTS ix_benchmark_map_ticker "
    "ON benchmark_etf_canonical_map (proxy_etf_ticker)",
    "CREATE INDEX IF NOT EXISTS ix_benchmark_map_asset_class_active "
    "ON benchmark_etf_canonical_map (asset_class) "
    "WHERE effective_to = '9999-12-31'",
]


# 20 rows, (canonical, aliases, ticker, asset_class).
# chk_proxy_identifier is satisfied by ticker alone; cik/series_id
# backfilled opportunistically in a later data migration.
_SEED: list[tuple[str, list[str], str, str]] = [
    (
        "S&P 500",
        ["S&P 500", "S&P 500 Index", "S&P 500® Index",
         "Standard & Poor's 500", "Standard & Poor's 500 Index",
         "S&P 500 Total Return"],
        "SPY", "equity_us_large",
    ),
    (
        "Russell 2000",
        ["Russell 2000", "Russell 2000 Index",
         "Russell 2000® Index", "Russell 2000 Total Return"],
        "IWM", "equity_us_small",
    ),
    (
        "Russell 1000",
        ["Russell 1000", "Russell 1000 Index", "Russell 1000® Index"],
        "IWB", "equity_us_large",
    ),
    (
        "Russell Midcap",
        ["Russell Midcap", "Russell Midcap Index", "Russell Mid Cap"],
        "IWR", "equity_us_mid",
    ),
    (
        "Russell 3000",
        ["Russell 3000", "Russell 3000 Index", "Russell 3000® Index"],
        "IWV", "equity_us_large",
    ),
    (
        "MSCI EAFE",
        ["MSCI EAFE", "MSCI EAFE Index", "MSCI EAFE (Net)",
         "MSCI Europe Australasia Far East"],
        "EFA", "equity_intl_dev",
    ),
    (
        "MSCI ACWI ex-US",
        ["MSCI ACWI ex-US", "MSCI ACWI ex USA", "MSCI ACWI ex-USA Index",
         "MSCI All Country World ex-US"],
        "ACWX", "equity_intl_dev",
    ),
    (
        "MSCI Emerging Markets",
        ["MSCI Emerging Markets", "MSCI EM", "MSCI Emerging Markets Index",
         "MSCI EM Index"],
        "EEM", "equity_em",
    ),
    (
        "MSCI World",
        ["MSCI World", "MSCI World Index", "MSCI World (Net)"],
        "URTH", "equity_intl_dev",
    ),
    (
        "NASDAQ 100",
        ["NASDAQ 100", "Nasdaq 100", "NASDAQ-100 Index", "Nasdaq 100 Index"],
        "QQQ", "equity_us_large",
    ),
    (
        "Dow Jones Industrial Average",
        ["Dow Jones Industrial Average", "DJIA", "Dow Jones Industrial",
         "Dow 30"],
        "DIA", "equity_us_large",
    ),
    (
        "Bloomberg US Aggregate Bond",
        ["Bloomberg US Aggregate Bond", "Bloomberg US Agg",
         "Bloomberg US Aggregate", "Bloomberg Barclays US Aggregate",
         "Barclays US Aggregate Bond"],
        "AGG", "fi_us_agg",
    ),
    (
        "Bloomberg US Treasury",
        ["Bloomberg US Treasury", "Bloomberg US Treasury Index",
         "Bloomberg Barclays US Treasury"],
        "GOVT", "fi_us_treasury",
    ),
    (
        "ICE BofA US High Yield",
        ["ICE BofA US High Yield", "ICE BofA US High Yield Index",
         "Bloomberg US Corporate High Yield", "BBG US Corp HY"],
        "HYG", "fi_us_hy",
    ),
    (
        "Bloomberg US Corporate IG",
        ["Bloomberg US Corporate IG", "Bloomberg US Corporate Investment Grade",
         "Bloomberg Barclays US Corporate", "BBG US Corp"],
        "LQD", "fi_us_ig",
    ),
    (
        "Bloomberg Municipal",
        ["Bloomberg Municipal", "Bloomberg Municipal Bond",
         "Bloomberg Barclays Municipal", "US Municipal Bond Index"],
        "MUB", "fi_us_muni",
    ),
    (
        "Bloomberg Global Agg ex-USD",
        ["Bloomberg Global Agg ex-USD", "Bloomberg Global Aggregate ex-US",
         "Bloomberg Barclays Global Aggregate ex-US"],
        "BNDX", "fi_intl",
    ),
    (
        "Bloomberg Commodity",
        ["Bloomberg Commodity", "Bloomberg Commodity Index",
         "BCOM", "Bloomberg Commodity Total Return"],
        "DJP", "commodities",
    ),
    (
        "MSCI US REIT",
        ["MSCI US REIT", "MSCI US REIT Index", "FTSE NAREIT Equity REITs",
         "MSCI US Investable Market REIT"],
        "VNQ", "reits",
    ),
    (
        "S&P Target Date",
        ["S&P Target Date", "S&P Target Date Index",
         "Morningstar Lifetime Moderate"],
        "AOR", "other",
    ),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(_ENUM_DDL)
    op.execute(_TABLE_DDL)
    for ddl in _INDEXES:
        op.execute(ddl)

    # Add primary_benchmark text column to sec_registered_funds so the
    # resolver has a source field. Populated by a downstream N-CEN/Tiingo
    # backfill worker (PR-Q7).
    op.execute("""
        ALTER TABLE sec_registered_funds
        ADD COLUMN IF NOT EXISTS primary_benchmark TEXT
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_registered_funds_benchmark
            ON sec_registered_funds (primary_benchmark)
            WHERE primary_benchmark IS NOT NULL
    """)

    # Seed 20 rows. Re-runnable: ON CONFLICT on the canonical+effective_from uq.
    bind = op.get_bind()
    for canonical, aliases, ticker, asset_class in _SEED:
        bind.execute(
            _seed_stmt(),
            {
                "canonical": canonical,
                "aliases": aliases,
                "ticker": ticker,
                "asset_class": asset_class,
            },
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sec_registered_funds_benchmark")
    op.execute("""
        ALTER TABLE sec_registered_funds
        DROP COLUMN IF EXISTS primary_benchmark
    """)
    op.execute("DROP INDEX IF EXISTS ix_benchmark_map_asset_class_active")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_map_ticker")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_map_aliases_gin")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_map_canonical_trgm")
    op.execute("DROP TABLE IF EXISTS benchmark_etf_canonical_map")
    op.execute("DROP TYPE IF EXISTS benchmark_asset_class")
    # pg_trgm left intact — may be used by other features.


def _seed_stmt():
    from sqlalchemy import text

    return text("""
        INSERT INTO benchmark_etf_canonical_map (
            benchmark_name_canonical, benchmark_name_aliases,
            proxy_etf_ticker, asset_class, source
        ) VALUES (
            :canonical, :aliases, :ticker, CAST(:asset_class AS benchmark_asset_class),
            'manual_seed_0165'
        )
        ON CONFLICT (benchmark_name_canonical, effective_from) DO UPDATE
            SET benchmark_name_aliases = EXCLUDED.benchmark_name_aliases,
                proxy_etf_ticker = EXCLUDED.proxy_etf_ticker,
                asset_class = EXCLUDED.asset_class,
                updated_at = now()
    """)
