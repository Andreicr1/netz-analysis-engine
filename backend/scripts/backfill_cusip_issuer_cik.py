"""Backfill sec_cusip_ticker_map.issuer_cik from SEC company_tickers.json.

Reads the SEC-published ticker->CIK map and updates rows in
sec_cusip_ticker_map where issuer_cik IS NULL but ticker IS NOT NULL.
Idempotent — safe to rerun. Reports before/after coverage.

Usage:
    python backend/scripts/backfill_cusip_issuer_cik.py

Environment:
    COMPANY_TICKERS_JSON  — path to company_tickers.json
                            (default: C:\\Users\\Andrei\\Desktop\\EDGAR FILES\\company_tickers.json)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db.engine import async_session_factory  # noqa: E402

DEFAULT_PATH = Path(os.environ.get(
    "COMPANY_TICKERS_JSON",
    r"C:\Users\Andrei\Desktop\EDGAR FILES\company_tickers.json",
))


async def backfill(file_path: Path = DEFAULT_PATH) -> dict[str, int]:
    if not file_path.exists():
        raise FileNotFoundError(
            f"company_tickers.json not found at {file_path}. "
            f"Set COMPANY_TICKERS_JSON env var or download from "
            f"https://www.sec.gov/files/company_tickers.json"
        )

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    ticker_to_cik: dict[str, int] = {
        row["ticker"].upper(): int(row["cik_str"])
        for row in raw.values()
        if row.get("ticker")
    }

    async with async_session_factory() as db:
        before = await db.scalar(text(
            "SELECT COUNT(*) FROM sec_cusip_ticker_map WHERE issuer_cik IS NOT NULL"
        ))

        # Temp table for bulk join-update
        await db.execute(text(
            "CREATE TEMP TABLE tmp_ticker_cik (ticker TEXT PRIMARY KEY, cik BIGINT NOT NULL) "
            "ON COMMIT DROP"
        ))

        # Batch insert into temp table
        batch_size = 1000
        items = list(ticker_to_cik.items())
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            values = ", ".join(
                f"('{ticker}', {cik})" for ticker, cik in batch
                if "'" not in ticker  # skip tickers with quotes (safety)
            )
            if values:
                await db.execute(text(
                    f"INSERT INTO tmp_ticker_cik (ticker, cik) VALUES {values} "
                    f"ON CONFLICT (ticker) DO NOTHING"
                ))

        # Bulk update
        result = await db.execute(text("""
            UPDATE sec_cusip_ticker_map m
            SET issuer_cik = t.cik::TEXT
            FROM tmp_ticker_cik t
            WHERE UPPER(m.ticker) = t.ticker
              AND m.issuer_cik IS NULL
              AND m.ticker IS NOT NULL
        """))
        updated = result.rowcount

        await db.commit()

        after = await db.scalar(text(
            "SELECT COUNT(*) FROM sec_cusip_ticker_map WHERE issuer_cik IS NOT NULL"
        ))

    print(f"backfill: {before} -> {after} (+{updated} rows updated)")
    return {"before": before, "after": after, "updated": updated}


if __name__ == "__main__":
    asyncio.run(backfill())
