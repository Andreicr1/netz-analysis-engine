"""DB capabilities + vectorizable content survey."""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

raw = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
url = raw.replace("postgresql+asyncpg://", "postgresql://")
if "sslmode" not in url:
    sep = "&" if "?" in url else "?"
    url = url + sep + "sslmode=require"

async def main():
    conn = await asyncpg.connect(url)
    # Suppress RLS custom parameter errors
    await conn.execute("SET app.current_organization_id = '00000000-0000-0000-0000-000000000000'")

    print("=== EXTENSIONS INSTALLED ===")
    rows = await conn.fetch("""
        SELECT name, default_version, installed_version
        FROM pg_available_extensions
        WHERE name IN ('ai','pgai','vectorscale','timescaledb','vector','pg_vectorize')
        ORDER BY name
    """)
    for r in rows:
        print(f"  {r['name']:<25} default={r['default_version']}  installed={r['installed_version']}")

    print("\n=== BROCHURE SECTIONS distribution ===")
    rows2 = await conn.fetch("""
        SELECT section, COUNT(*) AS cnt
        FROM sec_manager_brochure_text
        GROUP BY section ORDER BY cnt DESC
    """)
    for r in rows2:
        print(f"  {r['section']:<40} {r['cnt']:>8,}")

    print("\n=== ESMA FUNDS fields ===")
    row = await conn.fetchrow("""
        SELECT
            COUNT(*) AS total,
            COUNT(fund_name) AS has_name,
            COUNT(fund_type) AS has_type,
            COUNT(domicile) AS has_domicile,
            COUNT(yahoo_ticker) AS has_ticker
        FROM esma_funds
    """)
    print(f"  total={row['total']:,}  name={row['has_name']:,}  type={row['has_type']:,}  domicile={row['has_domicile']:,}  ticker={row['has_ticker']:,}")

    print("\n=== ESMA MANAGERS fields ===")
    row2 = await conn.fetchrow("""
        SELECT COUNT(*) AS total, COUNT(company_name) AS has_name, COUNT(country) AS has_country
        FROM esma_managers
    """)
    print(f"  total={row2['total']:,}  name={row2['has_name']:,}  country={row2['has_country']:,}")

    print("\n=== DD CHAPTERS content size ===")
    row3 = await conn.fetchrow("""
        SELECT COUNT(*) AS total,
               AVG(LENGTH(content_md)) AS avg_len,
               MAX(LENGTH(content_md)) AS max_len,
               COUNT(DISTINCT chapter_tag) AS unique_chapters
        FROM dd_chapters WHERE content_md IS NOT NULL
    """)
    print(f"  total={row3['total']:,}  avg_len={int(row3['avg_len'] or 0):,}  max_len={int(row3['max_len'] or 0):,}  chapters={row3['unique_chapters']}")

    print("\n=== MACRO REVIEWS report_json ===")
    row4 = await conn.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(decision_rationale) AS has_rationale,
               COUNT(report_json) AS has_json
        FROM macro_reviews
    """)
    print(f"  total={row4['total']:,}  rationale={row4['has_rationale']:,}  json={row4['has_json']:,}")

    print("\n=== SEC MANAGERS text fields sample ===")
    row5 = await conn.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(website) AS has_website,
               COUNT(client_types) AS has_client_types,
               COUNT(fee_types) AS has_fee_types
        FROM sec_managers
        WHERE registration_status = 'Registered'
    """)
    print(f"  registered={row5['total']:,}  website={row5['has_website']:,}  client_types={row5['has_client_types']:,}  fee_types={row5['has_fee_types']:,}")

    await conn.close()

asyncio.run(main())
