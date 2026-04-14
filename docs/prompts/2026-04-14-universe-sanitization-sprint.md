# Universe Sanitization Sprint — Filter Non-Institutional Vehicles

**Date:** 2026-04-14
**Branch:** `feat/universe-sanitization`
**Sessions:** 2 (Session A: Migration + sanitization worker, Session B: Downstream consumers + report)
**Priority:** CRITICAL — blocks Session B (apply gate) and Round 2 classifier patches
**Depends on:** PR #169 merged (classifier patches round 1)

---

## Context

The fund universe contains 62,728 rows in `sec_manager_funds`, 4,617 in `sec_registered_funds`, and 10,436 in `esma_funds`. Empirical analysis shows these counts include entities that are NOT appropriate for an institutional wealth management engine:

- **Retirement vehicles** (401k, 403b, IRA, ERISA, ESOP, pension plans)
- **Collective Investment Trusts** (CIT, bank-sponsored, retirement-focused)
- **Education plans** (529, Coverdell)
- **Insurance-wrapped products** (stable value, GICs, guaranteed income)
- **SMA/wrap programs** (separately managed accounts disguised as "funds")
- **Small retail-adviser-sponsored funds** (advisers with <$3B GAV or retail-heavy client base)
- **Duplicate multi-adviser filings** (same private fund reported by primary + sub-adviser)

Classifying these funds pollutes:
1. **Peer groups** — institutional funds compared against retirement vehicles
2. **Scoring percentiles** — inflated/deflated by non-comparable entities
3. **Candidate screener** — proposes unsuitable vehicles to IC
4. **Allocation blocks** — mis-routed by incorrect classification
5. **DD report context** — LLM receives retail context for institutional analysis

Classification fixes (Round 2) and apply gate (Session B) must wait for a clean universe.

---

## OBJECTIVE

Add `is_institutional` boolean flag to 6 fund tables + `instruments_universe`. Compute the flag via a new sanitization worker (lock `900_063`) using layered exclusion rules. Update downstream consumers to respect the flag. Produce an audit report of exclusions.

**Targets (estimated post-sanitization):**

| Table | Current | Expected after filter | Exclusions |
|---|---|---|---|
| sec_manager_funds | 62,728 | ~40,000 | ~22k (retirement, CIT, small-RIA, duplicates) |
| sec_registered_funds | 4,617 | ~3,500 | ~1.1k (target-date retirement, non-institutional share) |
| sec_etfs | 985 | ~950 | ~35 (target-date ETFs, exotic leveraged retail) |
| sec_bdcs | 196 | 196 | 0 (all public BDCs are institutional-appropriate) |
| sec_money_market_funds | 373 | ~320 | ~53 (retail-only MMFs) |
| esma_funds | 10,436 | ~8,000 | ~2.4k (retirement-focused UCITS, sub-scale) |
| **TOTAL** | **79,335** | **~53,000** | **~26k excluded (33%)** |

---

## CONSTRAINTS

- **Stored column, not computed view.** Performance + audit trail.
- **Default TRUE on migration.** Existing data stays institutional until sanitization runs.
- **GAV floor: $3B at manager level** (not $1B from embedding worker, not $5B).
- **Reversible.** Every exclusion has `exclusion_reason` for manual override.
- **Idempotent.** Re-run resets flags and re-applies rules.
- **No external fetches.** All data already in DB.
- **Don't break ESMA.** UCITS structure is the institutional filter; apply name/GAV-based rules only.

---

## Session A — Migration + Sanitization Worker

### DELIVERABLES

#### 1. Migration `0134_universe_sanitization_flags.py`

Add to 6 fund tables plus `instruments_universe`:

