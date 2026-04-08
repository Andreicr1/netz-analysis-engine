import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL_SYNC")

def clean_outliers():
    if not DATABASE_URL:
        print("Error: DATABASE_URL_SYNC not found in .env")
        return

    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        print("Cleaning sec_fund_prospectus_stats...")
        res1 = conn.execute(text(
            "UPDATE sec_fund_prospectus_stats "
            "SET expense_ratio_pct = NULL "
            "WHERE expense_ratio_pct > 1.0"
        ))
        
        print("Cleaning sec_fund_classes...")
        res2 = conn.execute(text(
            "UPDATE sec_fund_classes "
            "SET expense_ratio_pct = NULL "
            "WHERE expense_ratio_pct > 1.0"
        ))
        
        conn.commit()
        print(f"Done. Rows affected - Stats: {res1.rowcount}, Classes: {res2.rowcount}")

        print("\nAuditing moderate outliers (0.1 to 1.0)...")
        res3 = conn.execute(text(
            "SELECT series_id, expense_ratio_pct, management_fee_pct "
            "FROM sec_fund_prospectus_stats "
            "WHERE expense_ratio_pct BETWEEN 0.1 AND 1.0 "
            "ORDER BY expense_ratio_pct DESC LIMIT 10"
        ))
        rows = res3.fetchall()
        if rows:
            print("Top 10 moderate outliers in Stats:")
            for r in rows:
                print(f"  Series: {r[0]}, ER: {r[1]}, Mgmt: {r[2]}")
        else:
            print("No moderate outliers found.")

if __name__ == "__main__":
    clean_outliers()
