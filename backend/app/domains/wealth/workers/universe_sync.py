"""Universe sync worker — populates instruments_universe from SEC/ESMA catalog.

Bridges the gap between enriched catalog tables (sec_etfs, sec_fund_classes,
sec_registered_funds, esma_funds) and the global instruments_universe catalog.

Phase 1: SEC ETFs (~925 with ticker)
Phase 2: SEC Mutual Fund series — canonical share class (~4,794 series)
Phase 3: SEC Registered Funds with direct ticker (~363, supplements Phase 2)
Phase 3b: SEC BDCs (27 with ticker resolved via cusip_ticker_map)
Phase 4: ESMA UCITS funds with yahoo_ticker (~2,929)

Advisory lock: 900_070 (global)
Frequency: weekly (alongside sec_bulk_ingestion)

NOTE: instruments_universe has CHECK constraint chk_fund_attrs requiring
attributes to contain 'aum_usd', 'manager_name', 'inception_date' keys
when instrument_type = 'fund'. All phases include these keys.
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

UNIVERSE_SYNC_LOCK_ID = 900_070
SEC_MF_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_USER_AGENT = "Netz/1.0 (andrei@investintell.com)"

# ── Asset class classification constants (centralized) ─────────────────
# All sync phases share these keyword lists. CASE evaluation order:
# cash → explicit equity → alternatives → fixed_income → ELSE equity.
# %% escaping is normalized to % by SQLAlchemy text() for asyncpg.

_CASH_KW = [
    "%%money market%%", "%%cash%%", "%%liquidity%%", "%%ultra short%%",
]
_EQUITY_EXPLICIT_KW = [
    "%%equity income%%", "%%dividend income%%", "%%growth & income%%",
    "%%growth and income%%", "%%balanced%%", "%%allocation%%",
    "%%long/short equity%%", "%%long short equity%%",
]
_ALTERNATIVES_KW = [
    "%%real estate%%", "%%reit%%", "%%commodity%%", "%%commodities%%",
    "%%gold%%", "%%infrastructure%%", "%%private credit%%",
    "%%private equity%%", "%%venture capital%%", "%%hedge%%",
    "%%long/short%%", "%%long short%%", "%%market neutral%%",
    "%%event driven%%", "%%merger arbitrage%%", "%%multi-strategy%%",
    "%%managed futures%%", "%%convertible%%", "%%alternative%%",
]
_FI_KW = [
    "%%bond%%", "%%fixed income%%", "%%treasury%%", "%%government bond%%",
    "%%aggregate bond%%", "%%municipal%%", "%%muni %%",
    "%%investment grade%%", "%%high yield%%", "%%corporate bond%%",
    "%%sovereign%%", "%%mortgage%%", "%%structured%%", "%%securitized%%",
    "%%inflation protected%%", "%%tips%%", "%%floating rate%%",
    "%%bank loan%%", "%%loan%%",
]


def _asset_class_case(col: str) -> str:
    """Build asset_class CASE SQL for the given strategy_label column."""
    def _arr(kws: list[str]) -> str:
        return "ARRAY[" + ",".join(f"'{k}'" for k in kws) + "]"

    return (
        f"CASE\n"
        f"                WHEN {col} ILIKE ANY({_arr(_CASH_KW)}) THEN 'cash'\n"
        f"                WHEN {col} ILIKE ANY({_arr(_EQUITY_EXPLICIT_KW)}) THEN 'equity'\n"
        f"                WHEN {col} ILIKE ANY({_arr(_ALTERNATIVES_KW)}) THEN 'alternatives'\n"
        f"                WHEN {col} ILIKE ANY({_arr(_FI_KW)}) THEN 'fixed_income'\n"
        f"                ELSE 'equity'\n"
        f"            END"
    )


async def run_universe_sync() -> dict[str, Any]:
    """Sync global instrument catalog from SEC/ESMA sources."""
    logger.info("universe_sync.start")

    async with async_session() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({UNIVERSE_SYNC_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("universe_sync.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            stats: dict[str, Any] = {}
            stats["ticker_refresh"] = await _refresh_mf_tickers(db)
            stats["sec_etfs"] = await _sync_sec_etfs(db)
            stats["sec_mf_series"] = await _sync_sec_mf_series(db)
            stats["sec_registered"] = await _sync_sec_registered(db)
            stats["sec_bdcs"] = await _sync_sec_bdcs(db)
            stats["esma_funds"] = await _sync_esma_funds(db)
            stats["deactivated"] = await _deactivate_no_nav(db)

            total = sum(v.get("upserted", 0) for v in stats.values() if isinstance(v, dict))
            logger.info("universe_sync.done", total_upserted=total, **{
                k: v.get("upserted", 0) for k, v in stats.items() if isinstance(v, dict)
            })
            stats["total_upserted"] = total
            return stats
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({UNIVERSE_SYNC_LOCK_ID})"),
            )


# ── Pre-sync: refresh mutual fund tickers from SEC ───────────────────


async def _refresh_mf_tickers(db: AsyncSession) -> dict[str, Any]:
    """Fetch SEC company_tickers_mf.json and update sec_fund_classes tickers.

    Single GET (~1MB), no rate limit. Maps class_id → ticker for all
    mutual fund share classes. Runs before catalog sync so Phase 2
    has maximum ticker coverage.
    """
    import asyncio
    import concurrent.futures
    import json
    from urllib.request import Request, urlopen

    def _download() -> dict[str, Any]:
        req = Request(SEC_MF_TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            return cast(dict[str, Any], json.loads(resp.read()))

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            data = await loop.run_in_executor(pool, _download)
    except Exception as e:
        logger.warning("universe_sync.mf_ticker_fetch_failed", error=str(e)[:200])
        return {"updated": 0, "error": str(e)[:100]}

    rows = data.get("data", [])
    if not rows:
        return {"updated": 0}

    # Build class_id → ticker map
    class_ticker = {class_id: symbol for _cik, _sid, class_id, symbol in rows if symbol}
    logger.info("universe_sync.mf_tickers_fetched", classes=len(class_ticker))

    # Batch update via temp table
    await db.execute(text(
        "CREATE TEMP TABLE IF NOT EXISTS _tmp_mf_ticker "
        "(class_id TEXT PRIMARY KEY, ticker TEXT NOT NULL) ON COMMIT DROP"
    ))
    items = list(class_ticker.items())
    for i in range(0, len(items), 1000):
        chunk = items[i:i + 1000]
        # Escape single quotes in tickers
        vals = ",".join(
            f"('{cid}','{t.replace(chr(39), chr(39)+chr(39))}')"
            for cid, t in chunk
        )
        await db.execute(text(f"INSERT INTO _tmp_mf_ticker VALUES {vals} ON CONFLICT DO NOTHING"))

    result = cast(CursorResult[Any], await db.execute(text("""
        UPDATE sec_fund_classes fc
        SET ticker = t.ticker
        FROM _tmp_mf_ticker t
        WHERE fc.class_id = t.class_id
          AND (fc.ticker IS NULL OR fc.ticker != t.ticker)
    """)))
    updated = result.rowcount
    await db.commit()
    logger.info("universe_sync.mf_tickers_updated", updated=updated)
    return {"updated": updated}


# ── Phase 1: SEC ETFs ────────────────────────────────────────────────


async def _sync_sec_etfs(db: AsyncSession) -> dict[str, Any]:
    """Upsert SEC ETFs into instruments_universe."""
    _sql = """
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, isin, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            e.fund_name,
            e.series_id,
            e.ticker,
            __ASSET_CLASS__,
            'north_america',
            'USD',
            true,
            jsonb_build_object(
                'series_id', e.series_id,
                'sec_cik', e.cik,
                'fund_subtype', 'etf',
                'sec_universe', 'etf',
                'strategy_label', e.strategy_label,
                'is_index', e.is_index,
                'expense_ratio_pct', e.net_operating_expenses,
                'tracking_difference_net', e.tracking_difference_net,
                'aum_usd', e.monthly_avg_net_assets,
                'manager_name', e.fund_name,
                'inception_date', e.inception_date,
                'source', 'universe_sync'
            )
        FROM sec_etfs e
        WHERE e.ticker IS NOT NULL
        ON CONFLICT (ticker) DO UPDATE SET
            name = EXCLUDED.name,
            attributes = instruments_universe.attributes || EXCLUDED.attributes,
            updated_at = now()
    """.replace("__ASSET_CLASS__", _asset_class_case("e.strategy_label"))
    result = cast(CursorResult[Any], await db.execute(text(_sql)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.sec_etfs", upserted=count)
    return {"upserted": count}


# ── Phase 2: SEC Mutual Fund Series (canonical class) ────────────────


async def _sync_sec_mf_series(db: AsyncSession) -> dict[str, Any]:
    """Upsert SEC mutual fund series — one per series_id, canonical share class."""
    _sql = """
        WITH per_series AS (
            SELECT DISTINCT ON (fc.series_id)
                fc.series_id,
                fc.series_name,
                fc.ticker,
                fc.class_name AS canonical_class,
                fc.expense_ratio_pct,
                fc.net_assets,
                rf.monthly_avg_net_assets,
                fc.cik,
                rf.strategy_label,
                rf.fund_type,
                rf.crd_number,
                rf.inception_date,
                m.firm_name AS manager_name
            FROM sec_fund_classes fc
            LEFT JOIN sec_registered_funds rf ON rf.cik = fc.cik
            LEFT JOIN sec_managers m ON m.crd_number = rf.crd_number
            WHERE fc.ticker IS NOT NULL
              AND fc.ticker NOT LIKE '%%XX'
              AND NOT EXISTS (
                  SELECT 1 FROM instruments_universe iu
                  WHERE iu.isin = fc.series_id OR iu.ticker = fc.ticker
              )
            ORDER BY fc.series_id, fc.expense_ratio_pct ASC NULLS LAST
        ),
        canonical AS (
            SELECT DISTINCT ON (ticker) * FROM per_series
            ORDER BY ticker, expense_ratio_pct ASC NULLS LAST
        )
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, isin, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            c.series_name,
            c.series_id,
            c.ticker,
            __ASSET_CLASS__,
            'north_america',
            'USD',
            true,
            jsonb_build_object(
                'series_id', c.series_id,
                'sec_cik', c.cik,
                'sec_crd', c.crd_number,
                'fund_subtype', c.fund_type,
                'sec_universe', 'registered_us',
                'strategy_label', c.strategy_label,
                'canonical_class', c.canonical_class,
                'expense_ratio_pct', c.expense_ratio_pct,
                'aum_usd', COALESCE(c.net_assets, c.monthly_avg_net_assets),
                'manager_name', COALESCE(c.manager_name, c.series_name),
                'inception_date', c.inception_date,
                'source', 'universe_sync'
            )
        FROM canonical c
        ON CONFLICT (ticker) DO UPDATE SET
            name = EXCLUDED.name,
            attributes = instruments_universe.attributes || EXCLUDED.attributes,
            updated_at = now()
    """.replace("__ASSET_CLASS__", _asset_class_case("c.strategy_label"))
    result = cast(CursorResult[Any], await db.execute(text(_sql)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.sec_mf_series", upserted=count)
    return {"upserted": count}


# ── Phase 3: SEC Registered Funds with direct ticker ─────────────────


async def _sync_sec_registered(db: AsyncSession) -> dict[str, Any]:
    """Upsert SEC registered funds that have a direct ticker (supplements Phase 2)."""
    _sql = """
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, isin, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            rf.fund_name,
            rf.cik,
            rf.ticker,
            __ASSET_CLASS__,
            'north_america',
            'USD',
            true,
            jsonb_build_object(
                'sec_cik', rf.cik,
                'sec_crd', rf.crd_number,
                'fund_subtype', rf.fund_type,
                'sec_universe', 'registered_us',
                'strategy_label', rf.strategy_label,
                'is_index', rf.is_index,
                'is_target_date', rf.is_target_date,
                'is_fund_of_fund', rf.is_fund_of_fund,
                'aum_usd', NULL,
                'manager_name', rf.fund_name,
                'inception_date', rf.inception_date,
                'source', 'universe_sync'
            )
        FROM sec_registered_funds rf
        WHERE rf.ticker IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM instruments_universe iu WHERE iu.ticker = rf.ticker
          )
        ON CONFLICT (ticker) DO NOTHING
    """.replace("__ASSET_CLASS__", _asset_class_case("rf.strategy_label"))
    result = cast(CursorResult[Any], await db.execute(text(_sql)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.sec_registered", upserted=count)
    return {"upserted": count}


# ── Phase 3b: SEC BDCs (ticker resolved via cusip_ticker_map) ────────


async def _sync_sec_bdcs(db: AsyncSession) -> dict[str, Any]:
    """Upsert SEC BDCs with resolved tickers into instruments_universe."""
    result = cast(CursorResult[Any], await db.execute(text("""
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, isin, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            b.fund_name,
            b.series_id,
            b.ticker,
            'alternatives',
            'north_america',
            'USD',
            true,
            jsonb_build_object(
                'series_id', b.series_id,
                'sec_cik', b.cik,
                'fund_subtype', 'bdc',
                'sec_universe', 'bdc',
                'strategy_label', COALESCE(b.strategy_label, 'Private Credit'),
                'is_externally_managed', b.is_externally_managed,
                'investment_focus', b.investment_focus,
                'expense_ratio_pct', b.net_operating_expenses,
                'aum_usd', b.monthly_avg_net_assets,
                'manager_name', b.fund_name,
                'inception_date', b.inception_date,
                'source', 'universe_sync'
            )
        FROM sec_bdcs b
        WHERE b.ticker IS NOT NULL
        ON CONFLICT (ticker) DO UPDATE SET
            name = EXCLUDED.name,
            attributes = instruments_universe.attributes || EXCLUDED.attributes,
            updated_at = now()
    """)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.sec_bdcs", upserted=count)
    return {"upserted": count}


# ── Phase 4: ESMA UCITS ──────────────────────────────────────────────


async def _sync_esma_funds(db: AsyncSession) -> dict[str, Any]:
    """Upsert ESMA UCITS funds with resolved yahoo_ticker."""
    _sql = """
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, isin, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            ef.fund_name,
            ef.isin,
            ef.yahoo_ticker,
            __ASSET_CLASS__,
            CASE ef.domicile
                WHEN 'IE' THEN 'dm_europe' WHEN 'LU' THEN 'dm_europe'
                WHEN 'DE' THEN 'dm_europe' WHEN 'FR' THEN 'dm_europe'
                WHEN 'NL' THEN 'dm_europe' WHEN 'GB' THEN 'dm_europe'
                WHEN 'CH' THEN 'dm_europe' WHEN 'SE' THEN 'dm_europe'
                WHEN 'DK' THEN 'dm_europe' WHEN 'NO' THEN 'dm_europe'
                WHEN 'ES' THEN 'dm_europe' WHEN 'IT' THEN 'dm_europe'
                WHEN 'PT' THEN 'dm_europe' WHEN 'AT' THEN 'dm_europe'
                WHEN 'BE' THEN 'dm_europe' WHEN 'FI' THEN 'dm_europe'
                WHEN 'MT' THEN 'dm_europe' WHEN 'CY' THEN 'dm_europe'
                WHEN 'LI' THEN 'dm_europe'
                ELSE COALESCE(ef.domicile, 'dm_europe')
            END,
            CASE ef.domicile
                WHEN 'GB' THEN 'GBP' WHEN 'CH' THEN 'CHF'
                WHEN 'SE' THEN 'SEK' WHEN 'DK' THEN 'DKK'
                WHEN 'NO' THEN 'NOK' WHEN 'LI' THEN 'CHF'
                ELSE 'EUR'
            END,
            true,
            jsonb_build_object(
                'isin', ef.isin,
                'fund_subtype', 'ucits',
                'strategy_label', ef.strategy_label,
                'domicile', ef.domicile,
                'esma_manager_id', ef.esma_manager_id,
                'aum_usd', NULL,
                'manager_name', COALESCE(
                    (SELECT em.company_name FROM esma_managers em
                     WHERE em.esma_id = ef.esma_manager_id LIMIT 1),
                    ef.fund_name
                ),
                'inception_date', NULL,
                'source', 'universe_sync'
            )
        FROM esma_funds ef
        WHERE ef.yahoo_ticker IS NOT NULL
        ON CONFLICT (ticker) DO UPDATE SET
            name = EXCLUDED.name,
            attributes = instruments_universe.attributes || EXCLUDED.attributes,
            updated_at = now()
    """.replace("__ASSET_CLASS__", _asset_class_case("ef.strategy_label"))
    result = cast(CursorResult[Any], await db.execute(text(_sql)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.esma_funds", upserted=count)
    return {"upserted": count}


# ── Post-sync: deactivate instruments without NAV ─────────────────────


async def _deactivate_no_nav(db: AsyncSession) -> dict[str, Any]:
    """Mark instruments without NAV data as inactive.

    Funds without NAV are not useful in catalog, screener, or analytics.
    Idempotent — if a ticker gains NAV later, next universe_sync re-inserts
    with is_active=true via ON CONFLICT UPDATE.
    """
    result = cast(CursorResult[Any], await db.execute(text("""
        UPDATE instruments_universe
        SET is_active = false, updated_at = now()
        WHERE is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM nav_timeseries nt
              WHERE nt.instrument_id = instruments_universe.instrument_id
          )
    """)))
    await db.commit()
    count = result.rowcount
    logger.info("universe_sync.deactivated_no_nav", count=count)
    return {"deactivated": count}
