"""Backfill strategy_label across all three fund tables.

Applies keyword classifiers to:
  - sec_manager_funds (private): 3-layer (name → hedge refinement → brochure)
  - esma_funds (UCITS): name keywords (asset class + geography + ESG)
  - sec_registered_funds (mutual/ETF): name keywords

Idempotent: re-running overwrites all strategy_label values.

Usage:
    python -m scripts.backfill_strategy_label          # via app DB engine
    python -m scripts.backfill_strategy_label --dsn ... # direct connection
"""
from __future__ import annotations

import argparse
import asyncio
import time

import structlog

logger = structlog.get_logger()

# ── Layer 1: Fund name → strategy_label (all fund types) ────────

_LAYER1_SQL = """
UPDATE sec_manager_funds SET strategy_label = CASE
    -- ── Private Credit (most specific first) ──
    WHEN fund_name ~* '(direct lend|senior lend|private lend|private credit|private debt)' THEN 'Private Credit'
    WHEN fund_name ~* '(mezzanine|mezz\\b|subordinat)' THEN 'Private Credit'
    WHEN fund_name ~* '(distress|turnaround|restructur|special.?situation)' THEN 'Distressed / Special Situations'

    -- ── Credit (broader) ──
    WHEN fund_name ~* '(credit|loan|lending|CLO\\b|leveraged.?finance)' AND fund_type != 'Hedge Fund' THEN 'Private Credit'
    WHEN fund_name ~* '(credit|loan|lending)' AND fund_type = 'Hedge Fund' THEN 'Credit Hedge'

    -- ── Structured / Securitized ──
    WHEN fund_name ~* '(CLO\\b|securitiz|ABS\\b|MBS\\b|CMBS|RMBS|collateral.?loan)' THEN 'Structured Credit'

    -- ── Real Estate (override if fund_type is Other) ──
    WHEN fund_name ~* '(real estate|property|propert|realty|REIT|housing|residential|commercial.?mortgage)' THEN 'Real Estate'

    -- ── Infrastructure / Energy ──
    WHEN fund_name ~* '(infrastructure|infra\\b)' THEN 'Infrastructure'
    WHEN fund_name ~* '(energy|power|renewable|solar|wind|utility|oil|gas|midstream)' THEN 'Energy'
    WHEN fund_name ~* '(timber|natural resource|agriculture|farmland|mining|water)' THEN 'Natural Resources'

    -- ── PE substrategy ──
    WHEN fund_name ~* '(buyout|buy.?out|acquisition|LBO)' THEN 'Buyout'
    WHEN fund_name ~* '(growth|expansion)' AND fund_type IN ('Private Equity Fund', 'Venture Capital Fund') THEN 'Growth Equity'
    WHEN fund_name ~* '(secondar|co.?invest|coinvest)' AND fund_type = 'Private Equity Fund' THEN 'Secondaries / Co-Invest'
    WHEN fund_name ~* '(co.?invest|coinvest)' THEN 'Co-Investment'
    WHEN fund_name ~* '(secondar)' THEN 'Secondaries'

    -- ── Venture substrategy ──
    WHEN fund_name ~* '(seed|early.?stage|pre.?seed|angel)' AND fund_type = 'Venture Capital Fund' THEN 'Early-Stage Venture'
    WHEN fund_name ~* '(late.?stage|growth)' AND fund_type = 'Venture Capital Fund' THEN 'Late-Stage Venture'
    WHEN fund_type = 'Venture Capital Fund' THEN 'Venture Capital'

    -- ── Hedge substrategy ──
    WHEN fund_name ~* '(multi.?strat|diversified.?strat)' THEN 'Multi-Strategy'
    WHEN fund_name ~* '(macro|global.?trading)' THEN 'Global Macro'
    WHEN fund_name ~* '(long.?short|long/short|equity.?hedge|equity.?master)' THEN 'Long/Short Equity'
    WHEN fund_name ~* '(arbitrage|relative.?value|market.?neutral)' THEN 'Relative Value'
    WHEN fund_name ~* '(event.?driven|activist|merger|merger.?arb)' THEN 'Event-Driven'
    WHEN fund_name ~* '(quant|systematic|algorithm|stat.?arb)' THEN 'Quantitative'
    WHEN fund_name ~* '(fixed.?income|rates|rate.?trading|bond|interest.?rate)' AND fund_type = 'Hedge Fund' THEN 'Fixed Income Hedge'

    -- ── Sector-focused ──
    WHEN fund_name ~* '(health|biotech|life.?science|pharma|medical)' THEN 'Healthcare'
    WHEN fund_name ~* '(tech|digital|software|cyber|data|AI\\b|cloud|SaaS)' THEN 'Technology'
    WHEN fund_name ~* '(consumer|retail|food|beverage)' THEN 'Consumer'
    WHEN fund_name ~* '(financial|fintech|insurance|banking)' THEN 'Financial Services'

    -- ── Impact / ESG ──
    WHEN fund_name ~* '(impact|ESG|sustainable|social|green|climate)' THEN 'Impact / ESG'

    -- ── Remaining: fall back to fund_type as label ──
    WHEN fund_type = 'Hedge Fund' THEN 'Hedge Fund'
    WHEN fund_type = 'Private Equity Fund' THEN 'Private Equity'
    WHEN fund_type = 'Real Estate Fund' THEN 'Real Estate'
    WHEN fund_type = 'Securitized Asset Fund' THEN 'Structured Credit'
    WHEN fund_type = 'Liquidity Fund' THEN 'Liquidity'
    WHEN fund_type = 'Other Private Fund' THEN 'Other'

    ELSE NULL
END;
"""

