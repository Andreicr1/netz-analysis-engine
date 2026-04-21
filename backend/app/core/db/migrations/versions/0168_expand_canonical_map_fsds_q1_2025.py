"""Expand benchmark_etf_canonical_map from SEC FSDS Q1 2025 RR-1 slice.

Phase A of PR-Q5.1.3: the Q1 2025 lab.tsv slice of SEC Financial
Statement Data Sets surfaced 135 benchmark label variants spanning 81
unique (proxy ETF, asset class) buckets. This migration embeds the
audited mappings so the subsequent backfill script can resolve every
Q1 2025 filing's benchmark Member label to a canonical proxy ETF.

Source of truth for every row here:
    docs/diagnostics/2026-04-20-canonical-map-expansion-proposal.csv

Grouping rule (applied at migration-build time, not runtime):
- Collapse 135 CSV rows by (proposed_etf_ticker, asset_class enum).
- Merge all variants (canonical_name + top_raw_aliases) into a single
  alias array per bucket.
- Pick the cleanest canonical name via a deterministic scorer that
  penalizes boilerplate ("reflects no deduction"), trailing punctuation,
  unspaced "U.S.Index" artifacts, and all-uppercase variants.

Application rule (applied at upgrade time):
- If a row with the same (proxy_etf_ticker, asset_class) already exists
  (e.g. from 0165 seed or 0166 expansion), MERGE the new aliases into
  the existing row. Never duplicate the canonical identity.
- Otherwise INSERT a new row tagged source='fsds_q1_2025_slice_0168'
  with fit_quality_score = 0.92 (data-validated from FSDS, half-step
  above 0166's manual 0.90).

Asset-class ENUM is intentionally unchanged: finer-grained CSV labels
(equity_us_large_value, fi_us_cash, alt_commodities, etc.) are mapped
into the existing 14-value enum at build time. Canonical and aliases
preserve the institutional granularity.

No schema change; data only. Idempotent:
- Inserted rows: ON CONFLICT (canonical, effective_from) DO UPDATE
  merges aliases on re-run.
- Updated rows: re-run recomputes the merged alias set and writes it
  back, reaching the same fixed point.

depends_on: 0167.
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0168_expand_canonical_map_fsds_q1_2025"
down_revision = "0167_primary_benchmark_backfill_log"
branch_labels = None
depends_on = None


_FIT_QUALITY = 0.92
_SOURCE_TAG = "fsds_q1_2025_slice_0168"


# Auto-generated from 2026-04-20-canonical-map-expansion-proposal.csv
# Total groups: 81
_GROUPS: list[tuple[str, list[str], str, str]] = [
    (
        'MSCI ACWI Index',
        [
            'MSCI ACWI',
            'MSCI ACWI IMI Index',
            'MSCI ACWI Index',
            'MSCI ACWI Total Return Index',
            'MSCI All Country World Index',
            'MSCI All Country World Index NR',
        ],
        'ACWI', 'equity_intl_dev',
    ),
    (
        'MSCI ACWI Ex U.S. Index',
        [
            'MSCI ACWI EX-U.S. Index',
            'MSCI ACWI Ex U.S. Index',
            'MSCI ACWI ex U.S. Index',
            'MSCI ACWI ex U.S. Index reflects no deduction for fees, expenses, or taxes',
            'MSCI ACWI ex-U.S. Index',
        ],
        'ACWX', 'equity_intl_dev',
    ),
    (
        'Bloomberg Aggregate Bond Index',
        [
            'BLOOMBERG U.S. AGGREGATE BOND Index',
            'BLOOMBERG U.S. AGGREGATE Index',
            'Bloomberg Aggregate Bond Index',
            'Bloomberg U.S. Aggregate BOND Index',
            'Bloomberg U.S. Aggregate Bond Index',
            'Bloomberg U.S. Aggregate Bond Index reflects no deduction for fees, expenses, or taxes',
            'Bloomberg U.S. Aggregate Bond Index reflects no deductions for fees, expenses or taxes',
            'Bloomberg U.S. Aggregate Bond Total Return Index',
            'Bloomberg U.S. Aggregate Index',
            'Bloomberg U.S. AggregateBond Index',
            'Bloomberg U.S. Aggregatebond Index',
            'ICE BofA U.S. Broad Market Index',
        ],
        'AGG', 'fi_us_agg',
    ),
    (
        'Lipper Balanced Funds Index',
        [
            'Lipper Balanced Funds Index',
        ],
        'AOR', 'other',
    ),
    (
        'ICE BofA U.S. Treasury Bill Index',
        [
            'Bloomberg 1-3 Month U.S. Treasury Bill Index',
            'ICE BOFA 3-MONTH U.S. TREASURY BILL Index',
            'ICE BOFA 3-month U.S. Treasury BILL Index',
            'ICE BofA 3 Month U.S. Treasury Bill Index',
            'ICE BofA 3-Month U.S. Treasury Bill Index',
            'ICE BofA 3-month U.S. Treasury Bill Index',
            'ICE BofA U.S. Treasury Bill Index',
            'ICE BofA U.S.3 Month Treasury Bill Index',
            'ICE BofA U.S.3-Month Treasury Bill Index',
            'ICE BofA U.S.3-Month Treasury Bill Total Return Index',
            'ICE BofA U.S.3-month Treasury Bill Index',
        ],
        'BIL', 'fi_us_treasury',
    ),
    (
        'Bloomberg U.S.1-5 Year Government/credit Index',
        [
            'Bloomberg U.S. Government/Credit 1-3 Year Index',
            'Bloomberg U.S. Government/credit 1-3 Year Index',
            'Bloomberg U.S.1-3 Year Government/Credit Bond Index',
            'Bloomberg U.S.1-3 Year Government/credit Bond Index',
            'Bloomberg U.S.1-5 Year Government/Credit Index',
            'Bloomberg U.S.1-5 Year Government/credit Index',
        ],
        'BIV', 'fi_us_treasury',
    ),
    (
        'S&P UBS Leveraged Loan Index',
        [
            'Morningstar LSTA U.S. Leveraged Loan 100 Index',
            'Morningstar LSTA U.S. Leveraged Loan Index',
            'S&P UBS Leveraged Loan Index',
            'S&P UBS Leveraged Loan Index reflects no deductions for fees, expenses or taxes',
        ],
        'BKLN', 'fi_us_hy',
    ),
    (
        'Bloomberg Global Aggregate Index',
        [
            'Bloomberg Global Aggregate Bond Index',
            'Bloomberg Global Aggregate Bond Index Reflects No Deduction For Fees Expenses Or Taxes',
            'Bloomberg Global Aggregate Index',
        ],
        'BNDX', 'fi_intl',
    ),
    (
        'FTSE World Government Bond Index',
        [
            'FTSE World Government Bond Index',
        ],
        'BWX', 'fi_intl',
    ),
    (
        'Bloomberg Commodity Index',
        [
            'Bloomberg Commodity Index',
        ],
        'DJP', 'commodities',
    ),
    (
        'Dow Jones U.S. Select Dividend Index',
        [
            'Dow Jones U.S. Select Dividend Index',
        ],
        'DVY', 'equity_us_large',
    ),
    (
        'MSCI Emerging Markets Index',
        [
            'MSCI Emerging Markets Index',
            'MSCI Emerging Markets Index reflects no deductions for fees, expenses or taxes',
            'MSCI Emerging Markets Index)',
            'MSCI Emerging Markets Index?',
            'MSCI Emerging Markets Total Return Index',
        ],
        'EEM', 'equity_em',
    ),
    (
        'MSCI EAFE Index',
        [
            'MSCI EAFE Index',
            'MSCI EAFE Index reflects no deduction for fees, expenses, or taxes, except foreign withholding taxes',
            'MSCI EAFE Index reflects no deductions for fees, expenses or taxes',
            'MSCI EAFE NR Index',
        ],
        'EFA', 'equity_intl_dev',
    ),
    (
        'MSCI EAFE Value Index',
        [
            'MSCI EAFE Value Index',
        ],
        'EFV', 'equity_intl_dev',
    ),
    (
        'JP Morgan EMBI Global Diversified Index',
        [
            'JP Morgan EMBI Global Diversified Index',
        ],
        'EMB', 'fi_intl',
    ),
    (
        'Russell 1000 Equal Weight Index',
        [
            'Russell 1000 Equal Weight Index',
        ],
        'EQAL', 'equity_us_large',
    ),
    (
        'MSCI Japan Index',
        [
            'MSCI Japan Index',
        ],
        'EWJ', 'equity_intl_dev',
    ),
    (
        'Bloomberg U.S. Treasury Index',
        [
            'Bloomberg U.S. Treasury Index',
        ],
        'GOVT', 'fi_us_treasury',
    ),
    (
        'Bloomberg Municipal High Yield Bond Index',
        [
            'Bloomberg Municipal High Yield Bond Index',
        ],
        'HYD', 'fi_us_muni',
    ),
    (
        'ICE BofA U.S. High Yield Index',
        [
            'Bloomberg U.S. Corporate High Yield Index',
            'ICE BofA U.S. Cash Pay High Yield Constrained Index',
            'ICE BofA U.S. High Yield Constrained Index',
            'ICE BofA U.S. High Yield Index',
            'ICE BofA U.S. High Yield Index reflects no deduction for fees, expenses, or taxes',
        ],
        'HYG', 'fi_us_hy',
    ),
    (
        'Bloomberg Intermediate U.S. Aggregate Bond Index',
        [
            'Bloomberg Intermediate U.S. Aggregate Bond Index',
        ],
        'IAGG', 'fi_us_agg',
    ),
    (
        'Bloomberg U.S. Intermediate Corporate Bond Index',
        [
            'Bloomberg U.S. Intermediate Corporate Bond Index',
        ],
        'IGIB', 'fi_us_ig',
    ),
    (
        'S&P MidCap 400 Value Index',
        [
            'S&P MidCap 400 Value Index',
        ],
        'IJJ', 'equity_us_mid',
    ),
    (
        'S&P MidCap 400 Growth Index',
        [
            'S&P MidCap 400 Growth Index',
        ],
        'IJK', 'equity_us_mid',
    ),
    (
        'S&P SmallCap 600 Index',
        [
            'S&P Small Cap 600 Index',
            'S&P SmallCap 600 Index',
            'S&P SmallCap 600 TR Index',
        ],
        'IJR', 'equity_us_small',
    ),
    (
        'S&P SmallCap 600 Value Index',
        [
            'S&P SmallCap 600 Value Index',
        ],
        'IJS', 'equity_us_small',
    ),
    (
        'S&P SmallCap 600 Growth Index',
        [
            'S&P SmallCap 600 Growth Index',
        ],
        'IJT', 'equity_us_small',
    ),
    (
        'S&P 1500 Index',
        [
            'S&P 1500 Index',
            'S&P 1500 Index -',
            'S&P 1500 Index-',
            'S&P COMPOSITE 1500 Index',
            'S&P Composite 1500 Index',
            'S&P Composite 1500 Total Return Index',
        ],
        'ITOT', 'equity_us_large',
    ),
    (
        'S&P 500 Value Index',
        [
            'S&P 500 Value Index',
        ],
        'IVE', 'equity_us_large',
    ),
    (
        'S&P 500 Growth Index',
        [
            'S&P 500 Growth Index',
        ],
        'IVW', 'equity_us_large',
    ),
    (
        'Russell 1000 Index',
        [
            'RUSSELL 1000 Index',
            'Russell 1000 Index',
            'Russell 1000 Index reflects no deduction for fees, expenses, or taxes',
            'Russell 1000 Index reflects no deductions for fees, expenses or taxes',
        ],
        'IWB', 'equity_us_large',
    ),
    (
        'Russell 1000 Value Index',
        [
            'RUSSELL 1000 VALUE Index',
            'Russell 1000 Value Index',
            'Russell 1000 Value Index reflects no deduction for fees, expenses or taxes',
            'Russell 1000 Value Index reflects no deduction for fees, expenses, or taxes',
            'Russell 1000 Value Index reflects no deductions for fees, expenses or taxes',
        ],
        'IWD', 'equity_us_large',
    ),
    (
        'Russell 1000 Growth Index',
        [
            'RUSSELL 1000 GROWTH Index',
            'Russell 1000 Growth Index',
            'Russell 1000 Growth Index reflects no deduction for fees, expenses, or taxes',
            'Russell 1000 Growth Total Return Index',
        ],
        'IWF', 'equity_us_large',
    ),
    (
        'S&P 1000 Index',
        [
            'Bloomberg U.S.2000 Index',
            'RUSSELL 2000 Index',
            'RUSSELL 2500 Index',
            'Russell 2000 Index',
            'Russell 2000 Index reflects no deductions for fees, expenses or taxes',
            'Russell 2000 Total Return Index',
            'Russell 2500 Index',
            'Russell 2500 Total Return Index',
            'S&P 1000 Index',
        ],
        'IWM', 'equity_us_small',
    ),
    (
        'Russell 2000 Value Index',
        [
            'RUSSELL 2000 VALUE Index',
            'Russell 2000 Value Index',
            'Russell 2000 Value Index reflects no deduction for fees, expenses or taxes',
            'Russell 2000 Value Index reflects no deductions for fees, expenses or taxes',
        ],
        'IWN', 'equity_us_small',
    ),
    (
        'Russell 2000 Growth Index',
        [
            'RUSSELL 2000 GROWTH Index',
            'Russell 2000 Growth Index',
            'Russell 2000 Growth Total Return Index',
        ],
        'IWO', 'equity_us_small',
    ),
    (
        'Russell MidCap Growth Index',
        [
            'RUSSELL MIDCAP GROWTH Index',
            'Russell MidCap Growth Index',
            'Russell Midcap Growth Index',
            'Russell Midcap Growth Index reflects no deduction for fees, expenses, or taxes',
            'Russell Midcap Growth Total Return Index',
        ],
        'IWP', 'equity_us_mid',
    ),
    (
        'Russell MidCap Index',
        [
            'RUSSELL MIDCAP Index',
            'Russell Mid Cap Index',
            'Russell Mid Cap Total Return Index',
            'Russell MidCap Index',
            'Russell Midcap Index',
            'Russell Midcap Index reflects no deduction for fees, expenses or taxes',
            'Russell Midcap Index reflects no deductions for fees, expenses or taxes',
        ],
        'IWR', 'equity_us_mid',
    ),
    (
        'Russell MidCap Value Index',
        [
            'RUSSELL MIDCAP VALUE Index',
            'Russell MidCap Value Index',
            'Russell Midcap Value Index',
            'Russell Midcap Value Index reflects no deduction for fees, expenses or taxes',
            'Russell Midcap Value Index reflects no deductions for fees, expenses or taxes',
        ],
        'IWS', 'equity_us_mid',
    ),
    (
        'Russell 3000 Index',
        [
            'RUSSELL 3000 Index',
            'Russell 3000 Index',
            'Russell 3000 Index reflects no deduction for fees, expenses, or taxes',
            'Russell 3000 Index reflects no deductions for fees, expenses or taxes',
            'Russell 3000 Index?',
        ],
        'IWV', 'equity_us_large',
    ),
    (
        'Russell 3000 Value Index',
        [
            'RUSSELL 3000 VALUE Index',
            'Russell 3000 Value Index',
            'Russell 3000 Value Total Return Index',
        ],
        'IWW', 'equity_us_large',
    ),
    (
        'Russell 3000 Growth Index',
        [
            'RUSSELL 3000 GROWTH Index',
            'Russell 3000 Growth Index',
            'Russell 3000 Growth Total Return Index',
        ],
        'IWZ', 'equity_us_large',
    ),
    (
        'JP Morgan CLOIE AAA Index',
        [
            'JP Morgan CLOIE AAA Index',
            'JP Morgan CLOIE AAA Total Return Index',
        ],
        'JAAA', 'fi_us_ig',
    ),
    (
        'S&P Banks Select Industry Index',
        [
            'S&P Banks Select Industry Index',
        ],
        'KBE', 'other',
    ),
    (
        'Bloomberg U.S. Credit Index',
        [
            'Bloomberg U.S. Corporate Bond Index',
            'Bloomberg U.S. Corporate Bond Index reflects no deduction for fees, expenses, or taxes',
            'Bloomberg U.S. Corporate Index',
            'Bloomberg U.S. Credit Index',
        ],
        'LQD', 'fi_us_ig',
    ),
    (
        'Bloomberg U.S. MBS Index',
        [
            'Bloomberg U.S. MBS Index',
        ],
        'MBB', 'fi_us_agg',
    ),
    (
        'S&P MidCap 400 Index',
        [
            'S&P MidCap 400 Index',
        ],
        'MDY', 'equity_us_mid',
    ),
    (
        'S&P Municipal Bond Index',
        [
            'Bloomberg 3 15 Year Blend Municipal Bond Index',
            'Bloomberg 3-15 Year Blend Municipal Bond Index',
            'Bloomberg Minnesota Municipal Bond Index',
            'Bloomberg Municipal Bond Index',
            'Bloomberg Municipal Bond Index reflects no deduction for fees, expenses, or taxes',
            'Bloomberg Pennsylvania Municipal Bond Index',
            'Bloomberg U.S. Municipal Bond Index',
            'Bloomberg U.S. Municipal Bond Index*',
            'S&P Municipal Bond Index',
            'S&P Municipal Bond Index reflects no deductions for fees, expenses or taxes',
            'S&P Municipal Bond Index*',
            'S&P Municipal Bond Index* reflects no deductions for fees, expenses or taxes',
            'S&P National AMT-Free Municipal Bond Index',
            'S&P National Amt-free Municipal Bond Index',
        ],
        'MUB', 'fi_us_muni',
    ),
    (
        'Nasdaq Composite Index',
        [
            'NASDAQ Composite Index',
            'NASDAQ Composite Total Return Index',
            'Nasdaq Composite Index',
        ],
        'ONEQ', 'equity_us_large',
    ),
    (
        'ICE BOFA U.S. ALL Capital Securities Index',
        [
            'ICE BOFA U.S. ALL CAPITAL SECURITIES Index',
            'ICE BOFA U.S. ALL Capital Securities Index',
            'ICE BofA U.S. All Capital Securities Index',
        ],
        'PFF', 'fi_us_ig',
    ),
    (
        'Nasdaq-100 Index',
        [
            'NASDAQ - 100 Total Return Index',
            'NASDAQ 100 Total Return Index',
            'NASDAQ-100 Index',
            'NASDAQ-100 Total Return Index',
            'Nasdaq 100 Index',
            'Nasdaq 100 Total Return Index',
            'Nasdaq-100 Index',
        ],
        'QQQ', 'equity_us_large',
    ),
    (
        'S&P 500 Equal Weight Index',
        [
            'S&P 500 Equal Weight Index',
            'S&P 500 Equal Weight Total Return Index',
        ],
        'RSP', 'equity_us_large',
    ),
    (
        'Dow Jones U.S. Total Stock Market Float Adjusted Index',
        [
            'Dow Jones U.S. Total Stock Market Float Adjusted Index',
        ],
        'SCHB', 'equity_us_large',
    ),
    (
        'ICE BofA 1 3 Year U.S. Treasury Index',
        [
            'ICE BofA 1 3 Year U.S. Treasury Index',
            'ICE BofA 1-3 Year U.S. Treasury Index',
        ],
        'SHY', 'fi_us_treasury',
    ),
    (
        'Russell 2500 Growth Index',
        [
            'Russell 2500 Growth Index',
        ],
        'SMLG', 'equity_us_small',
    ),
    (
        'Russell 2500 Value Index',
        [
            'Russell 2500 Value Index',
            'Russell 2500 Value Total Return Index',
        ],
        'SMLV', 'equity_us_small',
    ),
    (
        'S&P Total Market Index',
        [
            'S&P Total Market Index',
        ],
        'SPTM', 'equity_us_large',
    ),
    (
        'S&P 500 index',
        [
            'S&P 500 Index',
            'S&P 500 Index reflects no deduction for fees, expenses or taxes',
            'S&P 500 Index reflects no deduction for fees, expenses, or taxes',
            'S&P 500 Index reflects no deductions for fees, expenses or taxes',
            'S&P 500 Index)',
            'S&P 500 index',
        ],
        'SPY', 'equity_us_large',
    ),
    (
        'Bloomberg 1 Year Municipal Bond Index',
        [
            'Bloomberg 1 Year Municipal Bond Index',
            'Bloomberg 1-Year Municipal Bond Index',
            'Bloomberg 1-year Municipal Bond Index',
        ],
        'SUB', 'fi_us_muni',
    ),
    (
        'Bloomberg U.S. Government Inflation-linked Bond Index',
        [
            'Bloomberg U.S. Government Inflation-Linked Bond Index',
            'Bloomberg U.S. Government Inflation-linked Bond Index',
        ],
        'TIP', 'fi_us_treasury',
    ),
    (
        'Bloomberg U.S. Universal Index',
        [
            'Bloomberg U.S. Universal Bond Index',
            'Bloomberg U.S. Universal Index',
            'Bloomberg U.S. Universal Index reflects no deductions for fees, expenses or taxes',
            'Bloomberg U.S. Universal Total Return Index',
        ],
        'UBND', 'fi_us_agg',
    ),
    (
        'MSCI World Index',
        [
            'MSCI WORLD Index',
            'MSCI World Index',
            'MSCI World Index -',
            'MSCI World Index)',
            'MSCI World Index-',
            'MSCI World NR Index reflects no deduction for fees, expenses, or taxes, except foreign withholding taxes',
        ],
        'URTH', 'equity_intl_dev',
    ),
    (
        'Bloomberg High Yield Very Liquid Index',
        [
            'Bloomberg High Yield Very Liquid Index',
        ],
        'USHY', 'fi_us_hy',
    ),
    (
        'MSCI U.S. Minimum Volatility Index',
        [
            'MSCI U.S. Minimum Volatility Index',
        ],
        'USMV', 'equity_us_large',
    ),
    (
        'MSCI World Ex U.S. Index',
        [
            'MSCI World Ex U.S. Index',
            'MSCI World ex U.S. Index',
            'MSCI World ex-U.S. Index',
        ],
        'VEA', 'equity_intl_dev',
    ),
    (
        'S&P Target Date To 2055 Index',
        [
            'S&P Target Date To 2055 Index',
        ],
        'VFFVX', 'other',
    ),
    (
        'S&P Target Date To 2050 Index',
        [
            'S&P Target Date To 2050 Index',
        ],
        'VFIFX', 'other',
    ),
    (
        'S&P Target Date To 2040 Index',
        [
            'S&P Target Date To 2040 Index',
        ],
        'VFORX', 'other',
    ),
    (
        'MSCI Europe Index',
        [
            'MSCI Europe Index',
        ],
        'VGK', 'equity_intl_dev',
    ),
    (
        'S&P Target Date To 2030 Index',
        [
            'S&P Target Date To 2030 Index',
        ],
        'VTHRX', 'other',
    ),
    (
        'MSCI U.S. Index',
        [
            'CRSP U.S. Total Market Index',
            'MSCI U.S. Index',
        ],
        'VTI', 'equity_us_large',
    ),
    (
        'S&P Target Date To 2045 Index',
        [
            'S&P Target Date To 2045 Index',
        ],
        'VTIVX', 'other',
    ),
    (
        'S&P Target Date To 2035 Index',
        [
            'S&P Target Date To 2035 Index',
        ],
        'VTTHX', 'other',
    ),
    (
        'S&P Target Date To 2060 Index',
        [
            'S&P Target Date To 2060 Index',
        ],
        'VTTSX', 'other',
    ),
    (
        'MSCI ACWI Ex U.S. Investable Market Index',
        [
            'MSCI ACWI Ex U.S. Investable Market Index',
            'MSCI ACWI ex U.S. Investable Market Index',
        ],
        'VXUS', 'equity_intl_dev',
    ),
    (
        'S&P Biotechnology Select Industry Index',
        [
            'S&P Biotechnology Select Industry Index',
        ],
        'XBI', 'other',
    ),
    (
        'S&P Oil & Gas Equipment & Services Select Industry Index',
        [
            'S&P Oil & Gas Equipment & Services Select Industry Index',
        ],
        'XES', 'other',
    ),
    (
        'S&P 500 Financials Index',
        [
            'S&P 500 Financials Index',
        ],
        'XLF', 'other',
    ),
    (
        'S&P 500 Information Technology Index',
        [
            'S&P 500 Information Technology Index',
        ],
        'XLK', 'other',
    ),
    (
        'S&P 500 Utilities Index',
        [
            'S&P 500 Utilities Index',
        ],
        'XLU', 'other',
    ),
    (
        'S&P Pharmaceuticals Select Industry Index',
        [
            'S&P Pharmaceuticals Select Industry Index',
        ],
        'XPH', 'other',
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    lookup_sql = text("""
        SELECT id, benchmark_name_aliases
          FROM benchmark_etf_canonical_map
         WHERE proxy_etf_ticker = :ticker
           AND asset_class = CAST(:asset_class AS benchmark_asset_class)
           AND effective_to = '9999-12-31'
         LIMIT 1
    """)

    update_sql = text("""
        UPDATE benchmark_etf_canonical_map
           SET benchmark_name_aliases = :aliases,
               updated_at             = now()
         WHERE id = :id
    """)

    insert_sql = text("""
        INSERT INTO benchmark_etf_canonical_map (
            benchmark_name_canonical, benchmark_name_aliases,
            proxy_etf_ticker, asset_class, source, fit_quality_score
        ) VALUES (
            :canonical, :aliases, :ticker,
            CAST(:asset_class AS benchmark_asset_class),
            :source, :fit
        )
        ON CONFLICT (benchmark_name_canonical, effective_from) DO UPDATE
            SET benchmark_name_aliases = (
                    SELECT ARRAY(
                        SELECT DISTINCT unnest(
                            benchmark_etf_canonical_map.benchmark_name_aliases
                            || EXCLUDED.benchmark_name_aliases
                        )
                        ORDER BY 1
                    )
                ),
                proxy_etf_ticker = EXCLUDED.proxy_etf_ticker,
                asset_class     = EXCLUDED.asset_class,
                updated_at      = now()
    """)

    inserted = 0
    merged = 0
    for canonical, aliases, ticker, asset_class in _GROUPS:
        existing = bind.execute(
            lookup_sql, {"ticker": ticker, "asset_class": asset_class}
        ).mappings().first()
        if existing is not None:
            current = list(existing["benchmark_name_aliases"] or [])
            combined = sorted({*current, *aliases, canonical})
            bind.execute(
                update_sql, {"aliases": combined, "id": existing["id"]}
            )
            merged += 1
        else:
            bind.execute(
                insert_sql,
                {
                    "canonical": canonical,
                    "aliases": sorted(set(aliases) | {canonical}),
                    "ticker": ticker,
                    "asset_class": asset_class,
                    "source": _SOURCE_TAG,
                    "fit": _FIT_QUALITY,
                },
            )
            inserted += 1

    # Best-effort visibility in alembic logs.
    print(
        f"[0168] benchmark_etf_canonical_map: "
        f"merged_into_existing={merged} inserted_new={inserted} "
        f"total_groups={len(_GROUPS)}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Delete rows created by this migration. Merges into pre-existing
    # rows cannot be reversed deterministically; callers that need a
    # true revert should restore from a dump. Log the caveat.
    r = bind.execute(
        text(
            "DELETE FROM benchmark_etf_canonical_map "
            "WHERE source = :source RETURNING id"
        ),
        {"source": _SOURCE_TAG},
    )
    deleted = len(r.fetchall())
    print(
        f"[0168] downgrade removed {deleted} inserted rows; alias merges "
        f"on pre-existing rows were not reverted."
    )
