"""Treasury data ingestion worker — fetches rates, debt, auctions, FX, interest expense.

Usage:
    python -m app.domains.wealth.workers.treasury_ingestion

Fetches data from the US Treasury Fiscal Data API via FiscalDataService
and upserts into the treasury_data hypertable.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_011.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import TreasuryData
from quant_engine.fiscal_data_service import (
    AuctionResult,
    DebtSnapshot,
    ExchangeRate,
    FiscalDataService,
    InterestExpense,
    TreasuryRate,
)

logger = structlog.get_logger()
TREASURY_LOCK_ID = 900_011


def _safe_decimal(value: float | None) -> Decimal | None:
    """Convert float to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _rates_to_rows(rates: list[TreasuryRate]) -> list[dict]:
    """Convert TreasuryRate dataclasses to upsert dicts."""
    rows: list[dict] = []
    for r in rates:
        val = _safe_decimal(r.avg_interest_rate_amt)
        if val is None:
            continue
        try:
            obs_date = date.fromisoformat(r.record_date)
        except (ValueError, TypeError):
            continue
        # Normalize security_desc to series_id: "Treasury Bills" → "RATE_TREASURY_BILLS"
        series_id = f"RATE_{r.security_desc.upper().replace(' ', '_')}"
        if len(series_id) > 80:
            series_id = series_id[:80]
        rows.append({
            "obs_date": obs_date,
            "series_id": series_id,
            "value": val,
            "source": "treasury_api",
        })
    return rows


def _debt_to_rows(snapshots: list[DebtSnapshot]) -> list[dict]:
    """Convert DebtSnapshot dataclasses to upsert dicts."""
    rows: list[dict] = []
    for d in snapshots:
        try:
            obs_date = date.fromisoformat(d.record_date)
        except (ValueError, TypeError):
            continue
        for field, series_id in (
            ("tot_pub_debt_out_amt", "DEBT_TOTAL_PUBLIC"),
            ("intragov_hold_amt", "DEBT_INTRAGOV"),
            ("debt_held_public_amt", "DEBT_HELD_PUBLIC"),
        ):
            val = _safe_decimal(getattr(d, field))
            if val is not None:
                rows.append({
                    "obs_date": obs_date,
                    "series_id": series_id,
                    "value": val,
                    "source": "treasury_api",
                })
    return rows


def _auctions_to_rows(auctions: list[AuctionResult]) -> list[dict]:
    """Convert AuctionResult dataclasses to upsert dicts."""
    rows: list[dict] = []
    for a in auctions:
        val = _safe_decimal(a.high_yield)
        if val is None:
            continue
        try:
            obs_date = date.fromisoformat(a.auction_date)
        except (ValueError, TypeError):
            continue
        series_id = f"AUCTION_{a.security_type}_{a.security_term}".upper().replace(" ", "_")
        if len(series_id) > 80:
            series_id = series_id[:80]
        rows.append({
            "obs_date": obs_date,
            "series_id": series_id,
            "value": val,
            "source": "treasury_api",
            "metadata_json": {
                "security_type": a.security_type,
                "security_term": a.security_term,
                "bid_to_cover": a.bid_to_cover_ratio,
            },
        })
    return rows


def _fx_to_rows(rates: list[ExchangeRate]) -> list[dict]:
    """Convert ExchangeRate dataclasses to upsert dicts."""
    rows: list[dict] = []
    for r in rates:
        val = _safe_decimal(r.exchange_rate)
        if val is None:
            continue
        try:
            obs_date = date.fromisoformat(r.record_date)
        except (ValueError, TypeError):
            continue
        series_id = f"FX_{r.country_currency_desc.upper().replace(' ', '_').replace('-', '_')}"
        if len(series_id) > 80:
            series_id = series_id[:80]
        rows.append({
            "obs_date": obs_date,
            "series_id": series_id,
            "value": val,
            "source": "treasury_api",
        })
    return rows


def _interest_expense_to_rows(expenses: list[InterestExpense]) -> list[dict]:
    """Convert InterestExpense dataclasses to upsert dicts."""
    rows: list[dict] = []
    for e in expenses:
        try:
            obs_date = date.fromisoformat(e.record_date)
        except (ValueError, TypeError):
            continue
        catg = e.expense_catg_desc.upper().replace(" ", "_")
        for suffix, val_float in (("MONTH", e.month_expense_amt), ("FYTD", e.fytd_expense_amt)):
            val = _safe_decimal(val_float)
            if val is not None:
                series_id = f"INTEREST_{catg}_{suffix}"
                if len(series_id) > 80:
                    series_id = series_id[:80]
                rows.append({
                    "obs_date": obs_date,
                    "series_id": series_id,
                    "value": val,
                    "source": "treasury_api",
                })
    return rows


async def run_treasury_ingestion(lookback_days: int = 365) -> dict:
    """Fetch treasury data and upsert to treasury_data hypertable."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({TREASURY_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("Treasury ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            today = date.today()
            start = (today - timedelta(days=lookback_days)).isoformat()

            rows: list[dict] = []

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                service = FiscalDataService(http_client)

                # Fetch all data types concurrently
                rates_t, debt_t, auctions_t, fx_t, expense_t = await asyncio.gather(
                    service.fetch_treasury_rates(start),
                    service.fetch_debt_to_penny(start),
                    service.fetch_treasury_auctions(start),
                    service.fetch_exchange_rates(start),
                    service.fetch_interest_expense(start),
                    return_exceptions=True,
                )

                if isinstance(rates_t, list):
                    rows.extend(_rates_to_rows(rates_t))
                else:
                    logger.warning("treasury_rates_fetch_failed", error=str(rates_t))

                if isinstance(debt_t, list):
                    rows.extend(_debt_to_rows(debt_t))
                else:
                    logger.warning("treasury_debt_fetch_failed", error=str(debt_t))

                if isinstance(auctions_t, list):
                    rows.extend(_auctions_to_rows(auctions_t))
                else:
                    logger.warning("treasury_auctions_fetch_failed", error=str(auctions_t))

                if isinstance(fx_t, list):
                    rows.extend(_fx_to_rows(fx_t))
                else:
                    logger.warning("treasury_fx_fetch_failed", error=str(fx_t))

                if isinstance(expense_t, list):
                    rows.extend(_interest_expense_to_rows(expense_t))
                else:
                    logger.warning("treasury_expense_fetch_failed", error=str(expense_t))

            # Deduplicate by (obs_date, series_id) — keep last value
            if rows:
                seen: dict[tuple, dict] = {}
                for r in rows:
                    seen[(r["obs_date"], r["series_id"])] = r
                rows = list(seen.values())

                # Normalize: all rows must have same keys for pg_insert multi-row
                for r in rows:
                    r.setdefault("metadata_json", None)

                chunk_size = 2000
                for i in range(0, len(rows), chunk_size):
                    chunk = rows[i:i + chunk_size]
                    stmt = pg_insert(TreasuryData).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["obs_date", "series_id"],
                        set_={
                            "value": stmt.excluded.value,
                            "source": stmt.excluded.source,
                            "metadata_json": stmt.excluded.metadata_json,
                        },
                    )
                    await db.execute(stmt)
                await db.commit()

            logger.info("Treasury ingestion complete", rows_upserted=len(rows))
            return {"status": "completed", "rows": len(rows)}

        except Exception:
            await db.rollback()
            raise
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({TREASURY_LOCK_ID})")
                )
            except Exception:
                pass  # lock auto-released on session close


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=365, help="Lookback in days (default 365)")
    args = parser.parse_args()
    asyncio.run(run_treasury_ingestion(lookback_days=args.lookback))