```python
"""Add is_institutional + exclusion_reason for universe sanitization.

Revision ID: 0134_universe_sanitization_flags
Revises: 0133_strategy_reclassification_stage
"""
from alembic import op
import sqlalchemy as sa

revision = "0134_universe_sanitization_flags"
down_revision = "0133_strategy_reclassification_stage"
branch_labels = None
depends_on = None


TABLES = [
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "sec_bdcs",
    "sec_money_market_funds",
    "esma_funds",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "is_institutional", sa.Boolean,
                nullable=False, server_default=sa.text("true"),
            ),
        )
        op.add_column(
            table,
            sa.Column("exclusion_reason", sa.Text, nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "sanitized_at", sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        # Partial index: institutional rows (most queries filter for these)
        op.create_index(
            f"idx_{table}_institutional",
            table,
            ["is_institutional"],
            postgresql_where=sa.text("is_institutional = true"),
        )

    # instruments_universe is JSONB-attributes-based, store flag inline
    # Use a generated column that reads from attributes for consistency
    op.execute("""
        ALTER TABLE instruments_universe
        ADD COLUMN is_institutional BOOLEAN
        GENERATED ALWAYS AS (
            COALESCE((attributes->>'is_institutional')::boolean, true)
        ) STORED;
    """)
    op.create_index(
        "idx_instruments_universe_institutional",
        "instruments_universe",
        ["is_institutional"],
        postgresql_where=sa.text("is_institutional = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_instruments_universe_institutional", "instruments_universe")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN is_institutional")
    for table in TABLES:
        op.drop_index(f"idx_{table}_institutional", table)
        op.drop_column(table, "sanitized_at")
        op.drop_column(table, "exclusion_reason")
        op.drop_column(table, "is_institutional")
```

#### 2. Sanitization worker: `backend/app/domains/wealth/workers/universe_sanitization.py`

