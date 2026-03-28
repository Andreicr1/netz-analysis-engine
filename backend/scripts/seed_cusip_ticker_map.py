"""Populate sec_cusip_ticker_map from N-PORT corporate bond CUSIPs via OpenFIGI.

Resolves CUSIP → ticker/issuer for corporate bonds held in N-PORT filings.
This enables insider_sentiment_score for Fixed Income / High Yield funds
(bonds → issuer equity ticker → Form 345 insider flow).

Source: sec_nport_holdings WHERE sector = 'CORP' AND LENGTH(cusip) = 9.
API: OpenFIGI v3 batch mapping (100 CUSIPs per request, 250 req/min with key).

Usage:
    python -m scripts.seed_cusip_ticker_map
    python -m scripts.seed_cusip_ticker_map --sector CORP --resume
    python -m scripts.seed_cusip_ticker_map --dry-run
    python -m scripts.seed_cusip_ticker_map --batch-size 50 --rate-limit 25
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import asyncpg
import httpx
import structlog

logger = structlog.get_logger()

# ── OpenFIGI config ────────────────────────────────────────────────

OPENFIGI_BATCH_URL = "https://api.openfigi.com/v3/mapping"
MAX_BATCH_SIZE = 100  # OpenFIGI hard limit
DEFAULT_RATE_LIMIT = 250  # requests/min with API key
UPSERT_BATCH = 500


# ── DB setup ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        sys.exit("Set DATABASE_URL")
    # asyncpg needs plain postgresql:// (not +asyncpg or +psycopg)
    if "+asyncpg" in raw:
        raw = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    if "+psycopg" in raw:
        raw = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    return raw


async def _connect(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn, ssl="require")


# ── Schema migration (idempotent) ─────────────────────────────────

async def _ensure_schema(conn: asyncpg.Connection) -> None:
    """Add issuer_cik column and indexes if missing."""
    await conn.execute("""
        ALTER TABLE sec_cusip_ticker_map
            ADD COLUMN IF NOT EXISTS issuer_cik VARCHAR;
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cusip_map_issuer_cik
            ON sec_cusip_ticker_map(issuer_cik) WHERE issuer_cik IS NOT NULL;
    """)
    logger.info("schema.ensured", added="issuer_cik column + index (if missing)")


# ── Fetch unresolved CUSIPs ───────────────────────────────────────

async def _fetch_cusips(
    conn: asyncpg.Connection,
    sector: str,
    resume: bool,
) -> list[str]:
    """Get distinct 9-char CUSIPs from sec_nport_holdings for sector."""
    if resume:
        rows = await conn.fetch("""
            SELECT DISTINCT h.cusip
            FROM sec_nport_holdings h
            LEFT JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip
            WHERE h.cusip IS NOT NULL
              AND h.sector = $1
              AND LENGTH(h.cusip) = 9
              AND m.cusip IS NULL
            ORDER BY h.cusip
        """, sector)
    else:
        rows = await conn.fetch("""
            SELECT DISTINCT h.cusip
            FROM sec_nport_holdings h
            WHERE h.cusip IS NOT NULL
              AND h.sector = $1
              AND LENGTH(h.cusip) = 9
            ORDER BY h.cusip
        """, sector)
    return [r["cusip"] for r in rows]


# ── OpenFIGI resolution ───────────────────────────────────────────

TRADEABLE_EXCHANGES = {"US", "UN", "UW", "UA", "UR", "UT"}


async def _resolve_batch(
    http: httpx.AsyncClient,
    cusips: list[str],
    api_key: str | None,
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Resolve a batch of CUSIPs via OpenFIGI. Returns parsed rows."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]

    async with sem:
        try:
            resp = await http.post(
                OPENFIGI_BATCH_URL, json=payload, headers=headers, timeout=30.0,
            )
            if resp.status_code == 429:
                logger.warning("openfigi.rate_limited", sleeping=60)
                await asyncio.sleep(60)
                return await _resolve_batch(http, cusips, api_key, sem)
            resp.raise_for_status()
            results = resp.json()
        except Exception as exc:
            logger.warning("openfigi.batch_failed", error=str(exc), count=len(cusips))
            return [_unresolved(c) for c in cusips]

    if not isinstance(results, list) or len(results) != len(cusips):
        logger.warning("openfigi.bad_response", expected=len(cusips))
        return [_unresolved(c) for c in cusips]

    rows = []
    for cusip, result in zip(cusips, results, strict=True):
        if "data" not in result or not result["data"]:
            rows.append(_unresolved(cusip))
            continue
        best = _pick_best(result["data"])
        ticker = best.get("ticker")
        exchange = best.get("exchCode")
        rows.append({
            "cusip": cusip,
            "ticker": ticker,
            "issuer_name": best.get("name"),
            "exchange": exchange,
            "security_type": best.get("securityType"),
            "figi": best.get("figi"),
            "composite_figi": best.get("compositeFIGI"),
            "resolved_via": "openfigi",
            "is_tradeable": bool(ticker and exchange in TRADEABLE_EXCHANGES),
        })
    return rows


def _unresolved(cusip: str) -> dict:
    return {
        "cusip": cusip,
        "ticker": None,
        "issuer_name": None,
        "exchange": None,
        "security_type": None,
        "figi": None,
        "composite_figi": None,
        "resolved_via": "unresolved",
        "is_tradeable": False,
    }


def _pick_best(candidates: list[dict]) -> dict:
    """Pick best match: prefer equity on US exchange."""
    equity_types = {"Common Stock", "ADR", "ETP"}
    us_exchanges = {"US", "UN", "UA", "UW"}

    equity = [c for c in candidates if c.get("securityType") in equity_types]
    pool = equity if equity else candidates

    us = [c for c in pool if c.get("exchCode") in us_exchanges]
    return us[0] if us else pool[0]


# ── Upsert ─────────────────────────────────────────────────────────

_UPSERT_SQL = """
    INSERT INTO sec_cusip_ticker_map
        (cusip, ticker, issuer_name, exchange, security_type,
         figi, composite_figi, resolved_via, is_tradeable, last_verified_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
    ON CONFLICT (cusip) DO UPDATE SET
        ticker          = EXCLUDED.ticker,
        issuer_name     = EXCLUDED.issuer_name,
        exchange        = EXCLUDED.exchange,
        security_type   = EXCLUDED.security_type,
        figi            = EXCLUDED.figi,
        composite_figi  = EXCLUDED.composite_figi,
        resolved_via    = EXCLUDED.resolved_via,
        is_tradeable    = EXCLUDED.is_tradeable,
        last_verified_at = NOW()
    WHERE sec_cusip_ticker_map.resolved_via = 'unresolved'
       OR EXCLUDED.resolved_via != 'unresolved'
"""


async def _upsert_rows(conn: asyncpg.Connection, rows: list[dict]) -> int:
    """Batch upsert rows into sec_cusip_ticker_map."""
    if not rows:
        return 0

    tuples = [
        (
            r["cusip"], r["ticker"], r["issuer_name"], r["exchange"],
            r["security_type"], r["figi"], r["composite_figi"],
            r["resolved_via"], r["is_tradeable"],
        )
        for r in rows
    ]

    for i in range(0, len(tuples), UPSERT_BATCH):
        batch = tuples[i : i + UPSERT_BATCH]
        await conn.executemany(_UPSERT_SQL, batch)

    return len(rows)


# ── Post-resolution: best-effort issuer_cik via name match ────────

async def _backfill_issuer_cik(conn: asyncpg.Connection) -> int:
    """Try to resolve issuer_cik from sec_managers via firm_name match."""
    result = await conn.execute("""
        UPDATE sec_cusip_ticker_map m
        SET issuer_cik = sub.cik
        FROM (
            SELECT DISTINCT ON (m2.cusip)
                m2.cusip,
                sm.cik
            FROM sec_cusip_ticker_map m2
            JOIN sec_managers sm
                ON LOWER(sm.firm_name) = LOWER(m2.issuer_name)
            WHERE m2.issuer_cik IS NULL
              AND m2.issuer_name IS NOT NULL
            ORDER BY m2.cusip
        ) sub
        WHERE m.cusip = sub.cusip
    """)
    # asyncpg returns "UPDATE N"
    return int(result.split()[-1]) if result else 0


# ── Main ───────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    api_key = os.environ.get("OPENFIGI_API_KEY")
    if not api_key:
        logger.warning("OPENFIGI_API_KEY not set — using free tier (25 req/min)")

    dsn = _resolve_dsn(args.dsn)
    conn = await _connect(dsn)

    try:
        # Step 0: ensure schema
        await _ensure_schema(conn)

        # Step 1: fetch CUSIPs
        cusips = await _fetch_cusips(conn, args.sector, args.resume)
        logger.info("cusips.fetched", sector=args.sector, count=len(cusips), resume=args.resume)

        if not cusips:
            logger.info("nothing_to_do")
            return

        if args.dry_run:
            print(f"[DRY RUN] Would resolve {len(cusips)} CUSIPs from sector={args.sector}")
            return

        # Step 2: resolve via OpenFIGI
        batch_size = min(args.batch_size, MAX_BATCH_SIZE)
        rate_limit = args.rate_limit if api_key else 25
        max_concurrent = max(1, rate_limit // 60)
        sem = asyncio.Semaphore(max_concurrent)
        sleep_between = 60.0 / rate_limit

        batches = [cusips[i : i + batch_size] for i in range(0, len(cusips), batch_size)]
        logger.info(
            "resolving",
            total_cusips=len(cusips),
            batches=len(batches),
            batch_size=batch_size,
            rate_limit=rate_limit,
            has_api_key=bool(api_key),
        )

        stats = {"resolved": 0, "tradeable": 0, "unresolved": 0}
        t0 = time.monotonic()

        async with httpx.AsyncClient() as http:
            all_rows: list[dict] = []
            for batch_num, batch in enumerate(batches, 1):
                rows = await _resolve_batch(http, batch, api_key, sem)
                all_rows.extend(rows)

                batch_resolved = sum(1 for r in rows if r["resolved_via"] != "unresolved")
                batch_unresolved = len(rows) - batch_resolved
                batch_tradeable = sum(1 for r in rows if r["is_tradeable"])
                stats["resolved"] += batch_resolved
                stats["unresolved"] += batch_unresolved
                stats["tradeable"] += batch_tradeable

                if batch_num % 50 == 0 or batch_num == len(batches):
                    elapsed = time.monotonic() - t0
                    logger.info(
                        "progress",
                        batch=f"{batch_num}/{len(batches)}",
                        resolved=stats["resolved"],
                        unresolved=stats["unresolved"],
                        elapsed_s=round(elapsed, 1),
                    )

                # Upsert periodically to avoid memory buildup
                if len(all_rows) >= 2000:
                    await _upsert_rows(conn, all_rows)
                    all_rows.clear()

                await asyncio.sleep(sleep_between)

            # Final upsert
            if all_rows:
                await _upsert_rows(conn, all_rows)

        # Step 3: best-effort issuer_cik backfill
        cik_count = await _backfill_issuer_cik(conn)
        logger.info("issuer_cik.backfilled", count=cik_count)

        elapsed = time.monotonic() - t0
        print(f"\n{'='*60}")
        print(f"  sec_cusip_ticker_map — N-PORT {args.sector} CUSIPs")
        print(f"{'='*60}")
        print(f"  Total CUSIPs:   {len(cusips):>8,}")
        print(f"  Resolved:       {stats['resolved']:>8,}")
        print(f"  Tradeable:      {stats['tradeable']:>8,}")
        print(f"  Unresolved:     {stats['unresolved']:>8,}")
        print(f"  Issuer CIK:     {cik_count:>8,}")
        print(f"  Coverage:       {stats['resolved']/len(cusips)*100:>7.1f}%")
        print(f"  Elapsed:        {elapsed:>7.1f}s")
        print(f"{'='*60}")
    finally:
        await conn.close()


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Populate sec_cusip_ticker_map from N-PORT CUSIPs via OpenFIGI",
    )
    p.add_argument("--sector", default="CORP", help="N-PORT sector filter (default: CORP)")
    p.add_argument("--batch-size", type=int, default=100, help="CUSIPs per OpenFIGI request (max 100)")
    p.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT, help="Requests/min (250 with API key)")
    p.add_argument("--dry-run", action="store_true", help="Count CUSIPs but don't resolve")
    p.add_argument("--resume", action="store_true", help="Skip CUSIPs already in map")
    p.add_argument("--dsn", help="Override DATABASE_URL")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(cli()))
