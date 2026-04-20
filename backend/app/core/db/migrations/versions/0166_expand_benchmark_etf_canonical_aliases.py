"""Expand benchmark_etf_canonical_map for Q5.1 backfill.

Phase A1 of PR-Q5.1: Q5's 20-row seed covered only the major broad
indices. The A0 discovery scan of ~5,400 fund descriptions surfaced
~1,500 unresolved extractions concentrated in style/cap slices
(Russell Growth/Value, S&P MidCap 400, S&P SmallCap 600), Bloomberg
fixed-income sub-indices, and single-country MSCI benchmarks.

This migration:
1. UPDATEs 6 existing canonical rows to absorb spacing / U.S. vs US /
   ® variants spotted in the A0 CSV.
2. INSERTs 24 new rows covering the top unresolved extractions, each
   mapped to an institutional-grade proxy ETF.

No schema change — data only. Idempotent via the unique
(benchmark_name_canonical, effective_from) constraint.

depends_on: 0165.
"""

from __future__ import annotations

from alembic import op

revision = "0166_expand_benchmark_etf_canonical_aliases"
down_revision = "0165_benchmark_etf_canonical_map"
branch_labels = None
depends_on = None


# (canonical, merged-aliases list, proxy_ticker, asset_class)
# UPDATEs: rows that already exist in 0165 seed — aliases are *replaced*
# wholesale with the union of old+new so downgrade can restore deterministically.
_ALIAS_UPDATES: list[tuple[str, list[str]]] = [
    (
        "S&P 500",
        [
            "S&P 500", "S&P 500 Index", "S&P 500® Index", "S&P 500®Index",
            "S&P 500® Total Return Index",
            "Standard & Poor's 500", "Standard & Poor's 500 Index",
            "S&P 500 Total Return",
        ],
    ),
    (
        "Russell 2000",
        [
            "Russell 2000", "Russell 2000 Index", "Russell 2000® Index",
            "Russell 2000®Index", "Russell 2000 Total Return",
        ],
    ),
    (
        "Russell 1000",
        [
            "Russell 1000", "Russell 1000 Index", "Russell 1000® Index",
            "Russell 1000®Index",
        ],
    ),
    (
        "Russell Midcap",
        [
            "Russell Midcap", "Russell Midcap Index", "Russell Midcap® Index",
            "Russell Midcap®Index", "Russell Mid Cap",
        ],
    ),
    (
        "Russell 3000",
        [
            "Russell 3000", "Russell 3000 Index", "Russell 3000® Index",
            "Russell 3000®Index",
        ],
    ),
    (
        "Bloomberg US Aggregate Bond",
        [
            "Bloomberg US Aggregate Bond", "Bloomberg US Aggregate Bond Index",
            "Bloomberg U.S. Aggregate Bond Index",
            "Bloomberg US Aggregate", "Bloomberg US Aggregate Index",
            "Bloomberg U.S. Aggregate Index",
            "Bloomberg US Agg",
            "Bloomberg Barclays US Aggregate", "Barclays US Aggregate Bond",
        ],
    ),
    (
        "Bloomberg Municipal",
        [
            "Bloomberg Municipal", "Bloomberg Municipal Bond",
            "Bloomberg Municipal Bond Index",
            "Bloomberg Barclays Municipal", "US Municipal Bond Index",
        ],
    ),
    (
        "ICE BofA US High Yield",
        [
            "ICE BofA US High Yield", "ICE BofA US High Yield Index",
            "ICE BofA US High Yield Constrained Index",
            "ICE® BofA® US High Yield Constrained Index",
            "Bloomberg US Corporate High Yield", "BBG US Corp HY",
        ],
    ),
]


