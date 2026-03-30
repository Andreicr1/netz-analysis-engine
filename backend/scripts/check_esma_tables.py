import os

os.environ.setdefault("DATABASE_URL_SYNC", 
    "postgresql+psycopg://tsdbadmin:s4wpyvwj0i5bjg0s@nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb?sslmode=require")

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL_SYNC"])
with engine.connect() as conn:
    rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    print("All alembic_version rows:", [r[0] for r in rows])
    
    for tbl in ["esma_managers", "esma_funds", "sec_nport_holdings", "bis_statistics", "imf_weo_forecasts"]:
        exists = conn.execute(text(
            f"SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='{tbl}')"
        )).scalar()
        print(f"  {tbl}: {'EXISTS' if exists else 'MISSING'}")