```python
"""Universe sanitization worker.

Layered exclusion rules applied in sequence. First match wins
(exclusion_reason records the triggering rule). Idempotent — resets
flags at start of each run.

Advisory lock: 900_063
Frequency: on-demand. Should run after sec_adv_ingestion,
sec_bulk_ingestion, esma_ingestion, and BEFORE strategy_reclassification.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session

SANITIZATION_LOCK_ID = 900_063
GAV_FLOOR_USD = 3_000_000_000  # $3B manager GAV floor

logger = logging.getLogger(__name__)


# ── Exclusion keyword patterns (PostgreSQL regex, case-insensitive) ──

PATTERN_RETIREMENT = (
    r"(\m401\(?k\)?|\m403\(?b\)?|\m457\b|"
    r"\bIRA\b|\bSEP\s+IRA|\bSIMPLE\s+IRA|"
    r"ERISA|retirement|pension\s+plan|"
    r"\bESOP\b|employee\s+stock\s+ownership|"
    r"\btarget\s+(?:date|retirement)\b)"
)

PATTERN_CIT = (
    r"(collective\s+(?:investment\s+)?trust|"
    r"\bCIT\b\s+fund|"  # Avoid false positives on bank abbreviations
    r"common\s+(?:investment\s+)?fund|"
    r"bank\s+collective)"
)

PATTERN_EDUCATION = (
    r"(\b529\s*(?:plan|portfolio)|"
    r"coverdell|"
    r"education\s+savings)"
)

PATTERN_INSURANCE = (
    r"(stable\s+value|"
    r"guaranteed\s+(?:income|interest|annuity)|"
    r"insurance.{0,10}wrap|"
    r"\bGIC\b|guaranteed\s+investment\s+contract|"
    r"fixed\s+annuity)"
)

PATTERN_SMA_WRAP = (
    r"(\bSMA\b\s+(?:program|platform)|"
    r"separately\s+managed|"
    r"wrap\s+(?:account|program|fee)|"
    r"managed\s+account\s+program|"
    r"\bUMA\b)"  # Unified managed account
)


async def run_universe_sanitization() -> dict[str, Any]:
    """Apply sanitization rules across all fund tables.

    Returns:
        dict with per-table, per-reason exclusion counts.
    """
    started = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "started_at": started.isoformat(),
        "per_table": {},
    }

    async with async_session() as db:
        # Acquire advisory lock
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SANITIZATION_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("sanitization_skipped: another instance running")
            return {"skipped": True, "reason": "lock_contention"}

        try:
            # Reset all flags to institutional=true first (idempotency)
            await _reset_flags(db)
            await db.commit()

            # Apply sanitization rules per table
            result["per_table"]["sec_manager_funds"] = \
                await _sanitize_sec_manager_funds(db)
            await db.commit()

            result["per_table"]["sec_registered_funds"] = \
                await _sanitize_sec_registered_funds(db)
            await db.commit()

            result["per_table"]["sec_etfs"] = await _sanitize_sec_etfs(db)
            await db.commit()

            result["per_table"]["sec_money_market_funds"] = \
                await _sanitize_sec_mmfs(db)
            await db.commit()

            result["per_table"]["esma_funds"] = await _sanitize_esma_funds(db)
            await db.commit()

            # Propagate to instruments_universe via JSONB attributes
            await _propagate_to_instruments_universe(db)
            await db.commit()

            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            result["duration_seconds"] = (
                datetime.now(timezone.utc) - started
            ).total_seconds()

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SANITIZATION_LOCK_ID})")
            )

    return result


async def _reset_flags(db: AsyncSession) -> None:
    """Reset all sanitization flags. Ensures idempotency."""
    for table in [
        "sec_manager_funds", "sec_registered_funds", "sec_etfs",
        "sec_bdcs", "sec_money_market_funds", "esma_funds",
    ]:
        await db.execute(text(f"""
            UPDATE {table}
            SET is_institutional = true,
                exclusion_reason = NULL,
                sanitized_at = NOW()
        """))
    logger.info("sanitization_flags_reset")


async def _sanitize_sec_manager_funds(db: AsyncSession) -> dict[str, int]:
    """Sanitize sec_manager_funds (62k rows, highest-risk table).

    Rules in order:
      1. Retirement/ERISA (name regex)
      2. CIT (name regex)
      3. Education (name regex)
      4. Insurance-wrapped (name regex)
      5. SMA/Wrap (name regex)
      6. GAV floor $3B at manager level (JOIN sec_managers)
      7. Retail-adviser (client_types JSONB check)
      8. Duplicate multi-adviser filings (keep primary, exclude secondaries)
    """
    counts: dict[str, int] = {}

    for reason, pattern in [
        ("retirement", PATTERN_RETIREMENT),
        ("cit", PATTERN_CIT),
        ("education", PATTERN_EDUCATION),
        ("insurance_wrapped", PATTERN_INSURANCE),
        ("sma_wrap", PATTERN_SMA_WRAP),
    ]:
        r = await db.execute(text(f"""
            UPDATE sec_manager_funds
            SET is_institutional = false,
                exclusion_reason = :reason,
                sanitized_at = NOW()
            WHERE is_institutional = true
              AND exclusion_reason IS NULL
              AND fund_name ~* :pattern
        """), {"reason": reason, "pattern": pattern})
        counts[reason] = r.rowcount

    # Rule 6: GAV floor at manager level
    r = await db.execute(text(f"""
        UPDATE sec_manager_funds f
        SET is_institutional = false,
            exclusion_reason = 'gav_below_3b',
            sanitized_at = NOW()
        FROM sec_managers m
        WHERE f.crd_number = m.crd_number
          AND f.is_institutional = true
          AND f.exclusion_reason IS NULL
          AND COALESCE(m.total_private_fund_assets, 0) < {GAV_FLOOR_USD}
    """))
    counts["gav_below_3b"] = r.rowcount

    # Rule 7: Retail adviser (heavy individual clients, few pooled vehicles)
    # client_types JSONB structure: {"individuals": {"count": N, "pct_aum": X}, ...}
    r = await db.execute(text("""
        UPDATE sec_manager_funds f
        SET is_institutional = false,
            exclusion_reason = 'retail_adviser',
            sanitized_at = NOW()
        FROM sec_managers m
        WHERE f.crd_number = m.crd_number
          AND f.is_institutional = true
          AND f.exclusion_reason IS NULL
          AND (
              COALESCE((m.client_types->'individuals'->>'count')::int, 0) > 500
              OR COALESCE((m.client_types->'pooled_vehicles'->>'count')::int, 0) < 2
          )
    """))
    counts["retail_adviser"] = r.rowcount

    # Rule 8: Duplicate multi-adviser filings
    # Strategy: for funds with same (fund_name, gross_asset_value) across
    # multiple crd_numbers, keep the one with the largest adviser (AUM),
    # mark others as duplicates.
    r = await db.execute(text("""
        WITH dupes AS (
            SELECT 
                f.fund_name,
                f.gross_asset_value,
                f.crd_number,
                m.aum_total,
                ROW_NUMBER() OVER (
                    PARTITION BY f.fund_name, f.gross_asset_value
                    ORDER BY m.aum_total DESC NULLS LAST, f.crd_number
                ) AS rn
            FROM sec_manager_funds f
            JOIN sec_managers m ON f.crd_number = m.crd_number
            WHERE f.is_institutional = true
              AND f.exclusion_reason IS NULL
              AND f.fund_name IS NOT NULL
              AND f.gross_asset_value IS NOT NULL
        )
        UPDATE sec_manager_funds f
        SET is_institutional = false,
            exclusion_reason = 'duplicate_filing',
            sanitized_at = NOW()
        FROM dupes d
        WHERE f.fund_name = d.fund_name
          AND COALESCE(f.gross_asset_value, -1) = COALESCE(d.gross_asset_value, -1)
          AND f.crd_number = d.crd_number
          AND d.rn > 1
    """))
    counts["duplicate_filing"] = r.rowcount

    # Total institutional remaining
    r = await db.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_institutional) AS institutional,
            COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded,
            COUNT(*) AS total
        FROM sec_manager_funds
    """))
    summary = dict(r.one()._mapping)
    counts.update(summary)

    logger.info("sec_manager_funds_sanitized", extra=counts)
    return counts


async def _sanitize_sec_registered_funds(db: AsyncSession) -> dict[str, int]:
    """Sanitize sec_registered_funds (mutual funds, interval, closed-end).

    Rules:
      1. Retirement/ERISA keywords in name
      2. Target date fund series (even if not in retirement keywords)
      3. Very low AUM (< $100M — sub-scale)
    """
    counts: dict[str, int] = {}

    # Rule 1: Retirement keywords
    r = await db.execute(text("""
        UPDATE sec_registered_funds
        SET is_institutional = false,
            exclusion_reason = 'retirement',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND fund_name ~* :pattern
    """), {"pattern": PATTERN_RETIREMENT})
    counts["retirement"] = r.rowcount

    # Rule 2: Explicit target date column if exists (N-CEN enrichment)
    r = await db.execute(text("""
        UPDATE sec_registered_funds
        SET is_institutional = false,
            exclusion_reason = 'target_date',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND COALESCE(is_target_date, false) = true
    """))
    counts["target_date"] = r.rowcount

    # Rule 3: Very low AUM (sub-scale)
    # Use sec_fund_classes.net_assets aggregated if available,
    # otherwise skip this rule
    r = await db.execute(text("""
        UPDATE sec_registered_funds f
        SET is_institutional = false,
            exclusion_reason = 'sub_scale',
            sanitized_at = NOW()
        FROM (
            SELECT cik_number, SUM(net_assets) AS total_aum
            FROM sec_fund_classes
            GROUP BY cik_number
        ) agg
        WHERE f.cik_number = agg.cik_number
          AND f.is_institutional = true
          AND f.exclusion_reason IS NULL
          AND agg.total_aum < 100_000_000
    """))
    counts["sub_scale"] = r.rowcount

    r = await db.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_institutional) AS institutional,
            COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded,
            COUNT(*) AS total
        FROM sec_registered_funds
    """))
    counts.update(dict(r.one()._mapping))

    logger.info("sec_registered_funds_sanitized", extra=counts)
    return counts


async def _sanitize_sec_etfs(db: AsyncSession) -> dict[str, int]:
    """Sanitize sec_etfs.

    Most ETFs are institutional-appropriate by structure. Exclude:
      1. Retirement-focused ETFs (target date)
      2. Leveraged/inverse with low AUM (retail exotic)
    """
    counts: dict[str, int] = {}

    r = await db.execute(text("""
        UPDATE sec_etfs
        SET is_institutional = false,
            exclusion_reason = 'retirement',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND fund_name ~* :pattern
    """), {"pattern": PATTERN_RETIREMENT})
    counts["retirement"] = r.rowcount

    # Leveraged/inverse ETFs below $100M AUM are typically retail-focused
    r = await db.execute(text("""
        UPDATE sec_etfs
        SET is_institutional = false,
            exclusion_reason = 'leveraged_retail',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND fund_name ~* '(\\b(?:2x|3x|-?1x|-?2x|-?3x)\\b|leveraged|inverse|ultra)'
          AND COALESCE(net_assets, 0) < 100_000_000
    """))
    counts["leveraged_retail"] = r.rowcount

    r = await db.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_institutional) AS institutional,
            COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded,
            COUNT(*) AS total
        FROM sec_etfs
    """))
    counts.update(dict(r.one()._mapping))

    logger.info("sec_etfs_sanitized", extra=counts)
    return counts


async def _sanitize_sec_mmfs(db: AsyncSession) -> dict[str, int]:
    """Sanitize sec_money_market_funds.

    Rules:
      1. Retirement-focused MMFs (stable value wrappers, ERISA)
      2. Retail-only share class (if mmf_category indicates)
    """
    counts: dict[str, int] = {}

    r = await db.execute(text("""
        UPDATE sec_money_market_funds
        SET is_institutional = false,
            exclusion_reason = 'retirement',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND (
              fund_name ~* :pattern_retirement
              OR fund_name ~* :pattern_insurance
          )
    """), {
        "pattern_retirement": PATTERN_RETIREMENT,
        "pattern_insurance": PATTERN_INSURANCE,
    })
    counts["retirement_or_insurance"] = r.rowcount

    # MMF category check (if column exists and indicates retail)
    r = await db.execute(text("""
        UPDATE sec_money_market_funds
        SET is_institutional = false,
            exclusion_reason = 'retail_mmf_category',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND mmf_category ~* '(retail|\\bgovernment\\s+retail\\b)'
    """))
    counts["retail_mmf_category"] = r.rowcount

    r = await db.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_institutional) AS institutional,
            COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded,
            COUNT(*) AS total
        FROM sec_money_market_funds
    """))
    counts.update(dict(r.one()._mapping))

    logger.info("sec_money_market_funds_sanitized", extra=counts)
    return counts


async def _sanitize_esma_funds(db: AsyncSession) -> dict[str, int]:
    """Sanitize esma_funds (UCITS).

    UCITS structure is already institutional by design (cross-border,
    regulated). Apply lighter filters:
      1. Retirement/pension-focused UCITS
      2. Education/529-equivalent EU products
      3. Very small AUM (< €50M sub-scale)
    """
    counts: dict[str, int] = {}

    r = await db.execute(text("""
        UPDATE esma_funds
        SET is_institutional = false,
            exclusion_reason = 'retirement',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND fund_name ~* :pattern
    """), {"pattern": PATTERN_RETIREMENT})
    counts["retirement"] = r.rowcount

    # EU pension products (PEPP, IORP-covered)
    r = await db.execute(text("""
        UPDATE esma_funds
        SET is_institutional = false,
            exclusion_reason = 'eu_pension',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND fund_name ~* '(\\bPEPP\\b|pan.?european\\s+pension|IORP|occupational\\s+pension)'
    """))
    counts["eu_pension"] = r.rowcount

    # Sub-scale UCITS (if AUM column available)
    # Note: adjust column name based on actual esma_funds schema
    r = await db.execute(text("""
        UPDATE esma_funds
        SET is_institutional = false,
            exclusion_reason = 'sub_scale',
            sanitized_at = NOW()
        WHERE is_institutional = true
          AND exclusion_reason IS NULL
          AND COALESCE(total_assets_eur, 0) < 50_000_000
          AND total_assets_eur IS NOT NULL
    """))
    counts["sub_scale"] = r.rowcount

    r = await db.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_institutional) AS institutional,
            COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded,
            COUNT(*) AS total
        FROM esma_funds
    """))
    counts.update(dict(r.one()._mapping))

    logger.info("esma_funds_sanitized", extra=counts)
    return counts


async def _propagate_to_instruments_universe(db: AsyncSession) -> None:
    """Propagate is_institutional from source tables to instruments_universe.

    The column is GENERATED from attributes->>'is_institutional', so we
    write to JSONB attributes.
    """
    # sec_manager_funds
    await db.execute(text("""
        UPDATE instruments_universe iu
        SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
            'is_institutional', f.is_institutional,
            'exclusion_reason', f.exclusion_reason
        )
        FROM sec_manager_funds f
        WHERE iu.attributes->>'sec_crd' = f.crd_number
          AND iu.attributes->>'fund_name' = f.fund_name
    """))

    # sec_registered_funds via CIK
    await db.execute(text("""
        UPDATE instruments_universe iu
        SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
            'is_institutional', f.is_institutional,
            'exclusion_reason', f.exclusion_reason
        )
        FROM sec_registered_funds f
        WHERE iu.attributes->>'sec_cik' = f.cik_number::text
    """))

    # sec_etfs via series_id
    await db.execute(text("""
        UPDATE instruments_universe iu
        SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
            'is_institutional', f.is_institutional,
            'exclusion_reason', f.exclusion_reason
        )
        FROM sec_etfs f
        WHERE iu.attributes->>'series_id' = f.series_id
    """))

    # esma_funds via ISIN
    await db.execute(text("""
        UPDATE instruments_universe iu
        SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
            'is_institutional', f.is_institutional,
            'exclusion_reason', f.exclusion_reason
        )
        FROM esma_funds f
        WHERE iu.attributes->>'isin' = f.isin
    """))

    logger.info("instruments_universe_flag_propagated")
```

