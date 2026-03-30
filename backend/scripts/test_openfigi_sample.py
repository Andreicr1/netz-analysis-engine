"""Test OpenFIGI response for a sample of ESMA ISINs to diagnose resolved=0."""
import os

os.environ.setdefault("DATABASE_URL_SYNC",
    "postgresql+psycopg://tsdbadmin:s4wpyvwj0i5bjg0s@nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb?sslmode=require")

import httpx
from sqlalchemy import create_engine, text

# Fetch 10 ISINs from DB
engine = create_engine(os.environ["DATABASE_URL_SYNC"])
with engine.connect() as conn:
    rows = conn.execute(text("SELECT isin, fund_name, fund_type FROM esma_funds LIMIT 10")).fetchall()

isins = [r[0] for r in rows]
print("Sample ISINs:")
for r in rows:
    print(f"  {r[0]}  {r[1][:50]}  type={r[2]}")

# Call OpenFIGI with API key
API_KEY = "475b71ce-e7c0-43a5-84f2-5716cd412cd9"
payload = [
    {"idType": "ID_ISIN", "idValue": isin, "includeUnlistedEquities": True}
    for isin in isins
]

resp = httpx.post(
    "https://api.openfigi.com/v3/mapping",
    json=payload,
    headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": API_KEY},
    timeout=30.0,
)
print(f"\nHTTP {resp.status_code}")
results = resp.json()
for isin, result in zip(isins, results, strict=False):
    if "data" in result:
        d = result["data"][0]
        print(f"  {isin}: ticker={d.get('ticker')} exchCode={d.get('exchCode')} sector={d.get('marketSector')} type={d.get('securityType')}")
    else:
        print(f"  {isin}: {result.get('warning') or result.get('error') or 'no data'}")