# ── Layer 2: Hedge fund sub-strategy refinement ─────────────────

_LAYER2_SQL = """
UPDATE sec_manager_funds SET strategy_label = CASE
    WHEN fund_name ~* '(equity|equities|stock|long.?only|all.?cap|small.?cap|large.?cap|mid.?cap|value.?fund|deep.?value)'
        AND fund_name !~* '(private equity|real estate)' THEN 'Long/Short Equity'
    WHEN fund_name ~* '(futures|managed.?future|trading|CTA\\b|commodit|systematic.?trad)' THEN 'CTA / Managed Futures'
    WHEN fund_name ~* '(convertible)' THEN 'Convertible Arbitrage'
    WHEN fund_name ~* '(volatility|vol\\b|options|dispersion)' THEN 'Volatility'
    WHEN fund_name ~* '(activist|engagement)' THEN 'Event-Driven'
    WHEN fund_name ~* '(mortgage|MSR|CMBS|RMBS)' THEN 'Structured Credit'
    WHEN fund_name ~* '(income|yield|dividend)' AND fund_name !~* '(fixed income)' THEN 'Income'
    WHEN fund_name ~* '(composite|diversified|balanced|multi.?asset|allocation)' THEN 'Multi-Strategy'
    WHEN fund_name ~* '(alpha|absolute.?return|total.?return)' THEN 'Absolute Return'
    ELSE strategy_label
END
WHERE fund_type = 'Hedge Fund' AND strategy_label = 'Hedge Fund';
"""

# ── Layer 3: Brochure content enrichment ────────────────────────

