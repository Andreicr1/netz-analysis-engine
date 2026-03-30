"""Quick DB inventory — row counts + text column survey."""
import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import asyncpg

URL = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
# Strip SQLAlchemy driver prefix if present
if URL:
    URL = URL.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]


async def main():
    conn = await asyncpg.connect(URL)

    print("=== ROW COUNTS (public schema) ===")
    rows = await conn.fetch("""
        SELECT relname AS tablename, n_live_tup
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
        ORDER BY n_live_tup DESC
        LIMIT 80
    """)
    for r in rows:
        print(f"  {r['tablename']:<55} {r['n_live_tup']:>12,}")

    print("\n=== TEXT / JSONB COLUMNS (candidate for embedding) ===")
    cols = await conn.fetch("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND data_type IN ('text', 'jsonb', 'character varying')
          AND column_name NOT IN (
              'id','organization_id','created_at','updated_at',
              'filing_date','calc_date','nav_date','report_date',
              'snapshot_date','effective_from','effective_to',
              'ticker','isin','cusip','crd_number','cik','lei',
              'currency','status','profile','domain','doc_type',
              'section_type','embedding_model','blob_name',
              'container_name','accession_number','sec_number'
          )
        ORDER BY table_name, column_name
    """)
    current_table = None
    for c in cols:
        if c['table_name'] != current_table:
            current_table = c['table_name']
            print(f"\n  [{current_table}]")
        print(f"    {c['column_name']:<40} {c['data_type']}")

    await conn.close()


asyncio.run(main())