#### 3. Tests: `backend/tests/domains/wealth/workers/test_universe_sanitization.py`

```python
"""Tests for universe sanitization worker."""
import pytest
from uuid import uuid4

from app.domains.wealth.workers.universe_sanitization import (
    run_universe_sanitization,
    GAV_FLOOR_USD,
    PATTERN_RETIREMENT,
    PATTERN_CIT,
)


class TestExclusionPatterns:
    """Regex pattern validation (independent of DB)."""

    @pytest.mark.parametrize("name,should_match", [
        ("Vanguard Target Retirement 2045", True),
        ("Fidelity 401(k) Plan Fund", True),
        ("Morgan Stanley IRA Portfolio", True),
        ("ESOP Shares Trust", True),
        ("ERISA Stable Value Fund", True),
        # Should NOT match
        ("Goldman Sachs Large Cap Growth", False),
        ("KKR Private Credit Fund", False),
        ("Apollo European Equity", False),
    ])
    def test_retirement_pattern(self, name, should_match):
        import re
        match = re.search(PATTERN_RETIREMENT, name, re.IGNORECASE)
        assert bool(match) == should_match

    @pytest.mark.parametrize("name,should_match", [
        ("JPMorgan Collective Investment Trust", True),
        ("Wells Fargo Collective Trust", True),
        ("Bank Collective Fund Series A", True),
        # Should NOT match
        ("Citadel Global Equities", False),
        ("Private Credit Opportunities", False),
    ])
    def test_cit_pattern(self, name, should_match):
        import re
        match = re.search(PATTERN_CIT, name, re.IGNORECASE)
        assert bool(match) == should_match


@pytest.mark.asyncio
class TestSanitizationWorker:
    async def test_worker_completes_without_error(self, db):
        """Integration: worker runs end-to-end against test DB."""
        result = await run_universe_sanitization()
        assert "per_table" in result
        assert "sec_manager_funds" in result["per_table"]

    async def test_idempotent_re_run(self, db):
        """Running twice produces same state."""
        r1 = await run_universe_sanitization()
        r2 = await run_universe_sanitization()
        # Per-reason counts should match exactly (idempotent)
        assert r1["per_table"] == r2["per_table"]
```