_LAYER3_SQL = """
WITH brochure_strategy AS (
    SELECT b.crd_number,
        CASE
            WHEN string_agg(b.content, ' ') ~* '(multi.?strategy|multi.?manager|pod.?based|diversified.?strat|portfolio manager)' THEN 'Multi-Strategy'
            WHEN string_agg(b.content, ' ') ~* '(long.?short|long/short|equity.?hedge|short.?sell)' THEN 'Long/Short Equity'
            WHEN string_agg(b.content, ' ') ~* '(global.?macro|macro.?trading|macro.?strateg)' THEN 'Global Macro'
            WHEN string_agg(b.content, ' ') ~* '(event.?driven|activist|merger.?arb|special.?situation)' THEN 'Event-Driven'
            WHEN string_agg(b.content, ' ') ~* '(quantitative|systematic|algorithm|statistical|machine.?learn|factor.?model)' THEN 'Quantitative'
            WHEN string_agg(b.content, ' ') ~* '(relative.?value|arbitrage|market.?neutral|pair.?trading)' THEN 'Relative Value'
            WHEN string_agg(b.content, ' ') ~* '(credit|loan|lend|debt|fixed.?income|bond)' THEN 'Credit Hedge'
            WHEN string_agg(b.content, ' ') ~* '(futures|CTA|managed.?future|commodit|trend.?follow)' THEN 'CTA / Managed Futures'
            WHEN string_agg(b.content, ' ') ~* '(convertible)' THEN 'Convertible Arbitrage'
            WHEN string_agg(b.content, ' ') ~* '(volatility|option|dispersion)' THEN 'Volatility'
            WHEN string_agg(b.content, ' ') ~* '(distress|turnaround|restructur)' THEN 'Distressed / Special Situations'
            ELSE NULL
        END as detected
    FROM sec_manager_brochure_text b
    WHERE b.section IN ('investment_philosophy', 'advisory_business', 'methods_of_analysis')
      AND b.crd_number IN (
          SELECT DISTINCT crd_number FROM sec_manager_funds
          WHERE fund_type = 'Hedge Fund' AND strategy_label = 'Hedge Fund'
      )
    GROUP BY b.crd_number
)
UPDATE sec_manager_funds f
SET strategy_label = bs.detected
FROM brochure_strategy bs
WHERE f.crd_number = bs.crd_number
  AND f.fund_type = 'Hedge Fund'
  AND f.strategy_label = 'Hedge Fund'
  AND bs.detected IS NOT NULL;
"""


async def _run_with_engine() -> None:
    """Execute via app's async engine (uses DATABASE_URL from .env)."""
    from sqlalchemy import text

    from app.core.db.engine import async_session_factory

    async with async_session_factory() as db, db.begin():
        t0 = time.time()

        r1 = await db.execute(text(_LAYER1_SQL))
        logger.info("layer1_fund_name_keywords", rows=r1.rowcount, elapsed=f"{time.time()-t0:.1f}s")

        r2 = await db.execute(text(_LAYER2_SQL))
        logger.info("layer2_hedge_refinement", rows=r2.rowcount, elapsed=f"{time.time()-t0:.1f}s")

        r3 = await db.execute(text(_LAYER3_SQL))
        logger.info("layer3_brochure_enrichment", rows=r3.rowcount, elapsed=f"{time.time()-t0:.1f}s")

        # Summary
        result = await db.execute(text(
            "SELECT strategy_label, COUNT(*) as cnt "
            "FROM sec_manager_funds GROUP BY strategy_label ORDER BY cnt DESC"
        ))
        logger.info("strategy_label_distribution")
        for row in result.fetchall():
            logger.info("  strategy", label=row[0], count=row[1])


async def _run_with_dsn(dsn: str) -> None:
    """Execute via direct asyncpg connection."""
    import asyncpg

    conn = await asyncpg.connect(dsn, ssl="require")
    t0 = time.time()

    try:
        r1 = await conn.execute(_LAYER1_SQL)
        count1 = int(r1.split()[-1]) if r1 else 0
        logger.info("layer1_fund_name_keywords", rows=count1, elapsed=f"{time.time()-t0:.1f}s")

        r2 = await conn.execute(_LAYER2_SQL)
        count2 = int(r2.split()[-1]) if r2 else 0
        logger.info("layer2_hedge_refinement", rows=count2, elapsed=f"{time.time()-t0:.1f}s")

        r3 = await conn.execute(_LAYER3_SQL)
        count3 = int(r3.split()[-1]) if r3 else 0
        logger.info("layer3_brochure_enrichment", rows=count3, elapsed=f"{time.time()-t0:.1f}s")

        rows = await conn.fetch(
            "SELECT strategy_label, COUNT(*) as cnt "
            "FROM sec_manager_funds GROUP BY strategy_label ORDER BY cnt DESC"
        )
        logger.info("strategy_label_distribution")
        for row in rows:
            logger.info("  strategy", label=row["strategy_label"], count=row["cnt"])
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill strategy_label via keyword classifier")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN (asyncpg format)")
    args = parser.parse_args()

    if args.dsn:
        asyncio.run(_run_with_dsn(args.dsn))
    else:
        asyncio.run(_run_with_engine())


if __name__ == "__main__":
    main()
