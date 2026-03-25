"""
Seed tenant data — works for both dev and production.

Usage:
  # Dev (default UUID):
  .venv/Scripts/python.exe seed_dev_tenant.py

  # Production (Clerk org ID → deterministic UUID):
  .venv/Scripts/python.exe seed_dev_tenant.py --clerk-org org_3BRsmzBv2qhA9lBMzsUs3PnFndR

  # With workers:
  .venv/Scripts/python.exe seed_dev_tenant.py --clerk-org org_3BRsmzBv2qhA9lBMzsUs3PnFndR --run-workers --lookback 730

Seeds:
  1. instruments_universe — 16 ETF proxies (one per allocation block)
  2. funds_universe — same 16 instruments (legacy table for risk_calc/portfolio_eval workers)
  3. strategic_allocation — 3 profiles (conservative / moderate / growth)
  4. model_portfolios — 3 live profiles
  5. (optional) NAV ingestion, risk_calc, portfolio_eval via --run-workers
"""
import argparse
import asyncio
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import clerk_org_to_uuid
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.instrument import Instrument

DEV_ORG_ID = uuid.UUID("e28fc30c-9d6d-4b21-8e91-cad8696b44fa")
ORG_ID: uuid.UUID = DEV_ORG_ID  # overridden by --clerk-org
# Deterministic namespace for uuid5 — stable IDs across re-runs
_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _det_id(isin: str) -> uuid.UUID:
    """Deterministic UUID from ISIN — same ID every run."""
    return uuid.uuid5(_NS, isin)


# (block_id, instrument_type, name, isin, ticker, geography, asset_class, currency)
INSTRUMENTS = [
    ("na_equity_large",  "fund", "iShares S&P 500 ETF",              "IE00B5BMR087", "SPY", "north_america", "equity",       "USD"),
    ("na_equity_growth", "fund", "Invesco QQQ Trust",                 "US46090E1038", "QQQ", "north_america", "equity",       "USD"),
    ("na_equity_value",  "fund", "iShares Russell 1000 Value ETF",    "US4642876555", "IWD", "north_america", "equity",       "USD"),
    ("na_equity_small",  "fund", "iShares Russell 2000 ETF",          "US4642876308", "IWM", "north_america", "equity",       "USD"),
    ("dm_europe_equity", "fund", "Vanguard FTSE Europe ETF",          "US9219438580", "VGK", "dm_europe",     "equity",       "EUR"),
    ("dm_asia_equity",   "fund", "iShares MSCI Japan ETF",            "US4642872265", "EWJ", "dm_asia",       "equity",       "JPY"),
    ("em_equity",        "fund", "iShares MSCI Emerging Markets ETF", "US4642872349", "EEM", "emerging",      "equity",       "USD"),
    ("fi_us_aggregate",  "fund", "iShares Core US Aggregate ETF",     "US4642876083", "AGG", "north_america", "fixed_income", "USD"),
    ("fi_us_treasury",   "fund", "iShares 7-10Y Treasury Bond ETF",   "US4642874659", "IEF", "north_america", "fixed_income", "USD"),
    ("fi_us_tips",       "fund", "iShares TIPS Bond ETF",             "US4642871762", "TIP", "north_america", "fixed_income", "USD"),
    ("fi_us_high_yield", "fund", "iShares iBoxx HY Corp Bond ETF",    "US4642885135", "HYG", "north_america", "fixed_income", "USD"),
    ("fi_em_debt",       "fund", "iShares JPM EM Bond ETF",           "US4642882819", "EMB", "emerging",      "fixed_income", "USD"),
    ("alt_real_estate",  "fund", "Vanguard Real Estate ETF",          "US9229085538", "VNQ", "north_america", "alternatives", "USD"),
    ("alt_commodities",  "fund", "iPath Bloomberg Commodity ETN",     "US06740C5560", "DJP", "global",        "alternatives", "USD"),
    ("alt_gold",         "fund", "SPDR Gold Shares",                  "US78463V1070", "GLD", "global",        "alternatives", "USD"),
    ("cash",             "fund", "iShares Short Treasury Bond ETF",   "US4642886265", "SHV", "north_america", "cash",         "USD"),
]