---

## Session B — Downstream Consumers + Report

### DELIVERABLES

#### 1. Update `strategy_reclassification.py` to filter institutional

Add `WHERE is_institutional = true` clause to every source table query.

#### 2. Update `candidate_screener.py`

File: `backend/app/domains/wealth/services/candidate_screener.py`

Add filter to the `discover_candidates()` query — `WHERE (attributes->>'is_institutional')::boolean = true`.

#### 3. Update `catalog_sql.py`

File: `backend/app/domains/wealth/queries/catalog_sql.py`

Add institutional filter to `build_catalog_query()`. Default `TRUE` (filter out non-institutional), with optional param `include_non_institutional: bool = False` for admin screens.

#### 4. Update materialized view `mv_unified_funds`

The view joins multiple source tables. Add `is_institutional` column to the SELECT list and a filter clause. Refresh after sanitization worker completes.

Create migration `0135_mv_unified_funds_institutional.py` with a `REFRESH MATERIALIZED VIEW CONCURRENTLY` after the view is redefined.

#### 5. Audit report script: `backend/scripts/universe_sanitization_report.py`

```python
"""Generate audit report of universe sanitization exclusions.

Usage:
    python backend/scripts/universe_sanitization_report.py [--samples=20]

Output:
    - Per-table, per-reason exclusion counts
    - Random samples of excluded funds per reason
    - Remaining institutional totals
    - Diff vs previous sanitization run (if any)
"""
import asyncio
import sys

from sqlalchemy import text
from app.core.db import async_session


TABLES = [
    "sec_manager_funds", "sec_registered_funds", "sec_etfs",
    "sec_bdcs", "sec_money_market_funds", "esma_funds",
]


async def main(samples: int = 20):
    print("\n=== UNIVERSE SANITIZATION AUDIT REPORT ===\n")

    async with async_session() as db:
        for table in TABLES:
            print(f"\n--- {table} ---")
            r = await db.execute(text(f"""
                SELECT 
                    exclusion_reason,
                    COUNT(*) AS n
                FROM {table}
                WHERE NOT is_institutional
                GROUP BY exclusion_reason
                ORDER BY n DESC
            """))
            rows = list(r)
            if not rows:
                print("  (no exclusions)")
                continue
            total_excluded = sum(row[1] for row in rows)
            for reason, n in rows:
                print(f"  {reason:<30} {n:>8,}")
            print(f"  {'TOTAL EXCLUDED':<30} {total_excluded:>8,}")

            # Total institutional
            r = await db.execute(text(f"""
                SELECT COUNT(*) FROM {table} WHERE is_institutional
            """))
            inst = r.scalar()
            print(f"  {'INSTITUTIONAL':<30} {inst:>8,}")

        # Samples per reason for sec_manager_funds (largest table)
        print(f"\n\n=== SAMPLE EXCLUSIONS (sec_manager_funds, {samples} per reason) ===")
        reasons_r = await db.execute(text("""
            SELECT DISTINCT exclusion_reason FROM sec_manager_funds
            WHERE NOT is_institutional AND exclusion_reason IS NOT NULL
        """))
        for (reason,) in reasons_r:
            print(f"\n--- {reason} ---")
            r = await db.execute(text(f"""
                SELECT fund_name, crd_number, gross_asset_value
                FROM sec_manager_funds
                WHERE exclusion_reason = :reason
                ORDER BY RANDOM()
                LIMIT :limit
            """), {"reason": reason, "limit": samples})
            for row in r:
                name, crd, gav = row
                gav_str = f"${gav/1e9:.1f}B" if gav else "--"
                print(f"  [{crd}] {(name or '?')[:70]:<70} {gav_str}")


if __name__ == "__main__":
    samples = 20
    for arg in sys.argv[1:]:
        if arg.startswith("--samples="):
            samples = int(arg.split("=")[1])
    asyncio.run(main(samples=samples))
```

