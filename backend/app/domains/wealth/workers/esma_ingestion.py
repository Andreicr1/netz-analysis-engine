"""ESMA UCITS fund universe ingestion worker.

Usage:
    python -m app.domains.wealth.workers.esma_ingestion

Single-pass: iterates raw Solr pages once, parsing both fund AND manager
data from each document. Eliminates the two-pass approach that caused
manager names to remain as placeholders.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_023.
"""

import asyncio
import os
from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import EsmaFund as EsmaFundModel
from app.shared.models import EsmaIsinTickerMap
from app.shared.models import EsmaManager as EsmaManagerModel

logger = structlog.get_logger()
ESMA_LOCK_ID = 900_023
_BATCH_SIZE = 2000

async def run_esma_ingestion() -> dict:
    """Fetch UCITS fund universe from ESMA and upsert managers, funds, ticker map.

    Single-pass approach: iterates raw Solr pages once, extracting both
    fund and manager data from each document. Avoids placeholder names.
    """
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({ESMA_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("ESMA ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            from data_providers.esma.models import EsmaFund as EsmaFundDC
            from data_providers.esma.models import EsmaManager as EsmaManagerDC
            from data_providers.esma.register_service import (
                RegisterService,
                _parse_fund_doc,
                parse_manager_from_doc,
            )
            from data_providers.esma.ticker_resolver import TickerResolver

            now = datetime.now(UTC)

            # ── Single pass: extract funds + managers from raw Solr docs ──
            funds_dc: list[EsmaFundDC] = []
            managers_map: dict[str, EsmaManagerDC] = {}
            fund_counts: dict[str, int] = {}

            async with RegisterService() as svc:
                start = 0
                total: int | None = None

                while True:
                    try:
                        data = await svc._fetch_page(start=start)
                    except Exception as exc:
                        logger.error("esma_ingestion.page_failed", start=start, error=str(exc))
                        break

                    response = data.get("response", {})
                    if total is None:
                        total = int(response.get("numFound", 0))
                        logger.info("esma_ingestion.total", total=total)

                    docs = response.get("docs", [])
                    if not docs:
                        break

                    for doc in docs:
                        # Parse fund
                        fund = _parse_fund_doc(doc)
                        if fund is not None:
                            funds_dc.append(fund)
                            mid = fund.esma_manager_id
                            fund_counts[mid] = fund_counts.get(mid, 0) + 1

                        # Parse manager from same doc (has company name, LEI, country)
                        mgr = parse_manager_from_doc(doc)
                        if mgr and mgr.esma_id not in managers_map:
                            managers_map[mgr.esma_id] = mgr

                    start += 1000
                    if total is not None and start >= total:
                        break

            # Apply fund counts to managers
            managers_list = [
                EsmaManagerDC(
                    esma_id=m.esma_id,
                    lei=m.lei,
                    company_name=m.company_name,
                    country=m.country,
                    authorization_status=m.authorization_status,
                    fund_count=fund_counts.get(m.esma_id, 0),
                )
                for m in managers_map.values()
            ]

            logger.info(
                "esma_ingestion.parsed",
                funds=len(funds_dc),
                managers=len(managers_list),
            )

            # ── Phase 2: Upsert managers — commit per batch ───────────
            # Each batch in its own transaction to prevent cascade abort
            managers_upserted = 0
            for i in range(0, len(managers_list), _BATCH_SIZE):
                batch = managers_list[i : i + _BATCH_SIZE]
                values = [
                    {
                        "esma_id": m.esma_id,
                        "lei": m.lei,
                        "company_name": m.company_name,
                        "country": m.country,
                        "authorization_status": m.authorization_status,
                        "fund_count": m.fund_count,
                        "data_fetched_at": now,
                    }
                    for m in batch
                ]
                try:
                    stmt = pg_insert(EsmaManagerModel).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["esma_id"],
                        set_={
                            "lei": stmt.excluded.lei,
                            "company_name": stmt.excluded.company_name,
                            "country": stmt.excluded.country,
                            "authorization_status": stmt.excluded.authorization_status,
                            "fund_count": stmt.excluded.fund_count,
                            "data_fetched_at": stmt.excluded.data_fetched_at,
                        },
                    )
                    await db.execute(stmt)
                    await db.commit()
                    managers_upserted += len(batch)
                except Exception as exc:
                    await db.rollback()
                    logger.warning("esma_ingestion.managers_batch_failed", batch_start=i, error=str(exc))
            logger.info("esma_ingestion.managers_upserted", count=managers_upserted)

            # ── Phase 3: Upsert funds — commit per batch ─────────────
            funds_upserted = 0
            for i in range(0, len(funds_dc), _BATCH_SIZE):
                batch = funds_dc[i : i + _BATCH_SIZE]
                values = [
                    {
                        "isin": f.isin,
                        "fund_name": f.fund_name,
                        "esma_manager_id": f.esma_manager_id,
                        "domicile": f.domicile,
                        "fund_type": f.fund_type,
                        "host_member_states": f.host_member_states or [],
                        "data_fetched_at": now,
                    }
                    for f in batch
                ]
                try:
                    stmt = pg_insert(EsmaFundModel).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["isin"],
                        set_={
                            "fund_name": stmt.excluded.fund_name,
                            "esma_manager_id": stmt.excluded.esma_manager_id,
                            "domicile": stmt.excluded.domicile,
                            "fund_type": stmt.excluded.fund_type,
                            "host_member_states": stmt.excluded.host_member_states,
                            "data_fetched_at": stmt.excluded.data_fetched_at,
                        },
                    )
                    await db.execute(stmt)
                    await db.commit()
                    funds_upserted += len(batch)
                except Exception as exc:
                    await db.rollback()
                    logger.warning("esma_ingestion.funds_batch_failed", batch_start=i, error=str(exc))
            logger.info("esma_ingestion.funds_upserted", count=funds_upserted)

            # ── Phase 4: Ticker resolution via OpenFIGI ───────────────
            isins = [f.isin for f in funds_dc]
            ticker_count = 0
            errors = 0

            api_key = os.environ.get("OPENFIGI_API_KEY")
            async with TickerResolver(api_key=api_key) as resolver:
                try:
                    resolutions = await resolver.resolve_all(isins)
                except Exception as exc:
                    logger.warning("esma_ingestion.ticker_resolution_failed", error=str(exc))
                    resolutions = []
                    errors += 1

            for i in range(0, len(resolutions), _BATCH_SIZE):
                batch = resolutions[i : i + _BATCH_SIZE]
                values = [
                    {
                        "isin": r.isin,
                        "yahoo_ticker": r.yahoo_ticker,
                        "exchange": r.exchange,
                        "resolved_via": r.resolved_via,
                        "is_tradeable": r.is_tradeable,
                        "last_verified_at": now,
                    }
                    for r in batch
                ]
                stmt = pg_insert(EsmaIsinTickerMap).values(values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["isin"],
                    set_={
                        "yahoo_ticker": stmt.excluded.yahoo_ticker,
                        "exchange": stmt.excluded.exchange,
                        "resolved_via": stmt.excluded.resolved_via,
                        "is_tradeable": stmt.excluded.is_tradeable,
                        "last_verified_at": stmt.excluded.last_verified_at,
                    },
                )
                await db.execute(stmt)
            await db.commit()
            ticker_count = sum(1 for r in resolutions if r.is_tradeable)

            # Update yahoo_ticker on esma_funds for resolved ISINs
            resolved_map = {
                r.isin: r.yahoo_ticker
                for r in resolutions
                if r.yahoo_ticker
            }
            if resolved_map:
                for isin, ticker in resolved_map.items():
                    await db.execute(
                        text(
                            "UPDATE esma_funds SET yahoo_ticker = :ticker, "
                            "ticker_resolved_at = :now WHERE isin = :isin",
                        ),
                        {"ticker": ticker, "now": now, "isin": isin},
                    )
                await db.commit()

            summary = {
                "status": "completed",
                "managers": len(managers_list),
                "funds": len(funds_dc),
                "tickers_resolved": ticker_count,
                "errors": errors,
            }

            # Refresh Materialized Views for screener and global search
            from app.domains.wealth.services.view_refresh import refresh_screener_views
            await refresh_screener_views(db)

            logger.info("esma_ingestion.complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({ESMA_LOCK_ID})"),
            )


if __name__ == "__main__":
    asyncio.run(run_esma_ingestion())
