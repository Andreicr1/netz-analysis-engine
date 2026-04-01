"""Bulk load RR1 (Risk/Return Summary) data from DERA TSV.

Ingests annual returns (bar chart), fees, and risk stats per mutual fund series/class.
Uses psycopg3 COPY for maximum throughput.

Usage:
    cd backend
    python scripts/bulk_load_rr1.py --parent "C:/Users/Andrei/Desktop/EDGAR FILES/RR1"
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time

csv.field_size_limit(10_000_000)  # Some RR1 fields are huge (HTML blobs)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def get_connection_string() -> str:
    from app.core.config.settings import settings
    url = str(settings.database_url)
    return url.replace("postgresql+asyncpg://", "postgresql://")


# Tags we extract from num.tsv
ANNUAL_RETURN_TAG = "AnnlRtrPct"

STAT_TAGS = {
    "ManagementFeesOverAssets": "management_fee_pct",
    "ExpensesOverAssets": "expense_ratio_pct",
    "NetExpensesOverAssets": "net_expense_ratio_pct",
    "FeeWaiverOrReimbursementOverAssets": "fee_waiver_pct",
    "DistributionAndService12b1FeesOverAssets": "distribution_12b1_pct",
    "AcquiredFundFeesAndExpensesOverAssets": "acquired_fund_fees_pct",
    "OtherExpensesOverAssets": "other_expenses_pct",
    "PortfolioTurnoverRate": "portfolio_turnover_pct",
    "ExpenseExampleYear01": "expense_example_1y",
    "ExpenseExampleYear03": "expense_example_3y",
    "ExpenseExampleYear05": "expense_example_5y",
    "ExpenseExampleYear10": "expense_example_10y",
    "BarChartHighestQuarterlyReturn": "bar_chart_best_qtr_pct",
    "BarChartLowestQuarterlyReturn": "bar_chart_worst_qtr_pct",
    "BarChartYearToDateReturn": "bar_chart_ytd_pct",
    "AvgAnnlRtrPct": None,  # special handling — needs measure dimension
    "AverageAnnualTotalReturns1YearPercent": "avg_annual_return_1y",
    "AverageAnnualTotalReturns5YearsPercent": "avg_annual_return_5y",
    "AverageAnnualTotalReturns10YearsPercent": "avg_annual_return_10y",
}

# AvgAnnlRtrPct uses 'measure' to distinguish 1Y/5Y/10Y/SinceInception
AVG_MEASURE_MAP = {
    "1": "avg_annual_return_1y",
    "5": "avg_annual_return_5y",
    "10": "avg_annual_return_10y",
}


def parse_rr1_quarter(rr1_dir: str) -> tuple[list[dict], list[dict]]:
    """Parse a single RR1 quarter directory.

    Returns (annual_returns, stats_rows).
    """
    num_path = os.path.join(rr1_dir, "num.tsv")
    sub_path = os.path.join(rr1_dir, "sub.tsv")

    if not os.path.exists(num_path):
        return [], []

    # Build accession → filing_date from sub.tsv
    filing_dates: dict[str, str] = {}
    if os.path.exists(sub_path):
        with open(sub_path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                filed = r.get("filed", "").strip()
                if filed and len(filed) == 8:
                    # Convert YYYYMMDD → YYYY-MM-DD
                    filing_dates[r["adsh"]] = f"{filed[:4]}-{filed[4:6]}-{filed[6:8]}"
                elif filed and len(filed) == 10:
                    filing_dates[r["adsh"]] = filed

    # Parse num.tsv
    annual_returns: list[dict] = []
    stats_accum: dict[tuple[str, str], dict] = {}  # (series_id, class_id) → stats

    with open(num_path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            tag = r["tag"]
            series_id = r.get("series", "").strip()
            class_id = r.get("class", "").strip()
            value_str = r.get("value", "").strip()
            ddate = r.get("ddate", "")
            adsh = r.get("adsh", "")
            measure = r.get("measure", "").strip()

            if not value_str:
                continue

            try:
                value = float(value_str)
            except (ValueError, TypeError):
                continue

            filing_date = filing_dates.get(adsh)

            # Annual returns (bar chart)
            if tag == ANNUAL_RETURN_TAG and series_id and ddate:
                year = int(ddate[:4])
                annual_returns.append({
                    "series_id": series_id,
                    "year": year,
                    "annual_return_pct": round(value, 6),
                    "filing_date": filing_date,
                })
                continue

            # Stats tags
            if tag in STAT_TAGS:
                key = (series_id or "_none", class_id or "")
                if key not in stats_accum:
                    stats_accum[key] = {
                        "series_id": series_id or None,
                        "class_id": class_id or "",
                        "filing_date": filing_date,
                    }

                col = STAT_TAGS[tag]
                if col is not None:
                    stats_accum[key][col] = round(value, 6)
                elif tag == "AvgAnnlRtrPct" and measure:
                    # Parse measure for period: look for year number
                    for period, col_name in AVG_MEASURE_MAP.items():
                        if f"{period}Y" in measure or f"{period} Y" in measure or measure.startswith(period):
                            stats_accum[key][col_name] = round(value, 6)
                            break

    # Filter stats: only rows with series_id and at least one data field
    data_cols = set(STAT_TAGS.values()) - {None}
    stats_rows = [
        row for row in stats_accum.values()
        if row.get("series_id") and any(row.get(c) is not None for c in data_cols)
    ]

    return annual_returns, stats_rows


def upsert_quarter(conn, annual_returns: list[dict], stats_rows: list[dict]) -> tuple[int, int]:
    """Upsert annual returns and stats via COPY + INSERT ON CONFLICT."""
    ret_count = 0
    stats_count = 0

    with conn.cursor() as cur:
        # ── Annual returns ────────────────────────────────────
        if annual_returns:
            cur.execute("DROP TABLE IF EXISTS _rr1_returns")
            cur.execute("""
                CREATE TEMP TABLE _rr1_returns (
                    series_id TEXT, year TEXT, annual_return_pct TEXT, filing_date TEXT
                )
            """)

            buf = io.StringIO()
            for r in annual_returns:
                fd = r["filing_date"] or ""
                buf.write(f"{r['series_id']}\t{r['year']}\t{r['annual_return_pct']}\t{fd}\n")
            buf.seek(0)

            with cur.copy("COPY _rr1_returns FROM STDIN") as copy:
                copy.write(buf.getvalue().encode("utf-8"))

            cur.execute("""
                INSERT INTO sec_fund_prospectus_returns (series_id, year, annual_return_pct, filing_date)
                SELECT DISTINCT ON (series_id, year::smallint)
                    series_id,
                    year::smallint,
                    annual_return_pct::numeric,
                    CASE WHEN filing_date IS NOT NULL AND length(filing_date) = 10
                         THEN filing_date::date ELSE NULL END
                FROM _rr1_returns
                WHERE series_id != '' AND year::int > 2000
                ORDER BY series_id, year::smallint, filing_date DESC NULLS LAST
                ON CONFLICT (series_id, year) DO UPDATE SET
                    annual_return_pct = EXCLUDED.annual_return_pct,
                    filing_date = COALESCE(EXCLUDED.filing_date, sec_fund_prospectus_returns.filing_date)
            """)
            ret_count = cur.rowcount

        # ── Stats ─────────────────────────────────────────────
        if stats_rows:
            stat_cols = [
                "series_id", "class_id", "filing_date",
                "management_fee_pct", "expense_ratio_pct", "net_expense_ratio_pct",
                "fee_waiver_pct", "distribution_12b1_pct", "acquired_fund_fees_pct",
                "other_expenses_pct", "portfolio_turnover_pct",
                "expense_example_1y", "expense_example_3y", "expense_example_5y", "expense_example_10y",
                "bar_chart_best_qtr_pct", "bar_chart_worst_qtr_pct", "bar_chart_ytd_pct",
                "avg_annual_return_1y", "avg_annual_return_5y", "avg_annual_return_10y",
            ]

            cur.execute("DROP TABLE IF EXISTS _rr1_stats")
            cur.execute(f"""
                CREATE TEMP TABLE _rr1_stats (
                    {', '.join(f'{c} TEXT' for c in stat_cols)}
                )
            """)

            buf = io.StringIO()
            for row in stats_rows:
                vals = []
                for c in stat_cols:
                    v = row.get(c)
                    vals.append(str(v) if v is not None else "")
                buf.write("\t".join(vals) + "\n")
            buf.seek(0)

            with cur.copy("COPY _rr1_stats FROM STDIN") as copy:
                copy.write(buf.getvalue().encode("utf-8"))

            def _safe_num(col: str, precision: int = 8) -> str:
                """Generate a safe numeric cast that clamps overflow to NULL."""
                limit = 10 ** precision
                return (
                    f"CASE WHEN NULLIF({col}, '') IS NOT NULL "
                    f"AND ABS(NULLIF({col}, '')::numeric) < {limit} "
                    f"THEN NULLIF({col}, '')::numeric ELSE NULL END"
                )

            cur.execute(f"""
                INSERT INTO sec_fund_prospectus_stats
                    ({', '.join(stat_cols)})
                SELECT DISTINCT ON (series_id, class_id)
                    series_id,
                    class_id,
                    CASE WHEN filing_date ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$' THEN filing_date::date ELSE NULL END,
                    {_safe_num('management_fee_pct', 2)},
                    {_safe_num('expense_ratio_pct', 2)},
                    {_safe_num('net_expense_ratio_pct', 2)},
                    {_safe_num('fee_waiver_pct', 2)},
                    {_safe_num('distribution_12b1_pct', 2)},
                    {_safe_num('acquired_fund_fees_pct', 2)},
                    {_safe_num('other_expenses_pct', 2)},
                    {_safe_num('portfolio_turnover_pct', 4)},
                    {_safe_num('expense_example_1y', 8)},
                    {_safe_num('expense_example_3y', 8)},
                    {_safe_num('expense_example_5y', 8)},
                    {_safe_num('expense_example_10y', 8)},
                    {_safe_num('bar_chart_best_qtr_pct', 4)},
                    {_safe_num('bar_chart_worst_qtr_pct', 4)},
                    {_safe_num('bar_chart_ytd_pct', 4)},
                    {_safe_num('avg_annual_return_1y', 4)},
                    {_safe_num('avg_annual_return_5y', 4)},
                    {_safe_num('avg_annual_return_10y', 4)}
                FROM _rr1_stats
                WHERE series_id != '' AND series_id IS NOT NULL
                ORDER BY series_id, class_id, filing_date DESC NULLS LAST
                ON CONFLICT (series_id, class_id) DO UPDATE SET
                    filing_date = COALESCE(EXCLUDED.filing_date, sec_fund_prospectus_stats.filing_date),
                    management_fee_pct = COALESCE(EXCLUDED.management_fee_pct, sec_fund_prospectus_stats.management_fee_pct),
                    expense_ratio_pct = COALESCE(EXCLUDED.expense_ratio_pct, sec_fund_prospectus_stats.expense_ratio_pct),
                    net_expense_ratio_pct = COALESCE(EXCLUDED.net_expense_ratio_pct, sec_fund_prospectus_stats.net_expense_ratio_pct),
                    fee_waiver_pct = COALESCE(EXCLUDED.fee_waiver_pct, sec_fund_prospectus_stats.fee_waiver_pct),
                    distribution_12b1_pct = COALESCE(EXCLUDED.distribution_12b1_pct, sec_fund_prospectus_stats.distribution_12b1_pct),
                    acquired_fund_fees_pct = COALESCE(EXCLUDED.acquired_fund_fees_pct, sec_fund_prospectus_stats.acquired_fund_fees_pct),
                    other_expenses_pct = COALESCE(EXCLUDED.other_expenses_pct, sec_fund_prospectus_stats.other_expenses_pct),
                    portfolio_turnover_pct = COALESCE(EXCLUDED.portfolio_turnover_pct, sec_fund_prospectus_stats.portfolio_turnover_pct),
                    expense_example_1y = COALESCE(EXCLUDED.expense_example_1y, sec_fund_prospectus_stats.expense_example_1y),
                    expense_example_3y = COALESCE(EXCLUDED.expense_example_3y, sec_fund_prospectus_stats.expense_example_3y),
                    expense_example_5y = COALESCE(EXCLUDED.expense_example_5y, sec_fund_prospectus_stats.expense_example_5y),
                    expense_example_10y = COALESCE(EXCLUDED.expense_example_10y, sec_fund_prospectus_stats.expense_example_10y),
                    bar_chart_best_qtr_pct = COALESCE(EXCLUDED.bar_chart_best_qtr_pct, sec_fund_prospectus_stats.bar_chart_best_qtr_pct),
                    bar_chart_worst_qtr_pct = COALESCE(EXCLUDED.bar_chart_worst_qtr_pct, sec_fund_prospectus_stats.bar_chart_worst_qtr_pct),
                    bar_chart_ytd_pct = COALESCE(EXCLUDED.bar_chart_ytd_pct, sec_fund_prospectus_stats.bar_chart_ytd_pct),
                    avg_annual_return_1y = COALESCE(EXCLUDED.avg_annual_return_1y, sec_fund_prospectus_stats.avg_annual_return_1y),
                    avg_annual_return_5y = COALESCE(EXCLUDED.avg_annual_return_5y, sec_fund_prospectus_stats.avg_annual_return_5y),
                    avg_annual_return_10y = COALESCE(EXCLUDED.avg_annual_return_10y, sec_fund_prospectus_stats.avg_annual_return_10y)
            """)
            stats_count = cur.rowcount

    conn.commit()
    return ret_count, stats_count


def main():
    parser = argparse.ArgumentParser(description="Bulk load RR1 data via psycopg3 COPY")
    parser.add_argument("--parent", required=True, help="Parent dir with quarter subdirs")
    args = parser.parse_args()

    import psycopg

    # Discover quarters
    quarter_dirs = sorted(
        os.path.join(args.parent, d)
        for d in os.listdir(args.parent)
        if os.path.isdir(os.path.join(args.parent, d)) and "rr1" in d.lower()
    )

    print(f"{'=' * 60}")
    print("  RR1 Risk/Return Bulk Loader (psycopg3 COPY)")
    print(f"  Quarters: {len(quarter_dirs)}")
    print(f"{'=' * 60}")

    connstr = get_connection_string()
    grand_returns = 0
    grand_stats = 0
    t_start = time.monotonic()

    with psycopg.connect(connstr) as conn:
        for qi, qdir in enumerate(quarter_dirs, 1):
            qname = os.path.basename(qdir)
            t0 = time.monotonic()

            try:
                annual_returns, stats_rows = parse_rr1_quarter(qdir)
                if not annual_returns and not stats_rows:
                    print(f"[{qi}/{len(quarter_dirs)}] {qname}: SKIP (no data)")
                    continue

                ret_ct, stat_ct = upsert_quarter(conn, annual_returns, stats_rows)
                elapsed = time.monotonic() - t0
                grand_returns += ret_ct
                grand_stats += stat_ct
                print(f"[{qi}/{len(quarter_dirs)}] {qname}: "
                      f"{ret_ct:,} returns + {stat_ct:,} stats in {elapsed:.1f}s")
            except Exception as e:
                conn.rollback()
                print(f"[{qi}/{len(quarter_dirs)}] {qname}: FAILED — {str(e)[:200]}")

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {len(quarter_dirs)} quarters")
    print(f"  Returns: {grand_returns:,} | Stats: {grand_stats:,}")
    print(f"  Time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