### VERIFICATION

1. `make test` passes.
2. `make lint` and `make typecheck` pass.
3. Migration 0134 applies cleanly.
4. Worker runs to completion against local DB. Report exclusion counts.
5. `sec_manager_funds` institutional count: **expected ~40k** (from 62.7k).
6. `esma_funds` institutional count: **expected ~8k** (from 10.4k).
7. `instruments_universe.attributes->>'is_institutional'` propagated correctly.
8. Downstream queries filter by `is_institutional = true` by default.
9. Audit report script runs and emits exclusion samples.

---

## Interpreting the Output

**Expected per-reason distribution in sec_manager_funds:**

| Reason | Expected count | Rationale |
|---|---|---|
| gav_below_3b | 12,000-16,000 | Most sub-$3B advisers |
| retirement | 500-1,500 | 401k/IRA/ERISA products |
| retail_adviser | 2,000-4,000 | RIAs with >500 individual clients |
| duplicate_filing | 2,000-3,000 | Multi-adviser sub-advisory |
| cit | 500-1,000 | Collective trusts |
| sma_wrap | 500-1,500 | SMA/wrap programs |
| insurance_wrapped | 200-500 | Stable value, GICs |
| education | 50-200 | 529 plans (rare in ADV) |

**If numbers deviate significantly:**
- **`gav_below_3b` > 25,000:** threshold too high — consider dropping to $2B
- **`duplicate_filing` > 5,000:** may indicate broken matching — review samples
- **`retail_adviser` > 10,000:** client_types thresholds too aggressive — tune

