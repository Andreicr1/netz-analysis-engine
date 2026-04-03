
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

from app.domains.wealth.queries.catalog_sql import CatalogFilters, build_catalog_query

load_dotenv(".env.production")
URL = os.getenv("DATABASE_URL_SYNC")
if URL and "postgresql://" in URL:
    URL = URL.replace("postgresql://", "postgresql+psycopg://")

def main():
    if not URL:
        print("DATABASE_URL_SYNC not found")
        return
    engine = create_engine(URL)
    
    # Test 1: Basic query
    filters = CatalogFilters(page=1, page_size=5)
    stmt = build_catalog_query(filters)
    print(f"SQL Generated: {stmt}")
    
    with engine.connect() as conn:
        res = conn.execute(stmt)
        print("\nResults found:")
        for row in res:
            # Row has all columns + _total + aum
            print(f" - {row.name} ({row.universe}) | AUM: {row.aum} | Total in DB: {row._total}")

    # Test 2: Filter by category
    filters = CatalogFilters(fund_universe="etf", page=1, page_size=5)
    stmt = build_catalog_query(filters)
    with engine.connect() as conn:
        res = conn.execute(stmt)
        print("\nETF Results:")
        for row in res:
            print(f" - {row.name} | Type: {row.fund_type}")

    engine.dispose()

if __name__ == "__main__":
    # Add project root to sys.path to allow imports
    import sys
    sys.path.append(os.path.join(os.getcwd(), "backend"))
    main()
