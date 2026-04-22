"""Best-effort Tiingo tick persistence for intraday candle history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

INSERT_INTRADAY_TICK_SQL = """
    INSERT INTO intraday_market_ticks (time, ticker, price, size, source)
    VALUES ($1, $2, $3, $4, $5)
"""


def _parse_timestamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _tick_row(tick: dict[str, Any]) -> tuple[datetime, str, float, int, str] | None:
    data = tick.get("data")
    if not isinstance(data, dict):
        return None

    ticker = str(data.get("ticker") or tick.get("ticker") or "").upper()
    if not ticker:
        return None

    price = data.get("price")
    if price is None:
        return None

    size = data.get("volume")
    source = str(data.get("source") or "tiingo")
    timestamp = data.get("timestamp") or tick.get("timestamp")

    return (
        _parse_timestamp(timestamp),
        ticker,
        float(price),
        int(size or 0),
        source,
    )


async def persist_ticks_batch(pool: Any | None, ticks: list[dict[str, Any]]) -> int:
    """Persist a Tiingo tick batch using one asyncpg executemany call.

    The caller owns best-effort error handling. A missing pool is treated
    as disabled persistence so tests and local dev can instantiate the
    bridge without a database connection.
    """
    if pool is None or not ticks:
        return 0

    rows = [row for tick in ticks if (row := _tick_row(tick)) is not None]
    if not rows:
        return 0

    async with pool.acquire() as conn:
        await conn.executemany(INSERT_INTRADAY_TICK_SQL, rows)
    return len(rows)
