"""Upsert N-PORT holdings CSVs into sec_nport_holdings via psycopg3.

Uses COPY to a temp table + INSERT...ON CONFLICT for maximum throughput.
No asyncpg, no SQLAlchemy — direct psycopg3 connection.

Usage:
    cd backend
    python scripts/upsert_nport_csvs.py --dir "C:/Users/Andrei/Desktop/EDGAR FILES/nport_parsed"
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
    """Build sync psycopg3 connection string from DATABASE_URL."""
    from app.core.config.settings import settings
    url = str(settings.database_url)
    # asyncpg URL → psycopg: replace +asyncpg with empty
    return url.replace("postgresql+asyncpg://", "postgresql://")


def upsert_csv(conn, csv_path: str) -> int:
    """COPY CSV to temp table, then upsert into sec_nport_holdings."""
    with conn.cursor() as cur:
        # Create temp table matching sec_nport_holdings
        cur.execute("""
            CREATE TEMP TABLE _nport_staging (
                report_date DATE,
                cik TEXT,
                cusip TEXT,
                isin TEXT,
                issuer_name TEXT,
                asset_class TEXT,
                sector TEXT,
                market_value BIGINT,
                quantity NUMERIC,
                currency TEXT,
                pct_of_nav NUMERIC,
                is_restricted TEXT,
                fair_value_level TEXT,
                series_id TEXT
            ) ON COMMIT DROP
        """)

        # COPY CSV directly into temp table
        with open(csv_path, encoding="utf-8") as f:
            with cur.copy(
                "COPY _nport_staging FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                for line in f:
                    copy.write(line.encode("utf-8"))

        # Count staged
        cur.execute("SELECT COUNT(*) FROM _nport_staging")
        staged = cur.fetchone()[0]

        # Upsert from staging → real table (deduplicate on PK first)
        cur.execute("""
            INSERT INTO sec_nport_holdings
                (report_date, cik, cusip, isin, issuer_name, asset_class, sector,
                 market_value, quantity, currency, pct_of_nav, is_restricted,
                 fair_value_level, series_id)
            SELECT DISTINCT ON (report_date, cik, cusip)
                report_date, cik, cusip,
                NULLIF(isin, ''),
                issuer_name,
                NULLIF(asset_class, ''),
                NULLIF(sector, ''),
                market_value,
                quantity,
                currency,
                pct_of_nav,
                is_restricted = 't',
                NULLIF(fair_value_level, ''),
                NULLIF(series_id, '')
            FROM _nport_staging
            ORDER BY report_date, cik, cusip, ABS(market_value) DESC NULLS LAST
            ON CONFLICT (report_date, cik, cusip) DO UPDATE SET
                isin = EXCLUDED.isin,
                issuer_name = EXCLUDED.issuer_name,
                asset_class = EXCLUDED.asset_class,
                sector = EXCLUDED.sector,
                market_value = EXCLUDED.market_value,
                quantity = EXCLUDED.quantity,
                currency = EXCLUDED.currency,
                pct_of_nav = EXCLUDED.pct_of_nav,
                is_restricted = EXCLUDED.is_restricted,
                fair_value_level = EXCLUDED.fair_value_level,
                series_id = EXCLUDED.series_id
        """)
        upserted = cur.rowcount

    conn.commit()
    return upserted


def main():
    parser = argparse.ArgumentParser(description="Upsert N-PORT CSVs via psycopg3 COPY")
    parser.add_argument("--dir", required=True, help="Directory with CSV files")
    args = parser.parse_args()

    import psycopg

    connstr = get_connection_string()
    csv_files = sorted(f for f in os.listdir(args.dir) if f.endswith(".csv"))

    print(f"{'=' * 60}")
    print("  N-PORT Holdings Upserter (psycopg3 COPY)")
    print(f"  CSVs: {len(csv_files)} | Source: {args.dir}")
    print(f"{'=' * 60}")

    grand_total = 0
    t_start = time.monotonic()

    with psycopg.connect(connstr) as conn:
        for qi, csv_file in enumerate(csv_files, 1):
            csv_path = os.path.join(args.dir, csv_file)
            t0 = time.monotonic()

            try:
                upserted = upsert_csv(conn, csv_path)
                elapsed = time.monotonic() - t0
                grand_total += upserted
                print(f"[{qi}/{len(csv_files)}] {csv_file}: "
                      f"{upserted:,} rows in {elapsed:.1f}s "
                      f"({upserted / max(elapsed, 1):,.0f} rows/s)")
            except Exception as e:
                conn.rollback()
                print(f"[{qi}/{len(csv_files)}] {csv_file}: FAILED — {str(e)[:200]}")

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {len(csv_files)} files")
    print(f"  Total upserted: {grand_total:,}")
    print(f"  Time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print(f"  Rate: {grand_total / max(elapsed, 1):,.0f} rows/s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