**Samples review:**

The audit report produces random samples per exclusion reason. Before proceeding to Round 2 classifier patches + Session B, manually review 10-20 samples per reason. Flag any **false positives** (institutional funds wrongly excluded) for rule tuning.

---

## OUT OF SCOPE

- **Fund-level GAV filtering** — deferred. Would require `sec_manager_funds.gross_asset_value` validation; Schedule D ingestion is incomplete (agent noted fund_id PFIDs missing).
- **Jurisdictional filtering** — deferred. Would require `jurisdiction` column from Schedule D (not populated).
- **`is_section_3c7` / `is_section_3c1`** — deferred. Same reason.
- **Adding `fund_id` (PFID) to dedup** — deferred. Schedule D ingestion backlog item.
- **Share class-level exclusion for sec_registered_funds** — deferred. Current filter at fund level; share class granularity is Phase 1.5+ sprint.
- **Re-running sec_adv_ingestion** — explicitly out of scope. User confirmed external-facing workers not needed.

---

## Order of Execution

1. **Migration 0134 applied** → adds columns with default TRUE (no rows excluded yet).
2. **Worker `run_universe_sanitization()` executed** → flags computed, ~26k rows marked non-institutional.
3. **Audit report reviewed** → sample check for false positives.
4. **Downstream consumers updated** (Session B of this sprint) → queries filter by `is_institutional`.
5. **Session B of classification sprint** can now proceed with a clean universe.
6. **Round 2 classifier patches** run next, with new numbers that reflect the institutional subset only.

---

## After This Sprint

The classifier Session B (apply gate) and Round 2 patches can proceed with confidence that:
- Peer groups reflect institutional reality
- Scoring percentiles are comparable
- Candidate screener proposes only institutional-appropriate funds
- `lost_class` diffs in reclassification will be smaller (non-institutional vehicles no longer pollute the stage)

The `is_institutional = false` rows stay in the DB (reversible, auditable) but are invisible to product queries.