# New canonical rows from A0 unresolved cluster analysis. Proxy ETFs are
# the institutional default for each slice (iShares/Vanguard/SPDR).
_NEW_ROWS: list[tuple[str, list[str], str, str]] = [
    # Russell style / cap slices ---------------------------------------
    ("Russell 1000 Value",
     ["Russell 1000 Value", "Russell 1000 Value Index",
      "Russell 1000® Value Index", "Russell 1000®Value Index"],
     "IWD", "equity_us_large"),
    ("Russell 1000 Growth",
     ["Russell 1000 Growth", "Russell 1000 Growth Index",
      "Russell 1000® Growth Index", "Russell 1000®Growth Index"],
     "IWF", "equity_us_large"),
    ("Russell 2000 Value",
     ["Russell 2000 Value", "Russell 2000 Value Index",
      "Russell 2000® Value Index", "Russell 2000®Value Index"],
     "IWN", "equity_us_small"),
    ("Russell 2000 Growth",
     ["Russell 2000 Growth", "Russell 2000 Growth Index",
      "Russell 2000® Growth Index", "Russell 2000®Growth Index"],
     "IWO", "equity_us_small"),
    ("Russell Midcap Value",
     ["Russell Midcap Value", "Russell Midcap Value Index",
      "Russell Midcap® Value Index", "Russell Midcap®Value Index"],
     "IWS", "equity_us_mid"),
    ("Russell Midcap Growth",
     ["Russell Midcap Growth", "Russell Midcap Growth Index",
      "Russell Midcap® Growth Index", "Russell Midcap®Growth Index"],
     "IWP", "equity_us_mid"),
    ("Russell 2500",
     ["Russell 2500", "Russell 2500 Index",
      "Russell 2500® Index", "Russell 2500™ Index", "Russell 2500TM Index"],
     "SMMD", "equity_us_mid"),
    ("Russell 2500 Value",
     ["Russell 2500 Value", "Russell 2500 Value Index",
      "Russell 2500® Value Index"],
     "IJS", "equity_us_small"),
    ("Russell 2500 Growth",
     ["Russell 2500 Growth", "Russell 2500 Growth Index",
      "Russell 2500® Growth Index"],
     "IJT", "equity_us_small"),
    ("Russell Microcap",
     ["Russell Microcap", "Russell Microcap Index",
      "Russell Microcap® Index"],
     "IWC", "equity_us_small"),
    # S&P cap slices ---------------------------------------------------
    ("S&P MidCap 400",
     ["S&P MidCap 400", "S&P MidCap 400 Index",
      "S&P MidCap 400® Index", "S&P 400", "S&P 400 Index"],
     "MDY", "equity_us_mid"),
    ("S&P SmallCap 600",
     ["S&P SmallCap 600", "S&P SmallCap 600 Index",
      "S&P SmallCap 600® Index", "S&P 600", "S&P 600 Index"],
     "IJR", "equity_us_small"),
    ("S&P Total Market",
     ["S&P Total Market", "S&P Total Market Index",
      "S&P Composite 1500", "S&P Composite 1500 Index"],
     "ITOT", "equity_us_large"),
    # MSCI global & single-country ------------------------------------
    ("MSCI ACWI",
     ["MSCI ACWI", "MSCI ACWI Index",
      "MSCI All Country World Index", "MSCI All Country World",
      "MSCI ACWI (All Country World Index)"],
     "ACWI", "equity_intl_dev"),
    ("MSCI World ex-USA",
     ["MSCI World ex-USA", "MSCI World ex USA Index",
      "MSCI World ex-USA Index", "MSCI World ex-US", "MSCI World ex US"],
     "ACWX", "equity_intl_dev"),
    ("MSCI EAFE Small Cap",
     ["MSCI EAFE Small Cap", "MSCI EAFE Small Cap Index",
      "MSCI EAFE Small-Cap Index"],
     "SCZ", "equity_intl_dev"),
    ("MSCI Emerging Markets Small Cap",
     ["MSCI Emerging Markets Small Cap",
      "MSCI Emerging Markets Small Cap Index",
      "MSCI EM Small Cap Index"],
     "EEMS", "equity_em"),
    ("MSCI Japan",
     ["MSCI Japan", "MSCI Japan Index"],
     "EWJ", "equity_intl_dev"),
    ("MSCI China",
     ["MSCI China", "MSCI China Index", "MSCI China All Shares Index"],
     "MCHI", "equity_em"),
    ("MSCI US Investable Market",
     ["MSCI US Investable Market", "MSCI US Investable Market Index",
      "MSCI USA IMI Index"],
     "ITOT", "equity_us_large"),
    ("MSCI USA Large Cap",
     ["MSCI USA Large Cap", "MSCI USA Large Cap Index",
      "MSCI USA Large-Cap Index"],
     "VONE", "equity_us_large"),
    # Fixed income extensions -----------------------------------------
    ("Bloomberg US Long Treasury",
     ["Bloomberg US Long Treasury", "Bloomberg US Long Treasury Bond Index",
      "Bloomberg U.S. Long Treasury Bond Index"],
     "TLT", "fi_us_treasury"),
    ("Bloomberg US TIPS",
     ["Bloomberg US TIPS", "Bloomberg US TIPS Index",
      "Bloomberg U.S. Treasury Inflation-Protected Securities (TIPS) Index",
      "Bloomberg US Treasury Inflation-Protected Securities (TIPS) Index"],
     "TIP", "fi_us_treasury"),
    ("JP Morgan Emerging Markets Bond",
     ["JP Morgan Emerging Markets Bond",
      "JP Morgan Emerging Markets Bond Index",
      "J.P. Morgan Emerging Market Bond Index",
      "J.P. Morgan EMBI Global", "EMBI Global Diversified"],
     "EMB", "fi_intl"),
]


