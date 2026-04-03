
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(".env.production")
URL = os.getenv("DATABASE_URL_SYNC")
if URL and "postgresql://" in URL:
    URL = URL.replace("postgresql://", "postgresql+psycopg://")

def main():
    engine = create_engine(URL)
    with engine.connect() as conn:
        print("Fixing mv_unified_assets index...")
        conn.execute(text("DROP INDEX IF EXISTS idx_mv_unified_assets_id;"))
        conn.execute(text("CREATE UNIQUE INDEX idx_mv_unified_assets_id ON mv_unified_assets (id, source);"))
        conn.commit()
        print("Done.")

    engine.dispose()

if __name__ == "__main__":
    main()
