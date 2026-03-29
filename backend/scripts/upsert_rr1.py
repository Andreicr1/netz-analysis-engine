"""Upsert RR1 CSVs (returns + stats) into DB via psycopg3 COPY.

Usage:
    cd backend
    python scripts/upsert_rr1.py --dir "C:/Users/Andrei/Desktop/EDGAR FILES/rr1_parsed"
"""

from __future__ import annotations

import argparse
import os
import sys
import time

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def get_connection_string() -> str:
    from app.core.config.settings import settings
    url = str(settings.database_url)
    return url.replace("postgresql+asyncpg://", "postgresql://")


def upsert_returns(conn, csv_path: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _rr1_ret_staging")
        cur.execute("""
            CREATE TEMP TABLE _rr1_ret_staging (
                series_id TEXT, year TEXT, annual_return_pct TEXT, filing_date TEXT
            )
        """)

        with open(csv_path, encoding="utf-8") as f:
            next(f)  # skip header
            with cur.copy("COPY _rr1_ret_staging FROM STDIN WITH (FORMAT csv)") as copy:
                for line in f:
                    copy.write(line.encode("utf-8"))

        cur.execute("SELECT COUNT(*) FROM _rr1_ret_staging")
        staged = cur.fetchone()[0]
        print(f"  Returns staged: {staged:,}")

        cur.execute("""
            INSERT INTO sec_fund_prospectus_returns (series_id, year, annual_return_pct, filing_date)
            SELECT
                series_id,
                year::smallint,
                annual_return_pct::numeric,
                CASE WHEN length(filing_date) >= 10 THEN filing_date::date ELSE NULL END
            FROM _rr1_ret_staging
            WHERE series_id != '' AND year != ''
            ON CONFLICT (series_id, year) DO UPDATE SET
                annual_return_pct = EXCLUDED.annual_return_pct,
                filing_date = COALESCE(EXCLUDED.filing_date, sec_fund_prospectus_returns.filing_date)
        """)
        count = cur.rowcount
    conn.commit()
    return count


def upsert_stats(conn, csv_path: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _rr1_stats_staging")

        cols = [
            "series_id", "class_id", "filing_date",
            "management_fee_pct", "expense_ratio_pct", "net_expense_ratio_pct",
            "fee_waiver_pct", "distribution_12b1_pct", "acquired_fund_fees_pct",
            "other_expenses_pct", "portfolio_turnover_pct",
            "expense_example_1y", "expense_example_3y", "expense_example_5y", "expense_example_10y",
            "bar_chart_best_qtr_pct", "bar_chart_worst_qtr_pct", "bar_chart_ytd_pct",
            "avg_annual_return_1y", "avg_annual_return_5y", "avg_annual_return_10y",
        ]

        cur.execute(f"""
            CREATE TEMP TABLE _rr1_stats_staging (
                {', '.join(f'{c} TEXT' for c in cols)}
            )
        """)

        with open(csv_path, encoding="utf-8") as f:
            next(f)  # skip header
            with cur.copy("COPY _rr1_stats_staging FROM STDIN WITH (FORMAT csv)") as copy:
                for line in f:
                    copy.write(line.encode("utf-8"))

        cur.execute("SELECT COUNT(*) FROM _rr1_stats_staging")
        staged = cur.fetchone()[0]
        print(f"  Stats staged: {staged:,}")

        def _safe(col: str) -> str:
            return f"NULLIF({col}, '')::numeric"

        def _date(col: str) -> str:
            return f"CASE WHEN length({col}) >= 10 THEN {col}::date ELSE NULL END"

        cur.execute(f"""
            INSERT INTO sec_fund_prospectus_stats
                ({', '.join(cols)})
            SELECT
                series_id,
                COALESCE(NULLIF(class_id, ''), ''),
                {_date('filing_date')},
                {_safe('management_fee_pct')},
                {_safe('expense_ratio_pct')},
                {_safe('net_expense_ratio_pct')},
                {_safe('fee_waiver_pct')},
                {_safe('distribution_12b1_pct')},
                {_safe('acquired_fund_fees_pct')},
                {_safe('other_expenses_pct')},
                {_safe('portfolio_turnover_pct')},
                {_safe('expense_example_1y')},
                {_safe('expense_example_3y')},
                {_safe('expense_example_5y')},
                {_safe('expense_example_10y')},
                {_safe('bar_chart_best_qtr_pct')},
                {_safe('bar_chart_worst_qtr_pct')},
                {_safe('bar_chart_ytd_pct')},
                {_safe('avg_annual_return_1y')},
                {_safe('avg_annual_return_5y')},
                {_safe('avg_annual_return_10y')}
            FROM _rr1_stats_staging
            WHERE series_id != '' AND series_id IS NOT NULL
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
        count = cur.rowcount
    conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="Upsert RR1 CSVs via psycopg3")
    parser.add_argument("--dir", required=True, help="Dir with returns.csv + stats.csv")
    args = parser.parse_args()

    import psycopg

    ret_path = os.path.join(args.dir, "returns.csv")
    stats_path = os.path.join(args.dir, "stats.csv")

    print(f"{'=' * 60}")
    print(f"  RR1 Upserter (psycopg3 COPY)")
    print(f"{'=' * 60}")

    connstr = get_connection_string()
    t_start = time.monotonic()

    with psycopg.connect(connstr) as conn:
        if os.path.exists(ret_path):
            print(f"\nReturns: {ret_path}")
            ret_ct = upsert_returns(conn, ret_path)
            print(f"  Upserted: {ret_ct:,}")

        if os.path.exists(stats_path):
            print(f"\nStats: {stats_path}")
            stat_ct = upsert_stats(conn, stats_path)
            print(f"  Upserted: {stat_ct:,}")

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE in {elapsed:.1f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