def upgrade() -> None:
    from sqlalchemy import text

    bind = op.get_bind()
    update_stmt = text("""
        UPDATE benchmark_etf_canonical_map
           SET benchmark_name_aliases = :aliases,
               updated_at = now()
         WHERE benchmark_name_canonical = :canonical
           AND effective_to = '9999-12-31'
    """)
    for canonical, aliases in _ALIAS_UPDATES:
        bind.execute(update_stmt, {"canonical": canonical, "aliases": aliases})

    insert_stmt = text("""
        INSERT INTO benchmark_etf_canonical_map (
            benchmark_name_canonical, benchmark_name_aliases,
            proxy_etf_ticker, asset_class, source, fit_quality_score
        ) VALUES (
            :canonical, :aliases, :ticker,
            CAST(:asset_class AS benchmark_asset_class),
            'manual_seed_0166',
            :fit
        )
        ON CONFLICT (benchmark_name_canonical, effective_from) DO UPDATE
            SET benchmark_name_aliases = EXCLUDED.benchmark_name_aliases,
                proxy_etf_ticker       = EXCLUDED.proxy_etf_ticker,
                asset_class            = EXCLUDED.asset_class,
                updated_at             = now()
    """)
    for canonical, aliases, ticker, asset_class in _NEW_ROWS:
        # Style/cap slices have slightly looser proxy fit than broad
        # indices — score 0.90 vs 1.0 for the 0165 seed.
        bind.execute(
            insert_stmt,
            {
                "canonical": canonical,
                "aliases": aliases,
                "ticker": ticker,
                "asset_class": asset_class,
                "fit": 0.90,
            },
        )


def downgrade() -> None:
    from sqlalchemy import text

    bind = op.get_bind()
    # Revert alias lists for existing rows to their 0165-seed values.
    _ORIGINAL_0165_ALIASES: list[tuple[str, list[str]]] = [
        (
            "S&P 500",
            ["S&P 500", "S&P 500 Index", "S&P 500® Index",
             "Standard & Poor's 500", "Standard & Poor's 500 Index",
             "S&P 500 Total Return"],
        ),
        (
            "Russell 2000",
            ["Russell 2000", "Russell 2000 Index",
             "Russell 2000® Index", "Russell 2000 Total Return"],
        ),
        (
            "Russell 1000",
            ["Russell 1000", "Russell 1000 Index", "Russell 1000® Index"],
        ),
        (
            "Russell Midcap",
            ["Russell Midcap", "Russell Midcap Index", "Russell Mid Cap"],
        ),
        (
            "Russell 3000",
            ["Russell 3000", "Russell 3000 Index", "Russell 3000® Index"],
        ),
        (
            "Bloomberg US Aggregate Bond",
            ["Bloomberg US Aggregate Bond", "Bloomberg US Agg",
             "Bloomberg US Aggregate", "Bloomberg Barclays US Aggregate",
             "Barclays US Aggregate Bond"],
        ),
        (
            "Bloomberg Municipal",
            ["Bloomberg Municipal", "Bloomberg Municipal Bond",
             "Bloomberg Barclays Municipal", "US Municipal Bond Index"],
        ),
        (
            "ICE BofA US High Yield",
            ["ICE BofA US High Yield", "ICE BofA US High Yield Index",
             "Bloomberg US Corporate High Yield", "BBG US Corp HY"],
        ),
    ]
    revert = text("""
        UPDATE benchmark_etf_canonical_map
           SET benchmark_name_aliases = :aliases,
               updated_at = now()
         WHERE benchmark_name_canonical = :canonical
           AND effective_to = '9999-12-31'
    """)
    for canonical, aliases in _ORIGINAL_0165_ALIASES:
        bind.execute(revert, {"canonical": canonical, "aliases": aliases})

    delete_stmt = text("""
        DELETE FROM benchmark_etf_canonical_map
         WHERE benchmark_name_canonical = :canonical
           AND source = 'manual_seed_0166'
           AND effective_to = '9999-12-31'
    """)
    for canonical, _aliases, _ticker, _ac in _NEW_ROWS:
        bind.execute(delete_stmt, {"canonical": canonical})
