
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(".env.production")
URL = os.getenv("DATABASE_URL_SYNC")
if URL and "postgresql://" in URL:
    URL = URL.replace("postgresql://", "postgresql+psycopg://")

def main():
    if not URL:
        print("DATABASE_URL_SYNC not found")
        return
    engine = create_engine(URL)
    
    # Test global search for a common ticker or name
    query = "BlackRock"
    print(f"Testing global search for: {query}")
    
    with engine.connect() as conn:
        res = conn.execute(text(f"""
            SELECT id, name, ticker, asset_class, source 
            FROM mv_unified_assets 
            WHERE name ILIKE '%{query}%' OR ticker ILIKE '%{query}%'
            LIMIT 5
        """))
        print("\nAssets found in mv_unified_assets:")
        for row in res:
            print(f" - {row.name} ({row.ticker}) | Class: {row.asset_class} | Source: {row.source}")

    engine.dispose()

if __name__ == "__main__":
    main()
