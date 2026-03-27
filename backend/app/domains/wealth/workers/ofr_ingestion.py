"""OFR hedge fund data ingestion worker — leverage, AUM, repo, stress scenarios.

Usage:
    python -m app.domains.wealth.workers.ofr_ingestion

Fetches data from the OFR Hedge Fund Monitor API via OFRHedgeFundService
and upserts into the ofr_hedge_fund_data hypertable.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_012.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import OfrHedgeFundData
from quant_engine.ofr_hedge_fund_service import OFRHedgeFundService

logger = structlog.get_logger()
OFR_LOCK_ID = 900_012


def _safe_decimal(value: float | None) -> Decimal | None:
    """Convert float to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def run_ofr_ingestion(lookback_years: int = 5) -> dict:
    """Fetch OFR hedge fund data and upsert to ofr_hedge_fund_data hypertable."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({OFR_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("OFR ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            today = date.today()
            start = (today - timedelta(days=lookback_years * 365)).isoformat()

            rows: list[dict] = []

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                service = OFRHedgeFundService(http_client)

                # ── Leverage by size cohort ────────────────────────
                try:
                    leverage = await service.fetch_industry_leverage(start)
                    for snap in leverage:
                        try:
                            obs_date = date.fromisoformat(snap.date)
                        except (ValueError, TypeError):
                            continue
                        for field, suffix in (
                            ("gav_weighted_mean", "WEIGHTED_MEAN"),
                            ("p5", "P5"),
                            ("p50", "P50"),
                            ("p95", "P95"),
                        ):
                            val = _safe_decimal(getattr(snap, field))
                            if val is not None:
                                rows.append({
                                    "obs_date": obs_date,
                                    "series_id": f"OFR_LEVERAGE_{suffix}",
                                    "value": val,
                                    "source": "ofr_api",
                                })
                except Exception as e:
                    logger.warning("ofr_leverage_fetch_failed", error=str(e))

                # ── Industry size (GAV, NAV, count) ────────────────
                try:
                    sizes = await service.fetch_industry_size(start)
                    for size_snap in sizes:
                        try:
                            obs_date = date.fromisoformat(size_snap.date)
                        except (ValueError, TypeError):
                            continue
                        for field, sid in (
                            ("gav_sum", "OFR_INDUSTRY_GAV"),
                            ("nav_sum", "OFR_INDUSTRY_NAV"),
                            ("fund_count", "OFR_INDUSTRY_COUNT"),
                        ):
                            val = _safe_decimal(getattr(size_snap, field))
                            if val is not None:
                                rows.append({
                                    "obs_date": obs_date,
                                    "series_id": sid,
                                    "value": val,
                                    "source": "ofr_api",
                                })
                except Exception as e:
                    logger.warning("ofr_industry_size_fetch_failed", error=str(e))

                # ── Strategy breakdown ─────────────────────────────
                try:
                    strategies = await service.fetch_strategy_breakdown(start)
                    for strat_snap in strategies:
                        val = _safe_decimal(strat_snap.gav_sum)
                        if val is None:
                            continue
                        try:
                            obs_date = date.fromisoformat(strat_snap.date)
                        except (ValueError, TypeError):
                            continue
                        series_id = f"OFR_STRATEGY_{strat_snap.strategy.upper()}_AUM"
                        rows.append({
                            "obs_date": obs_date,
                            "series_id": series_id,
                            "value": val,
                            "source": "ofr_api",
                        })
                except Exception as e:
                    logger.warning("ofr_strategy_fetch_failed", error=str(e))

                # ── Counterparty concentration ─────────────────────
                try:
                    counterparty = await service.fetch_counterparty_concentration(start)
                    for cp_snap in counterparty:
                        val = _safe_decimal(cp_snap.value)
                        if val is None:
                            continue
                        try:
                            obs_date = date.fromisoformat(cp_snap.date)
                        except (ValueError, TypeError):
                            continue
                        # Mnemonic like "SCOOS-NET_LENDERCOMPET" → "OFR_SCOOS_NET_LENDERCOMPET"
                        series_id = f"OFR_{cp_snap.mnemonic.replace('-', '_')}"
                        if len(series_id) > 80:
                            series_id = series_id[:80]
                        rows.append({
                            "obs_date": obs_date,
                            "series_id": series_id,
                            "value": val,
                            "source": "ofr_api",
                        })
                except Exception as e:
                    logger.warning("ofr_counterparty_fetch_failed", error=str(e))

                # ── FICC repo volumes ──────────────────────────────
                try:
                    repo_list = await service.fetch_repo_volumes(start)
                    for repo_snap in repo_list:
                        val = _safe_decimal(repo_snap.volume)
                        if val is None:
                            continue
                        try:
                            obs_date = date.fromisoformat(repo_snap.date)
                        except (ValueError, TypeError):
                            continue
                        rows.append({
                            "obs_date": obs_date,
                            "series_id": "OFR_REPO_VOLUME",
                            "value": val,
                            "source": "ofr_api",
                        })
                except Exception as e:
                    logger.warning("ofr_repo_fetch_failed", error=str(e))

                # ── Risk scenarios (CDS stress) ────────────────────
                try:
                    scenarios = await service.fetch_risk_scenarios(start)
                    for risk_snap in scenarios:
                        val = _safe_decimal(risk_snap.value)
                        if val is None:
                            continue
                        try:
                            obs_date = date.fromisoformat(risk_snap.date)
                        except (ValueError, TypeError):
                            continue
                        # scenario like "cds_down_250bps_p5" → "OFR_CDS_DOWN_250BPS_P5"
                        series_id = f"OFR_{risk_snap.scenario.upper()}"
                        rows.append({
                            "obs_date": obs_date,
                            "series_id": series_id,
                            "value": val,
                            "source": "ofr_api",
                        })
                except Exception as e:
                    logger.warning("ofr_risk_scenarios_fetch_failed", error=str(e))

            # Deduplicate by (obs_date, series_id) — keep last value
            if rows:
                seen: dict[tuple, dict] = {}
                for r in rows:
                    seen[(r["obs_date"], r["series_id"])] = r
                rows = list(seen.values())

                chunk_size = 2000
                for i in range(0, len(rows), chunk_size):
                    chunk = rows[i:i + chunk_size]
                    stmt = pg_insert(OfrHedgeFundData).values(chunk)
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

            logger.info("OFR ingestion complete", rows_upserted=len(rows))
            return {"status": "completed", "rows": len(rows)}

        except Exception:
            await db.rollback()
            raise
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({OFR_LOCK_ID})"),
                )
            except Exception:
                pass  # lock auto-released on session close


if __name__ == "__main__":
    asyncio.run(run_ofr_ingestion())