PROFILES = {
    "conservative": {
        "na_equity_large":  0.08, "na_equity_growth": 0.02, "na_equity_value":  0.04,
        "na_equity_small":  0.01, "dm_europe_equity": 0.03, "dm_asia_equity":   0.02,
        "em_equity":        0.02, "fi_us_aggregate":  0.25, "fi_us_treasury":   0.20,
        "fi_us_tips":       0.08, "fi_us_high_yield": 0.05, "fi_em_debt":       0.05,
        "alt_real_estate":  0.03, "alt_commodities":  0.03, "alt_gold":         0.05, "cash": 0.04,
    },
    "moderate": {
        "na_equity_large":  0.18, "na_equity_growth": 0.07, "na_equity_value":  0.07,
        "na_equity_small":  0.04, "dm_europe_equity": 0.07, "dm_asia_equity":   0.04,
        "em_equity":        0.05, "fi_us_aggregate":  0.15, "fi_us_treasury":   0.10,
        "fi_us_tips":       0.05, "fi_us_high_yield": 0.05, "fi_em_debt":       0.04,
        "alt_real_estate":  0.04, "alt_commodities":  0.02, "alt_gold":         0.02, "cash": 0.01,
    },
    "growth": {
        "na_equity_large":  0.28, "na_equity_growth": 0.12, "na_equity_value":  0.10,
        "na_equity_small":  0.07, "dm_europe_equity": 0.10, "dm_asia_equity":   0.06,
        "em_equity":        0.08, "fi_us_aggregate":  0.05, "fi_us_treasury":   0.03,
        "fi_us_tips":       0.02, "fi_us_high_yield": 0.03, "fi_em_debt":       0.03,
        "alt_real_estate":  0.01, "alt_commodities":  0.01, "alt_gold":         0.01, "cash": 0.00,
    },
}

MODEL_PORTFOLIOS = [
    {
        "id": uuid.uuid5(_NS, "model-conservative"),
        "profile": "conservative",
        "display_name": "Conservative Income",
        "description": "Capital preservation focus with emphasis on investment-grade bonds and minimal equity exposure.",
        "benchmark_composite": "40/60",
        "inception_date": date(2024, 1, 1),
        "backtest_start_date": date(2024, 1, 1),
        "inception_nav": 1000.0,
        "status": "live",
    },
    {
        "id": uuid.uuid5(_NS, "model-moderate"),
        "profile": "moderate",
        "display_name": "Balanced Growth",
        "description": "Balanced approach with diversified global equity and fixed income allocations.",
        "benchmark_composite": "60/40",
        "inception_date": date(2024, 1, 1),
        "backtest_start_date": date(2024, 1, 1),
        "inception_nav": 1000.0,
        "status": "live",
    },
    {
        "id": uuid.uuid5(_NS, "model-growth"),
        "profile": "growth",
        "display_name": "Aggressive Growth",
        "description": "Growth-oriented portfolio with high equity allocation and emerging market exposure.",
        "benchmark_composite": "80/20",
        "inception_date": date(2024, 1, 1),
        "backtest_start_date": date(2024, 1, 1),
        "inception_nav": 1000.0,
        "status": "live",
    },
]


async def seed():
    async with async_session_factory() as db:
        # Set RLS context so org-scoped tables are accessible
        await set_rls_context(db, ORG_ID)

        # ── 1. Upsert instruments_universe ────────────────────────────
        inst_rows = []
        for block_id, itype, name, isin, ticker, geo, asset_class, currency in INSTRUMENTS:
            inst_rows.append({
                "instrument_id":   _det_id(isin),
                "instrument_type": itype,
                "name":            name,
                "isin":            isin,
                "ticker":          ticker,
                "geography":       geo,
                "asset_class":     asset_class,
                "currency":        currency,
                "block_id":        block_id,
                "is_active":       True,
                "approval_status": "approved",
                "organization_id": ORG_ID,
                "attributes": {
                    "aum_usd": 1_000_000_000,
                    "manager_name": name.split(" ")[0],
                    "inception_date": "2020-01-01",
                },
            })

        stmt = pg_insert(Instrument).values(inst_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id"],
            set_={
                "ticker": stmt.excluded.ticker,
                "is_active": True,
                "name": stmt.excluded.name,
                "block_id": stmt.excluded.block_id,
            },
        )
        await db.execute(stmt)
        print(f"[instruments_universe] Upserted {len(inst_rows)} instruments")

        # ── 2. Upsert funds_universe (legacy table for risk_calc/portfolio_eval) ──
        # Uses the SAME deterministic UUIDs so nav_timeseries FK works for both
        for block_id, itype, name, isin, ticker, geo, asset_class, currency in INSTRUMENTS:
            fund_id = _det_id(isin)
            await db.execute(text("""
                INSERT INTO funds_universe (fund_id, organization_id, isin, ticker, name,
                    fund_type, geography, asset_class, block_id, currency, is_active, approval_status)
                VALUES (:fund_id, :org_id, :isin, :ticker, :name,
                    :fund_type, :geo, :asset_class, :block_id, :currency, true, 'approved')
                ON CONFLICT (fund_id) DO UPDATE SET
                    ticker = EXCLUDED.ticker, is_active = true, name = EXCLUDED.name,
                    block_id = EXCLUDED.block_id
            """), {
                "fund_id": fund_id, "org_id": ORG_ID, "isin": isin,
                "ticker": ticker, "name": name, "fund_type": itype,
                "geo": geo, "asset_class": asset_class,
                "block_id": block_id, "currency": currency,
            })
        print(f"[funds_universe] Upserted {len(INSTRUMENTS)} funds (legacy)")

        # ── 3. Upsert strategic_allocation ────────────────────────────
        # Delete existing for this org then re-insert (no unique index on profile+block+org)
        await db.execute(
            delete(StrategicAllocation)
            .where(StrategicAllocation.organization_id == ORG_ID)
        )
        alloc_rows = []
        effective = date(2024, 1, 1)
        for profile, weights in PROFILES.items():
            for block_id, weight in weights.items():
                alloc_rows.append({
                    "allocation_id":   uuid.uuid5(_NS, f"alloc-{profile}-{block_id}"),
                    "profile":         profile,
                    "block_id":        block_id,
                    "target_weight":   weight,
                    "min_weight":      max(0.0, weight - 0.05),
                    "max_weight":      min(1.0, weight + 0.05),
                    "effective_from":  effective,
                    "organization_id": ORG_ID,
                })

        stmt2 = pg_insert(StrategicAllocation).values(alloc_rows)
        stmt2 = stmt2.on_conflict_do_update(
            index_elements=["allocation_id"],
            set_={
                "target_weight": stmt2.excluded.target_weight,
                "min_weight": stmt2.excluded.min_weight,
                "max_weight": stmt2.excluded.max_weight,
                "effective_from": stmt2.excluded.effective_from,
            },
        )
        await db.execute(stmt2)
        print(f"[strategic_allocation] Upserted {len(alloc_rows)} rows across {len(PROFILES)} profiles")

        # ── 4. Upsert model_portfolios ────────────────────────────────
        for mp in MODEL_PORTFOLIOS:
            await db.execute(text("""
                INSERT INTO model_portfolios
                    (id, organization_id, profile, display_name, description,
                     benchmark_composite, inception_date, backtest_start_date,
                     inception_nav, status)
                VALUES (:id, :org_id, :profile, :display_name, :description,
                        :benchmark_composite, :inception_date, :backtest_start_date,
                        :inception_nav, :status)
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    status = EXCLUDED.status,
                    description = EXCLUDED.description
            """), {
                "id": mp["id"], "org_id": ORG_ID,
                "profile": mp["profile"], "display_name": mp["display_name"],
                "description": mp["description"],
                "benchmark_composite": mp["benchmark_composite"],
                "inception_date": mp["inception_date"],
                "backtest_start_date": mp["backtest_start_date"],
                "inception_nav": mp["inception_nav"],
                "status": mp["status"],
            })
        print(f"[model_portfolios] Upserted {len(MODEL_PORTFOLIOS)} live portfolios")

        await db.commit()
        print("\nSeed data committed successfully.")


