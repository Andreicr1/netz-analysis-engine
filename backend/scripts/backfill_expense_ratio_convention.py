import os
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL_SYNC")

def backfill():
    if not DATABASE_URL:
        print("Error: DATABASE_URL_SYNC not found in .env")
        return

    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        print("Counting instruments with expense_ratio_pct > 1.0...")
        # Only check if expense_ratio_pct is present and a number
        query = text(
            "SELECT instrument_id, attributes "
            "FROM instruments_universe "
            "WHERE (attributes->>'expense_ratio_pct') IS NOT NULL"
        )
        
        res = conn.execute(query)
        rows = res.fetchall()
        
        count = 0
        for i_id, attrs in rows:
            if not attrs:
                continue
            
            er = attrs.get("expense_ratio_pct")
            try:
                if er is not None and float(er) > 1.0:
                    # Fix convention (1.5 -> 0.015)
                    new_er = float(er) / 100.0
                    attrs["expense_ratio_pct"] = new_er
                    
                    # Also fix other related pct columns if they exist as outliers
                    for key in ["management_fee_pct", "portfolio_turnover_pct", "tracking_difference_net"]:
                        val = attrs.get(key)
                        if val is not None and float(val) > 1.0:
                            attrs[key] = float(val) / 100.0
                    
                    conn.execute(
                        text("UPDATE instruments_universe SET attributes = :attr WHERE instrument_id = :id"),
                        {"attr": json.dumps(attrs), "id": i_id}
                    )
                    count += 1
            except (ValueError, TypeError):
                continue
        
        conn.commit()
        print(f"Done. Instruments updated: {count}")

        # Phase 4.1: Refresh Materialized View
        print("\nRefreshing Materialized View mv_unified_funds...")
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds"))
        conn.commit()
        print("Refresh complete.")

if __name__ == "__main__":
    backfill()
