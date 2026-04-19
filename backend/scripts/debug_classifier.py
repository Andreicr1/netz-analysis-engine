"""Debug: run strategy classifier directly on problem tickers."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://netz:password@127.0.0.1:5434/netz_engine",
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main() -> None:
    from app.domains.wealth.services.strategy_classifier import classify_fund

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    tickers = ["SCHD", "QQQM", "SCHB", "VMIAX", "FJUL", "AGG", "XLF", "FEZ", "SPY"]

    async with Session() as db:
        for t in tickers:
            result = await db.execute(
                text("""
                    SELECT ticker, name,
                           attributes->>'tiingo_description' AS desc,
                           attributes->>'fund_type' AS fund_type
                    FROM instruments_universe WHERE ticker = :t LIMIT 1
                """),
                {"t": t},
            )
            row = result.mappings().one_or_none()
            if not row:
                print(f"{t:8} NOT FOUND")
                continue
            res = classify_fund(
                fund_name=row["name"],
                fund_type=row["fund_type"],
                tiingo_description=row["desc"],
            )
            print(f"{t:8} -> {res.strategy_label!r:30} fields={vars(res)}")


if __name__ == "__main__":
    asyncio.run(main())
