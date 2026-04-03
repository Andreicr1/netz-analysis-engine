
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
        print("Checking for duplicate class_id across different CIKs:")
        res = conn.execute(text("SELECT class_id, count(distinct cik) FROM sec_fund_classes GROUP BY 1 HAVING count(distinct cik) > 1"))
        for row in res:
            print(row)

    engine.dispose()

if __name__ == "__main__":
    main()
