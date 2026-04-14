# Fund Classification — Phase 2: Cascade Classifier + Bug Fixes + Diff Gate

**Date:** 2026-04-14
**Branch:** `feat/classification-cascade`
**Sessions:** 2 (Session A: Cascade + bug fixes, Session B: Diff gate + apply)
**Depends on:** Phase 1 (Tiingo enrichment worker) complete — `attributes.tiingo_description` populated in `instruments_universe`

---

## Problem

The current classifier at `backend/scripts/backfill_strategy_label.py` has three issues:

1. **Operates only on private funds** (sec_manager_funds, esma_funds, sec_registered_funds). ETFs (92.6% NULL), BDCs, MMFs not routed through the cascade.
2. **Uses only fund name regex** — impossible to classify Balanced/Multi-Asset from name alone (Andrei's example: "invests at least 50% of its total assets in stocks and the remaining assets are generally invested in corporate and government debt").
3. **Specific regex bugs confirmed empirically:**
   - `GOLDMAN SACHS TRUST` → "Commodities" (regex `gold` captures "Goldman")
   - `iShares Mortgage Real Estate ETF` → "Fixed Income" (pattern `(fixed.?income|mortgage)` precedes real estate check)
   - `Columbia Research Enhanced Real Estate ETF` → "Municipal Bond" (muni pattern precedes real estate)
   - `ProShares Short Real Estate` → "Equity" (no inverse/short semantics)
   - `PGIM Real Estate Income Fund` → "Fixed Income" ("Income" captures before "Real Estate")
   - `Credit Allocation Funds` → "Credit" (ignores "Allocation" → should be Multi-Asset)
   - `AQR INNOVATION FUND - SERIES 31 CONVERTIBLE OPPORTUNITIES` → "Convertible Arbitrage" (no fund_type gate)

---

## Architecture — Cascade Classifier

Priority cascade by signal authority. Higher authority wins; each layer sets `classification_source` for lineage.

```
Layer 0: N-PORT holdings composition    [P0, Phase 4 future — NOT this sprint]
Layer 1: Tiingo description regex       [P1, NEW in this sprint]
Layer 2: Fund name regex (fixed)        [P2, bug fixes in this sprint]
Layer 3: ADV fund_type + brochure       [P3, existing, unchanged]
```

Execution order per fund:
1. Check if Tiingo description available and rich (≥ 50 chars) → run Layer 1
2. If Layer 1 classifies → set `classification_source = "tiingo_description"`
3. Else → run Layer 2 (name regex with bug fixes) → `classification_source = "name_regex"`
4. Else → run Layer 3 (brochure, hedge funds only) → `classification_source = "adv_brochure"`
5. Else → fallback category (existing behavior) → `classification_source = "fallback"`

---

## Session A — Cascade Classifier + Bug Fixes

### OBJECTIVE

1. Create a new classifier module `backend/app/domains/wealth/services/strategy_classifier.py` that implements the cascade.
2. Add `classification_source` to `instruments_universe.attributes` JSONB for lineage.
3. Fix all 7 documented name regex bugs.
4. Extend the classifier to ALL fund tables (add ETFs to the cascade).

### FILES TO CREATE

#### 1. `backend/app/domains/wealth/services/strategy_classifier.py`

Main classifier module. Pure functions, no DB writes (writes handled by caller).

```python
"""
Fund strategy classifier — cascade by signal authority.

Signal authority:
    Tiingo description (Layer 1) > Fund name regex (Layer 2) > ADV brochure (Layer 3)

Each classification includes `source` for lineage in downstream audit.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import re

@dataclass(frozen=True)
class ClassificationResult:
    strategy_label: str | None
    source: Literal["tiingo_description", "name_regex", "adv_brochure", "fallback"]
    confidence: Literal["high", "medium", "low"]
    matched_pattern: str | None  # e.g., "keyword:balanced_60_40"


# Strategy catalog — 37 labels canonical (preserve existing taxonomy)
STRATEGY_LABELS = {
    # Equity
    "Large Blend", "Large Growth", "Large Value",
    "Mid Blend", "Mid Growth", "Mid Value",
    "Small Blend", "Small Growth", "Small Value",
    "International Equity", "Emerging Markets Equity",
    "Global Equity", "Sector Equity",
    # Fixed Income
    "Short-Term Bond", "Intermediate-Term Bond", "Long-Term Bond",
    "High Yield Bond", "Investment Grade Bond",
    "Government Bond", "Municipal Bond", "International Bond",
    "Inflation-Linked Bond",
    # Private / Alts
    "Private Credit", "Private Equity", "Venture Capital",
    "Real Estate", "Infrastructure", "Commodities", "Precious Metals",
    # Hedge
    "Long/Short Equity", "Global Macro", "Multi-Strategy",
    "Event-Driven", "Volatility Arbitrage", "Convertible Arbitrage",
    "Quant/Systematic",
    # Multi-Asset
    "Balanced", "Target Date", "Allocation",
    # Other
    "Cash Equivalent", "Other",
}


def classify_fund(
    *,
    fund_name: str,
    fund_type: str | None,
    tiingo_description: str | None,
) -> ClassificationResult:
    """Classify a fund through the cascade. Pure function."""
    # Layer 1: Tiingo description
    if tiingo_description and len(tiingo_description) >= 50:
        result = _classify_from_description(tiingo_description, fund_type)
        if result is not None:
            return ClassificationResult(
                strategy_label=result[0],
                source="tiingo_description",
                confidence="high",
                matched_pattern=result[1],
            )

    # Layer 2: Fund name regex (bug-fixed)
    result = _classify_from_name(fund_name, fund_type)
    if result is not None:
        return ClassificationResult(
            strategy_label=result[0],
            source="name_regex",
            confidence="medium",
            matched_pattern=result[1],
        )

    # Layer 3 (brochure) not handled here — requires DB access, called separately by worker
    return ClassificationResult(
        strategy_label=None,
        source="fallback",
        confidence="low",
        matched_pattern=None,
    )


def _classify_from_description(
    description: str, fund_type: str | None,
) -> tuple[str, str] | None:
    """Layer 1: classify from Tiingo description keywords.

    Pattern priority matters — more specific patterns first.
    Returns (strategy_label, matched_pattern) or None.
    """
    text = description.lower()

    # ── Balanced / Multi-Asset (explicit composition) ─────────────
    # Catches "60% equity 40% debt", "approximately 50% stocks and 50% bonds", etc.
    balanced_patterns = [
        r"(\d+)%\s+(?:of\s+its\s+(?:total\s+)?assets\s+in\s+)?(?:debt|bonds?|fixed\s+income)",
        r"(?:approximately|about)\s+\d+%.*(?:debt|bonds?).*\d+%.*(?:equit(?:y|ies)|stocks?)",
        r"balanced\s+(?:fund|portfolio)",
        r"target\s+(?:date|risk|allocation)",
    ]
    for pattern in balanced_patterns:
        if re.search(pattern, text):
            # Target date funds are their own category
            if "target date" in text or "target retirement" in text:
                return ("Target Date", f"desc:target_date")
            return ("Balanced", f"desc:balanced:{pattern[:30]}")

    # ── Real Estate / REIT ─────────────────────────────────────────
    real_estate_patterns = [
        r"\breal\s+estate\s+(?:securities|investment|sector|companies)",
        r"\breits?\b",
        r"real\s+estate\s+investment\s+trusts?",
        r"mortgage\s+(?:reit|real\s+estate)",
    ]
    for pattern in real_estate_patterns:
        if re.search(pattern, text):
            return ("Real Estate", f"desc:real_estate:{pattern[:30]}")

    # ── Precious Metals (specific: gold, silver, mining) ───────────
    # IMPORTANT: check before "Commodities" to avoid fallthrough
    precious_metals_patterns = [
        r"\bgold\s+(?:and\s+silver|mining|bullion|producers)",
        r"\bsilver\s+(?:mining|producers)",
        r"precious\s+metals",
        r"\bmining\s+(?:companies|equities|stocks)",
    ]
    for pattern in precious_metals_patterns:
        if re.search(pattern, text):
            return ("Precious Metals", f"desc:precious_metals:{pattern[:30]}")

    # ── Commodities (general, after precious metals exclusion) ─────
    commodity_patterns = [
        r"\bcommodit(?:y|ies)\s+(?:futures|index|prices)",
        r"\bcrude\s+oil",
        r"agricultural\s+commodit",
        r"natural\s+gas\s+(?:prices|futures)",
    ]
    for pattern in commodity_patterns:
        if re.search(pattern, text):
            return ("Commodities", f"desc:commodities:{pattern[:30]}")

    # ── Private Credit / Direct Lending ────────────────────────────
    private_credit_patterns = [
        r"direct\s+lending",
        r"private\s+(?:credit|debt|lending)",
        r"middle[- ]market\s+(?:loans|lending)",
        r"senior\s+secured\s+loans",
    ]
    for pattern in private_credit_patterns:
        if re.search(pattern, text):
            return ("Private Credit", f"desc:private_credit:{pattern[:30]}")

    # ── Fixed Income (by specificity) ──────────────────────────────
    # High Yield before general Fixed Income
    if re.search(r"high[- ]yield\s+bonds?|junk\s+bonds?|non[- ]investment\s+grade", text):
        return ("High Yield Bond", "desc:high_yield")
    if re.search(r"municipal\s+bonds?|muni\s+(?:bonds?|debt)|tax[- ]exempt", text):
        return ("Municipal Bond", "desc:municipal")
    if re.search(r"treasury\s+(?:bonds?|notes?|securities)|government\s+bonds?", text):
        return ("Government Bond", "desc:government_bond")
    if re.search(r"investment[- ]grade\s+(?:bonds?|credit|debt)|corporate\s+bonds?", text):
        return ("Investment Grade Bond", "desc:ig_bond")
    if re.search(r"inflation[- ]linked|treasury\s+inflation|tips\b", text):
        return ("Inflation-Linked Bond", "desc:tips")

    # ── Equity strategies (size + style) ───────────────────────────
    # Check size keywords
    is_large = bool(re.search(r"\blarge[- ]cap|s&p\s*500|russell\s*1000|large\s+compan", text))
    is_mid = bool(re.search(r"\bmid[- ]cap|russell\s*midcap|medium\s+compan", text))
    is_small = bool(re.search(r"\bsmall[- ]cap|russell\s*2000|small\s+compan", text))

    # Check style keywords
    is_growth = bool(re.search(r"\bgrowth\s+(?:stocks?|compan|style|invest)", text))
    is_value = bool(re.search(r"\bvalue\s+(?:stocks?|compan|style|invest)", text))

    # International check
    if re.search(r"(?:emerging\s+markets?|developing\s+countries)", text):
        return ("Emerging Markets Equity", "desc:emerging_markets")
    if re.search(r"(?:international|global|world|foreign)\s+(?:equit|stocks?|compan)", text):
        return ("International Equity", "desc:international")

    # Domestic size + style
    if is_large:
        if is_growth: return ("Large Growth", "desc:large_growth")
        if is_value: return ("Large Value", "desc:large_value")
        return ("Large Blend", "desc:large_blend")
    if is_mid:
        if is_growth: return ("Mid Growth", "desc:mid_growth")
        if is_value: return ("Mid Value", "desc:mid_value")
        return ("Mid Blend", "desc:mid_blend")
    if is_small:
        if is_growth: return ("Small Growth", "desc:small_growth")
        if is_value: return ("Small Value", "desc:small_value")
        return ("Small Blend", "desc:small_blend")

    # ── Hedge strategies (only if fund_type hints hedge) ──────────
    if fund_type and "hedge" in fund_type.lower():
        if re.search(r"long[/-]short|130[/-]30", text):
            return ("Long/Short Equity", "desc:long_short")
        if re.search(r"global\s+macro", text):
            return ("Global Macro", "desc:macro")
        if re.search(r"multi[- ]strateg|multi[- ]manager", text):
            return ("Multi-Strategy", "desc:multi_strategy")
        if re.search(r"event[- ]driven|merger\s+arbitrage|activist", text):
            return ("Event-Driven", "desc:event_driven")
        if re.search(r"volatility\s+(?:arbitrage|strategy)|options\s+(?:strategy|based)", text):
            return ("Volatility Arbitrage", "desc:vol_arb")
        if re.search(r"\bquant(?:itative)?|systematic|algorithmic", text):
            return ("Quant/Systematic", "desc:quant")

    # ── Cash / Money Market ────────────────────────────────────────
    if re.search(r"money\s+market|cash\s+equivalent|short[- ]duration", text):
        return ("Cash Equivalent", "desc:cash")

    # No match in Layer 1
    return None


def _classify_from_name(
    fund_name: str, fund_type: str | None,
) -> tuple[str, str] | None:
    """Layer 2: classify from fund name. BUG-FIXED version.

    Key fixes vs backfill_strategy_label.py:
    1. 'gold' pattern requires word boundary (does not match 'Goldman')
    2. Real Estate checked BEFORE Fixed Income/Income patterns
    3. Short/Inverse ETF patterns detected and passed through
    4. Balanced/Multi-Asset detected via 'allocation' or 'balanced' keywords
    5. Convertible requires fund_type gate (only hedge funds)
    """
    if not fund_name:
        return None
    name = fund_name.lower()

    # ── Bug fix: word-boundary 'gold' ──────────────────────────────
    # Only match 'gold' as standalone word, not as part of 'Goldman'
    has_gold = bool(re.search(r"\bgold\b(?!\s*man)", name))
    has_silver_mining = bool(re.search(r"\bsilver\b|\bmining\b|\bprecious\s+metal", name))

    # ── Real Estate FIRST (before Fixed Income/Income) ────────────
    # Bug fix: PGIM Real Estate Income was being caught by "Income" pattern
    if re.search(r"\breal\s+estate\b|\breit\b|housing|residential", name):
        return ("Real Estate", "name:real_estate")

    # ── Short/Inverse ETFs (new category) ──────────────────────────
    # ProShares Short Real Estate should classify as Real Estate (inverse exposure)
    # Not Equity. The asset class is the underlying, direction is separate.
    # For now, detect and fall through to underlying asset class
    if re.search(r"\bshort\b|\binverse\b|\b-1x\b|\b-2x\b|\b-3x\b", name):
        # Strip short/inverse prefix and try to classify underlying
        stripped = re.sub(r"\b(short|inverse|-?[123]x)\b", "", name).strip()
        if stripped and stripped != name:
            # Recursive call on stripped name
            sub_result = _classify_from_name(stripped, fund_type)
            if sub_result is not None:
                return (sub_result[0], f"name:short:{sub_result[1]}")

    # ── Balanced / Multi-Asset ─────────────────────────────────────
    # Bug fix: "Credit Allocation Funds" should be Balanced, not Credit
    if re.search(r"\ballocation\b|\bbalanced\b|\bmulti[- ]asset\b", name):
        return ("Balanced", "name:balanced")
    if re.search(r"target\s+(?:date|retirement|\d{4})", name):
        return ("Target Date", "name:target_date")

    # ── Precious Metals (word-boundary gold check) ─────────────────
    if has_gold or has_silver_mining:
        return ("Precious Metals", "name:precious_metals")

    # ── Private Credit / Direct Lending ────────────────────────────
    if re.search(r"direct\s+lend|private\s+(?:credit|debt|lending)|middle[- ]market", name):
        return ("Private Credit", "name:private_credit")

    # ── Convertible (fund_type gate) ───────────────────────────────
    # Bug fix: AQR Innovation Convertible (equity fund) was being classified as Convertible Arbitrage
    # Require fund_type to indicate hedge fund
    if "convertible" in name and fund_type and "hedge" in fund_type.lower():
        return ("Convertible Arbitrage", "name:convertible_arb")

    # ── Fixed Income (AFTER Real Estate) ───────────────────────────
    if re.search(r"\bhigh[- ]yield\b|\bjunk\b", name):
        return ("High Yield Bond", "name:high_yield")
    if re.search(r"\bmunicipal\b|\bmuni\b|tax[- ]exempt", name):
        return ("Municipal Bond", "name:municipal")
    if re.search(r"\btreasury\b|\bgovernment\s+bond", name):
        return ("Government Bond", "name:government")
    if re.search(r"\binvestment[- ]grade\b|\bcorporate\s+bond", name):
        return ("Investment Grade Bond", "name:ig_bond")
    if re.search(r"\btips\b|inflation[- ]linked|\btip\s+", name):
        return ("Inflation-Linked Bond", "name:tips")
    # General bond/income (lowest priority in FI)
    if re.search(r"\bbond\b|\bincome\b|\bfixed[- ]income\b", name) and "equity" not in name:
        return ("Intermediate-Term Bond", "name:general_bond")

    # ── Equity size + style ────────────────────────────────────────
    if re.search(r"emerging\s+markets?", name):
        return ("Emerging Markets Equity", "name:emerging")
    if re.search(r"\binternational\b|\bglobal\b|\bworld\b|\bforeign\b", name):
        return ("International Equity", "name:international")

    is_large = bool(re.search(r"\blarge[- ]cap\b|s&p\s*500", name))
    is_mid = bool(re.search(r"\bmid[- ]cap\b", name))
    is_small = bool(re.search(r"\bsmall[- ]cap\b|russell\s*2000", name))
    is_growth = bool(re.search(r"\bgrowth\b", name))
    is_value = bool(re.search(r"\bvalue\b", name))

    if is_large:
        if is_growth: return ("Large Growth", "name:large_growth")
        if is_value: return ("Large Value", "name:large_value")
        return ("Large Blend", "name:large_blend")
    if is_mid:
        if is_growth: return ("Mid Growth", "name:mid_growth")
        if is_value: return ("Mid Value", "name:mid_value")
        return ("Mid Blend", "name:mid_blend")
    if is_small:
        if is_growth: return ("Small Growth", "name:small_growth")
        if is_value: return ("Small Value", "name:small_value")
        return ("Small Blend", "name:small_blend")

    # ── Hedge strategies (fund_type gate) ──────────────────────────
    if fund_type and "hedge" in fund_type.lower():
        if re.search(r"long[/-]short", name): return ("Long/Short Equity", "name:long_short")
        if re.search(r"macro", name): return ("Global Macro", "name:macro")
        if re.search(r"multi[- ]strateg", name): return ("Multi-Strategy", "name:multi_strategy")
        if re.search(r"event[- ]driven|merger\s+arb|activist", name): return ("Event-Driven", "name:event_driven")
        if re.search(r"volatility", name): return ("Volatility Arbitrage", "name:vol_arb")
        if re.search(r"\bquant\b|systematic", name): return ("Quant/Systematic", "name:quant")
        return ("Multi-Strategy", "name:hedge_generic")  # Default for hedge

    # ── Private funds default ──────────────────────────────────────
    if fund_type:
        ft = fund_type.lower()
        if "private equity" in ft: return ("Private Equity", "fund_type:pe")
        if "venture" in ft: return ("Venture Capital", "fund_type:vc")
        if "real estate" in ft: return ("Real Estate", "fund_type:re")
        if "securitized" in ft: return ("Private Credit", "fund_type:securitized")

    return None
```

#### 2. `backend/app/domains/wealth/workers/strategy_reclassification.py`

Worker that runs the cascade over all fund tables and stages results.

```python
"""
Strategy reclassification worker.

Runs the cascade classifier over all fund sources and stages results
into a new table `strategy_reclassification_stage` for review BEFORE
overwriting production labels. The diff gate (Session B) applies staged
results after human review.

Advisory lock: 900_062
Frequency: on-demand (not scheduled). Operator runs via CLI or API endpoint.
"""
from __future__ import annotations
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session
from app.domains.wealth.services.strategy_classifier import classify_fund

RECLASSIFICATION_LOCK_ID = 900_062
logger = logging.getLogger(__name__)


async def run_strategy_reclassification(
    *,
    sources: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Run cascade classifier. Writes results to staging table, not production.

    Args:
        sources: List of table names. If None, runs all: 
            ['instruments_universe', 'sec_manager_funds', 'sec_registered_funds',
             'sec_etfs', 'esma_funds']
        limit: Max funds per source. If None, all.

    Returns:
        Counts per source.
    """
    sources = sources or [
        "instruments_universe", "sec_manager_funds", "sec_registered_funds",
        "sec_etfs", "esma_funds",
    ]

    results: dict[str, int] = {}

    async with async_session() as db:
        # Acquire advisory lock
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({RECLASSIFICATION_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("reclassification_skipped: another instance running")
            return {}

        try:
            for source in sources:
                count = await _reclassify_source(db, source, limit)
                results[source] = count
                await db.commit()
                logger.info("reclassified_source", extra={"source": source, "count": count})
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({RECLASSIFICATION_LOCK_ID})")
            )

    return results


async def _reclassify_source(
    db: AsyncSession, source: str, limit: int | None,
) -> int:
    """Reclassify one source table. Writes to strategy_reclassification_stage."""
    # Query varies by source — each has different column names and JOIN needs
    # For instruments_universe: name, attributes.fund_type, attributes.tiingo_description
    # For sec_manager_funds: fund_name, fund_type (no Tiingo — uses ADV brochure Layer 3)
    # Etc.
    # Implementation: one SQL per source, classify in Python, INSERT to stage table
    # (See migration below for stage table schema)
    ...
```

#### 3. Migration: `backend/app/core/db/migrations/versions/0134_strategy_reclassification_stage.py`

```python
"""strategy_reclassification_stage table for diff-gated reclassification.

Revision ID: 0134_strategy_reclassification_stage
Revises: 0133_construction_inputs_metadata (or latest)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0134_strategy_reclassification_stage"
down_revision = "0133_construction_inputs_metadata"  # Or current head
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_reclassification_stage",
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_table", sa.Text, nullable=False),  # "sec_manager_funds", etc.
        sa.Column("source_pk", sa.Text, nullable=False),     # Primary key value as text
        sa.Column("fund_name", sa.Text, nullable=True),
        sa.Column("fund_type", sa.Text, nullable=True),
        sa.Column("current_strategy_label", sa.Text, nullable=True),
        sa.Column("proposed_strategy_label", sa.Text, nullable=True),
        sa.Column("classification_source", sa.Text, nullable=False),
        sa.Column("matched_pattern", sa.Text, nullable=True),
        sa.Column("confidence", sa.Text, nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_stage_run_id", "strategy_reclassification_stage", ["run_id"],
    )
    op.create_index(
        "idx_stage_source_table", "strategy_reclassification_stage", ["source_table"],
    )


def downgrade() -> None:
    op.drop_table("strategy_reclassification_stage")
```

### TESTS

#### `backend/tests/services/test_strategy_classifier.py`

Test all documented bugs as regression tests:

```python
import pytest
from app.domains.wealth.services.strategy_classifier import classify_fund


class TestNameBugFixes:
    def test_goldman_is_not_precious_metals(self):
        result = classify_fund(
            fund_name="GOLDMAN SACHS TRUST - LARGE CAP GROWTH FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"
        assert result.source == "name_regex"

    def test_ishares_mortgage_real_estate(self):
        result = classify_fund(
            fund_name="iShares Mortgage Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_columbia_research_enhanced_real_estate(self):
        result = classify_fund(
            fund_name="Columbia Research Enhanced Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_proshares_short_real_estate(self):
        result = classify_fund(
            fund_name="ProShares Short Real Estate",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"
        assert "short" in (result.matched_pattern or "")

    def test_pgim_real_estate_income(self):
        result = classify_fund(
            fund_name="PGIM Real Estate Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_credit_allocation_is_balanced(self):
        result = classify_fund(
            fund_name="Credit Allocation Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Balanced"

    def test_aqr_convertible_without_hedge_type(self):
        """Convertible in name without hedge fund_type should NOT be Convertible Arb."""
        result = classify_fund(
            fund_name="AQR INNOVATION FUND - SERIES 31 CONVERTIBLE OPPORTUNITIES",
            fund_type="Mutual Fund",  # Not hedge
            tiingo_description=None,
        )
        assert result.strategy_label != "Convertible Arbitrage"


class TestTiingoDescriptionLayer:
    def test_balanced_60_40_from_description(self):
        result = classify_fund(
            fund_name="Voya Balanced Income",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests approximately 60% of its assets in debt instruments "
                "and approximately 40% of its assets in equity securities"
            ),
        )
        assert result.strategy_label == "Balanced"
        assert result.source == "tiingo_description"

    def test_precious_metals_from_description(self):
        result = classify_fund(
            fund_name="World Something Fund",
            fund_type="Mutual Fund",
            tiingo_description="invests primarily in gold mining companies and precious metals producers",
        )
        assert result.strategy_label == "Precious Metals"
        assert result.source == "tiingo_description"

    def test_real_estate_from_description(self):
        result = classify_fund(
            fund_name="Generic Equity Fund",
            fund_type="Mutual Fund",
            tiingo_description="invests in publicly traded real estate securities using price-to-NAV and cash flow multiple ratios",
        )
        assert result.strategy_label == "Real Estate"
        assert result.source == "tiingo_description"

    def test_description_overrides_name(self):
        """If description says Real Estate, don't let name fool us."""
        result = classify_fund(
            fund_name="Cohen & Steers Realty Shares",
            fund_type="Mutual Fund",
            tiingo_description="bottom-up, relative value investment process when selecting publicly traded real estate securities",
        )
        assert result.strategy_label == "Real Estate"
        assert result.source == "tiingo_description"


class TestCascadePriority:
    def test_description_beats_name(self):
        """If Tiingo description available and classifies, it wins."""
        result = classify_fund(
            fund_name="Generic Growth Fund",
            fund_type="ETF",
            tiingo_description="invests primarily in gold mining companies",
        )
        assert result.source == "tiingo_description"
        assert result.strategy_label == "Precious Metals"

    def test_fallback_to_name_when_description_weak(self):
        """If description is too short, use name."""
        result = classify_fund(
            fund_name="Vanguard Large-Cap Growth ETF",
            fund_type="ETF",
            tiingo_description="short",  # < 50 chars
        )
        assert result.source == "name_regex"
        assert result.strategy_label == "Large Growth"
```

### VERIFICATION

1. `make test` passes (regression tests + new tests).
2. `make lint` passes.
3. `make typecheck` passes.
4. Migration 0134 applies cleanly.
5. All 7 documented bugs fixed (tests assert fixed behavior).
6. Worker `run_strategy_reclassification()` populates stage table without touching production.

---

## Session B — Diff Gate + Apply

### OBJECTIVE

1. Generate a CSV diff report: current vs proposed labels per source.
2. Quantify downstream impact: allocation blocks affected, active portfolios with at-risk funds.
3. Classify diffs by severity (asset class crossing = high, style refinement = low).
4. Provide manual approval mechanism: apply staged labels with operator sign-off.

### DELIVERABLES

#### 1. `backend/scripts/strategy_diff_report.py`

Generate CSV with columns:
- source_table, source_pk, fund_name, current_label, proposed_label
- classification_source, confidence, matched_pattern
- severity: "asset_class_change" | "style_refinement" | "new_classification" | "unchanged"
- downstream_impact_blocks: list of allocation_blocks affected
- downstream_impact_portfolios: count of active portfolios holding this fund
- requires_manual_review: bool

Severity logic:
- `unchanged`: current == proposed
- `new_classification`: current is NULL or "Other", proposed is specific
- `style_refinement`: same asset class family (e.g., "Large Blend" → "Large Growth")
- `asset_class_change`: different family (e.g., "Fixed Income" → "Real Estate") — REQUIRES REVIEW

Family map:
```python
STRATEGY_FAMILY = {
    "Large Blend": "equity", "Large Growth": "equity", "Large Value": "equity",
    "Mid Blend": "equity", "Mid Growth": "equity", "Mid Value": "equity",
    "Small Blend": "equity", "Small Growth": "equity", "Small Value": "equity",
    "International Equity": "equity", "Emerging Markets Equity": "equity",
    "Global Equity": "equity", "Sector Equity": "equity",
    "Short-Term Bond": "fixed_income", "Intermediate-Term Bond": "fixed_income",
    "Long-Term Bond": "fixed_income", "High Yield Bond": "fixed_income",
    "Investment Grade Bond": "fixed_income", "Government Bond": "fixed_income",
    "Municipal Bond": "fixed_income", "International Bond": "fixed_income",
    "Inflation-Linked Bond": "fixed_income",
    "Real Estate": "alts", "Infrastructure": "alts",
    "Commodities": "alts", "Precious Metals": "alts",
    "Private Credit": "private", "Private Equity": "private", "Venture Capital": "private",
    "Long/Short Equity": "hedge", "Global Macro": "hedge", "Multi-Strategy": "hedge",
    "Event-Driven": "hedge", "Volatility Arbitrage": "hedge", "Convertible Arbitrage": "hedge",
    "Quant/Systematic": "hedge",
    "Balanced": "multi_asset", "Target Date": "multi_asset", "Allocation": "multi_asset",
    "Cash Equivalent": "cash", "Other": "other",
}
```

Output: `reports/strategy_diff_{run_id}.csv` for operator review.

#### 2. `backend/scripts/apply_strategy_reclassification.py`

Apply staged labels after review. Options:
- `--run-id UUID` (required): which reclassification run to apply
- `--severity` (optional): filter by severity (e.g., `--severity style_refinement,new_classification` to apply only low-risk)
- `--dry-run` (default True): preview counts without writing
- `--confirm` (explicit flag): actually write

For each staged row that matches filters:
1. UPDATE source_table SET strategy_label = proposed_label WHERE pk = source_pk
2. Also UPDATE `instruments_universe.attributes` → set `strategy_label` + `classification_source` + `classification_updated_at`
3. Mark stage row as `applied_at = NOW()`, `applied_by = <actor>`
4. Refresh materialized views: `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds`
5. Emit audit event per applied row

#### 3. `backend/app/core/db/migrations/versions/0135_classification_source_column.py`

Add a columns to preserve classification lineage at source table level (not just JSONB):

```python
# For sec_manager_funds, sec_registered_funds, sec_etfs — add:
op.add_column("sec_manager_funds", sa.Column("classification_source", sa.Text, nullable=True))
op.add_column("sec_manager_funds", sa.Column("classification_updated_at", sa.DateTime(timezone=True), nullable=True))
# Repeat for sec_registered_funds, sec_etfs, esma_funds
```

### VERIFICATION

1. `strategy_diff_report.py` produces CSV with severity classification and downstream impact.
2. Apply script dry-run shows counts by severity without writing.
3. Apply script with `--confirm` writes to source tables and updates JSONB lineage.
4. Materialized view refresh succeeds.
5. Audit events emitted for every applied reclassification.
6. No production writes happen without operator confirmation.

### DECISIONS

- **Do NOT auto-apply asset_class_change diffs.** These require manual review because they can move a fund out of an active allocation block.
- **Style refinements (same family) can be auto-applied** after sanity check on counts.
- **New classifications (NULL → specific)** are always safe to auto-apply — they add information without contradicting existing.
- **Reclassification is a one-shot operation for this sprint.** Not scheduled. Operator runs manually after each Phase 1 Tiingo refresh.

---

## Out of Scope (Explicit Deferrals)

- **Layer 0 (N-PORT holdings composition classifier)** — deferred to Phase 4. Requires SQL analytics over `sec_nport_holdings` to compute asset mix and classify by composition. Separate sprint.
- **LLM-based classification** — explicitly rejected. Deterministic regex keeps auditability.
- **Re-scheduled reclassification** — one-shot for now. If cadence is needed later, wrap `run_strategy_reclassification` in a cron.
- **Share class expansion** — out of scope. Series-level classification is sufficient for strategy.
- **ESMA + UCITS edge cases** — apply same classifier but may need regional keyword additions (e.g., "OEIC", "SICAV") in a later iteration.