async def run_workers(lookback_days: int = 730):
    """Run instrument_ingestion, risk_calc, and portfolio_eval sequentially."""
    print(f"\n{'='*60}")
    print(f"Running workers (lookback={lookback_days} days)...")
    print(f"{'='*60}")

    # ── Step 1: Instrument ingestion (needs db session) ──
    print("\n[1/3] Running instrument_ingestion...")
    from app.domains.wealth.workers.instrument_ingestion import run_instrument_ingestion

    async with async_session_factory() as db:
        await set_rls_context(db, ORG_ID)
        result = await run_instrument_ingestion(db, ORG_ID, lookback_days=lookback_days)
        print(f"  instruments_processed: {result['instruments_processed']}")
        print(f"  rows_upserted: {result['rows_upserted']}")
        if result["skipped_tickers"]:
            print(f"  skipped: {result['skipped_tickers']}")
        if result["errors"]:
            print(f"  errors: {result['errors']}")

    if result["rows_upserted"] == 0:
        print("\nERROR: No NAV data ingested. Cannot proceed with risk_calc.")
        return

    # ── Step 2: Risk calculation ──
    print("\n[2/3] Running risk_calc...")
    from app.domains.wealth.workers.risk_calc import run_risk_calc

    risk_result = await run_risk_calc(ORG_ID)
    total_computed = sum(v for v in risk_result.values() if isinstance(v, int))
    print(f"  funds computed: {total_computed}")

    # ── Step 3: Portfolio evaluation ──
    print("\n[3/3] Running portfolio_eval...")
    from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval

    eval_result = await run_portfolio_eval(ORG_ID)
    for profile, status in eval_result.items():
        print(f"  {profile}: {status}")


async def main(run_workers_flag: bool = False, lookback_days: int = 730):
    await seed()
    if run_workers_flag:
        await run_workers(lookback_days)
    else:
        print("\nNext steps:")
        print("  .venv/Scripts/python.exe seed_dev_tenant.py --run-workers --lookback 730")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed tenant data")
    parser.add_argument("--clerk-org", type=str, help="Clerk org ID (e.g. org_xxx) — derives deterministic UUID")
    parser.add_argument("--run-workers", action="store_true", help="Also run ingestion/risk/eval workers")
    parser.add_argument("--lookback", type=int, default=730, help="NAV lookback days (default: 730 = ~2yr)")
    args = parser.parse_args()

    if args.clerk_org:
        ORG_ID = clerk_org_to_uuid(args.clerk_org)
        print(f"Clerk org: {args.clerk_org}")
    print(f"Internal UUID: {ORG_ID}\n")

    asyncio.run(main(args.run_workers, args.lookback))
