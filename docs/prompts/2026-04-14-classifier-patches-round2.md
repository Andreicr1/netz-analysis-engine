# Fund Classifier — Patches Round 2 (ESMA + Sectors + CMBS + Long/Short UCITS)

**Date:** 2026-04-14
**Branch:** `fix/classifier-patches-round2`
**Sessions:** 1
**Depends on:** PR #169 (Round 1 patches) + PR #171/#172 (universe sanitization) merged

---

## Context

After Round 1 patches and universe sanitization, the staging table showed `lost_class = 13,409`. Sample analysis revealed these concentrations:

| Gap | Samples | Scale |
|---|---|---|
| **ESMA taxonomy mismatch** | "BNP Paribas Sustainable Asian Cities Bond", "Allianz European Equity" | ~5,248 ESMA rows |
| **Long/Short UCITS** | "Pictet Long Short", "Lyxor/Morgan Stanley EuroZone Long Short" | ~300-500 rows |
| **Sector Equity** | "Energy Services Fund", "Health Care Services Portfolio" | ~500-1,000 rows |
| **CMBS / ABS / MBS** | "Pimco Commercial Mortgage Securities", "TCW Asset-Backed Securities" | ~200-500 rows |
| **Convertible (standalone)** | "Columbia Convertible Securities", "Franklin Convertible Securities" | ~100-200 rows |
| **Leveraged long ETFs** | "ProShares Ultra S&P 500" (2x long), "Direxion Daily 3x Bull" | ~100 rows |
| **ESG/Sustainable** | "BlackRock Sustainable Equity", "Vanguard ESG U.S. Stock ETF" | ~200-500 rows |

Empirical audit of `strategy_classifier.py` confirmed missing patterns across 9 dimensions.

---

## OBJECTIVE

Apply 8 targeted patches to `strategy_classifier.py` that:
1. Add 6 new labels to the taxonomy (ESMA-specific + sector fixed income)
2. Fix 1 critical bug (Long/Short UCITS gate)
3. Add 6 new pattern blocks (standalone Convertible, Sector Equity, CMBS/ABS/MBS, Long leverage, ESG/Sustainable, European bonds, Asian equity)

Re-run the reclassification worker afterward. Expected `lost_class` reduction: from 13,409 to 6,000-8,000.

---

## CONSTRAINTS

- **Additive.** No existing tests should regress. All 30 tests from Round 1 must still pass.
- **Pure function changes.** Only edits to `strategy_classifier.py`.
- **Tests first.** Every patch has a regression test before the fix lands.
- **Keep deterministic.** No LLM. Regex + keywords.
- **Preserve existing taxonomy.** Only ADD labels, don't rename.
- **New labels are real, not cosmetic.** Each maps to downstream usage (peer groups, block mapping).

---

## DELIVERABLES

### 1. Expand `STRATEGY_LABELS` taxonomy (+6 labels)

File: `backend/app/domains/wealth/services/strategy_classifier.py`

Add to the `STRATEGY_LABELS` set:

```python
# Under Equity section, ADD:
"European Equity",
"Asian Equity",
"ESG/Sustainable Equity",

# Under Fixed Income section, ADD:
"European Bond",
"Emerging Markets Debt",
"ESG/Sustainable Bond",
"Mortgage-Backed Securities",
"Asset-Backed Securities",

# Under Convertibles, ADD (separate from Convertible Arbitrage):
"Convertible Securities",
```

Total taxonomy goes from 38 to 47 labels.

**Note on "Multi-Asset" vs "Balanced":** These are synonyms (Balanced is US convention, Multi-Asset is European convention). Keep only "Balanced" in taxonomy — ESMA Multi-Asset names already map to Balanced via existing pattern. No new label needed.

**Note on "ESG/Sustainable Equity" vs "ESG/Sustainable Bond":** Two distinct labels because:
- Scoring peer groups differ materially (equity volatility vs bond volatility)
- Allocation block routing differs
- If the fund is Balanced/ESG, keep as Balanced (ESG is secondary tag)

---

### 2. Patch 1 — Fix Long/Short UCITS gate (CRITICAL BUG)

**Current (buggy):**
```python
# Layer 2 name patterns, line ~443:
if fund_type and "hedge" in fund_type.lower():
    if re.search(r"long[/-]short", name): return ("Long/Short Equity", "name:long_short")
    # ... other hedge patterns
```

ESMA UCITS with `fund_type = "UCITS"` and name "Long Short Global Equity" never matches because the hedge gate fires False.

**Patched:**
Add Long/Short detection OUTSIDE the hedge gate, BEFORE the hedge gate fires:

```python
# Before the hedge block, add:
# Long/Short can be UCITS structure (not just US hedge fund) — check name regardless of fund_type
if re.search(r"\blong[/-]\s*short\b", name, re.IGNORECASE):
    return ("Long/Short Equity", "name:long_short_ucits_or_hedge")
```

Same fix for Layer 1 (description):
```python
# Before the hedge fund_type gate in _classify_from_description:
if re.search(r"long[/-]short\s+(?:equit|strategy)|long[- ]short\s+position", text):
    return ("Long/Short Equity", "desc:long_short")
```

### 3. Patch 2 — Standalone Convertible Securities (not Arbitrage)

**Current bug:** "convertible" only classifies when fund_type is hedge. Mutual funds like "Columbia Convertible Securities" fall through.

**Layer 2 (name), BEFORE the hedge-gated Convertible Arbitrage:**
```python
# Standalone convertible detection (non-hedge structure)
# Must come AFTER fund_type check — hedge funds still get Convertible Arbitrage
if re.search(r"\bconvertible\s+(?:secur|bond|fund)", name):
    if not (fund_type and "hedge" in fund_type.lower()):
        return ("Convertible Securities", "name:convertible_securities")
```

**Layer 1 (description):**
```python
# Before the hedge block in _classify_from_description:
if re.search(r"invests?\s+.*convertible\s+(?:securities|bonds)", text):
    return ("Convertible Securities", "desc:convertible_securities")
```

### 4. Patch 3 — Sector Equity patterns

Currently taxonomy has "Sector Equity" but zero patterns fire. Add explicit sector keywords.

**Layer 2 (name), BEFORE size+style blocks:**
```python
# Sector ETF detection — fires before generic size/style inference
sector_patterns = [
    (r"\b(?:energy|oil\s+&\s+gas|petroleum)\s+(?:sector|fund|etf|portfolio|equities|stocks?)", "energy"),
    (r"\b(?:health\s*care|biotech|pharmaceutical|medical)", "healthcare"),
    (r"\b(?:technology|tech\s+sector|software|semiconductor)", "technology"),
    (r"\b(?:financials?|bank(?:ing)?\s+sector|insurance\s+sector)", "financials"),
    (r"\b(?:utilit|infrastructure\s+equity)", "utilities"),
    (r"\b(?:consumer\s+(?:discretion|staples)|retail\s+sector)", "consumer"),
    (r"\b(?:industrial(?:s)?|transportation|aerospace)", "industrials"),
    (r"\b(?:materials\s+sector|chemicals\s+equity|metals\s+&\s+mining)", "materials"),
    (r"\bcommunic|media\s+sector|telecom", "communications"),
]
for pattern, sector_name in sector_patterns:
    if re.search(pattern, name, re.IGNORECASE):
        return ("Sector Equity", f"name:sector:{sector_name}")
```

**Layer 1 (description):**
```python
# Before size+style in _classify_from_description:
if re.search(
    r"invests?\s+(?:primarily|at\s+least\s+\d+%)\s+.*"
    r"(?:energy|health\s*care|technology|financial|utilit|"
    r"consumer|industrial|material|telecom)\s+(?:sector|compan|stocks|equit)",
    text,
):
    # Match but defer to name regex for sector specificity (lineage source is name)
    return ("Sector Equity", "desc:sector_equity")
```

### 5. Patch 4 — Mortgage-Backed / Asset-Backed Securities

**Layer 1 (description), BEFORE Structured Credit / CLO:**
```python
# Mortgage-Backed Securities (agency + non-agency)
if re.search(
    r"mortgage[- ]backed\s+secur|"
    r"\bMBS\b|\bCMBS\b|"
    r"agency\s+mortgage|residential\s+mortgage",
    text,
):
    return ("Mortgage-Backed Securities", "desc:mbs")

# Asset-Backed Securities (non-mortgage)
if re.search(
    r"asset[- ]backed\s+secur|"
    r"\bABS\b(?!\s+CAPITAL)|"  # Avoid false-match on firm names containing "ABS Capital"
    r"(?:auto|credit\s+card|student\s+loan)[- ]backed",
    text,
):
    return ("Asset-Backed Securities", "desc:abs")
```

**Layer 2 (name):**
```python
# Before Real Estate (MBS can confuse with "mortgage real estate")
if re.search(
    r"mortgage[- ]backed|"
    r"\bMBS\s+(?:fund|portfolio|strateg)|"
    r"\bCMBS\b|"
    r"(?:agency|residential|commercial)\s+mortgage\s+(?:secur|bond)",
    name, re.IGNORECASE,
):
    return ("Mortgage-Backed Securities", "name:mbs")

if re.search(
    r"asset[- ]backed\s+secur|"
    r"\bABS\s+(?:fund|portfolio|strateg)|"
    r"(?:auto|consumer)[- ]backed\s+loan",
    name, re.IGNORECASE,
):
    return ("Asset-Backed Securities", "name:abs")
```

### 6. Patch 5 — Long leverage (2x, 3x) ETF patterns

**Current:** Only `-[123]x` (inverse) detected.

**Layer 2 (name):**
```python
# BEFORE the inverse/short block, handle long leverage
# 2x, 3x, ultra, daily bull = positive leverage
if re.search(r"\b(?:2x|3x|ultra|daily\s+(?:bull|long))\b(?!\s*-)", name, re.IGNORECASE):
    # Strip leverage keyword and recurse on underlying
    stripped = re.sub(
        r"\b(?:2x|3x|ultra|daily\s+(?:bull|long))\b",
        "", name,
    ).strip()
    if stripped and stripped != name:
        sub_result = _classify_from_name(stripped, fund_type)
        if sub_result is not None:
            return (sub_result[0], f"name:leveraged:{sub_result[1]}")
```

Note: Direction (long leverage vs short/inverse) is preserved in lineage via `matched_pattern`, not as a separate label. The underlying asset class drives the classification.

### 7. Patch 6 — ESG / Sustainable patterns

**Layer 1 (description):**
```python
# ESG detection — determine if equity or bond based on other content in description
if re.search(
    r"(?:environmental.{0,15}social.{0,15}governance|"
    r"\bESG\b|sustainable\s+invest|"
    r"impact\s+invest|socially\s+responsible)",
    text,
):
    # Determine asset class from context
    if re.search(r"\b(?:bond|fixed[- ]income|debt|credit)\b", text):
        return ("ESG/Sustainable Bond", "desc:esg_bond")
    if re.search(r"\b(?:equit|stocks?|shares?|companies)\b", text):
        return ("ESG/Sustainable Equity", "desc:esg_equity")
    # Default to equity if ambiguous (most ESG funds are equity)
    return ("ESG/Sustainable Equity", "desc:esg_ambiguous")
```

**Layer 2 (name):**
```python
# ESG detection in name — similar dual-label approach
if re.search(r"\b(?:ESG|sustainable|sustainability|responsible\s+invest|SRI|impact)\b", name, re.IGNORECASE):
    if re.search(r"\b(?:bond|fixed[- ]income|debt|credit)\b", name, re.IGNORECASE):
        return ("ESG/Sustainable Bond", "name:esg_bond")
    return ("ESG/Sustainable Equity", "name:esg_equity")
```

### 8. Patch 7 — European bonds + European equity (ESMA)

**Layer 1 (description):**
```python
# European bonds (before generic Government/Corporate)
if re.search(
    r"(?:european|euro(?:pean|zone)|eu|germany|france|italy|spain|uk|united\s+kingdom)\s+"
    r"(?:government|sovereign|corporate)\s+(?:bond|debt|securit)",
    text,
):
    return ("European Bond", "desc:european_bond")

# European equity
if re.search(
    r"(?:european|euro(?:pean|zone)|eu)\s+(?:equit|stocks?|compan|shares?)|"
    r"(?:germany|france|italy|spain|uk|united\s+kingdom)\s+(?:equit|compan|stocks?)",
    text,
):
    return ("European Equity", "desc:european_equity")
```

**Layer 2 (name):**
```python
# European bonds (before generic Government Bond)
if re.search(
    r"\beuropean\s+(?:bond|fixed|debt|credit|sovereign|corporate)",
    name, re.IGNORECASE,
):
    return ("European Bond", "name:european_bond")

# European equity (before generic International Equity)
if re.search(
    r"\beuropean\s+(?:equit|stock|company|compan|share)|"
    r"\beuro(?:pean|zone)\s+(?:equit|stock|index)|"
    r"\b(?:europe|euro\s*stoxx)\b",
    name, re.IGNORECASE,
):
    return ("European Equity", "name:european_equity")
```

### 9. Patch 8 — Asian equity + Emerging Markets Debt

**Layer 1 (description):**
```python
# Emerging Markets Debt (before generic EM Equity or IG Bond)
if re.search(
    r"emerging\s+market(?:s)?\s+(?:debt|bond|fixed[- ]income|sovereign|corporate\s+bond)",
    text,
):
    return ("Emerging Markets Debt", "desc:em_debt")

# Asian equity
if re.search(
    r"\basia(?:n|[- ]pacific)?\s+(?:equit|stocks?|compan|shares?)|"
    r"\b(?:china|japan|korea|taiwan|singapore|hong\s+kong|india)\s+(?:equit|stocks?|compan)",
    text,
):
    return ("Asian Equity", "desc:asian_equity")
```

**Layer 2 (name):**
```python
# Emerging Markets Debt (before generic EM Equity)
if re.search(
    r"emerging\s+market(?:s)?\s+(?:debt|bond|fixed|sovereign|corporate)|"
    r"\bEM\s+(?:debt|bond|sovereign)",
    name, re.IGNORECASE,
):
    return ("Emerging Markets Debt", "name:em_debt")

# Asian equity (before generic International)
if re.search(
    r"\basia(?:n|[- ]pacific)?\s+(?:equit|stock|compan)|"
    r"\b(?:china|japan|korea|taiwan|singapore|hong\s+kong|india)\s+(?:equit|stock|compan|fund)",
    name, re.IGNORECASE,
):
    return ("Asian Equity", "name:asian_equity")
```

---

## TESTS

### New test file: `backend/tests/domains/wealth/services/test_strategy_classifier_round2.py`

```python
"""Regression tests for Round 2 classifier patches."""
import pytest
from app.domains.wealth.services.strategy_classifier import (
    classify_fund,
    STRATEGY_LABELS,
)


class TestTaxonomyExpansion:
    @pytest.mark.parametrize("label", [
        "European Equity", "Asian Equity", "ESG/Sustainable Equity",
        "European Bond", "Emerging Markets Debt", "ESG/Sustainable Bond",
        "Mortgage-Backed Securities", "Asset-Backed Securities",
        "Convertible Securities",
    ])
    def test_new_label_in_taxonomy(self, label):
        assert label in STRATEGY_LABELS

    def test_taxonomy_has_47_labels(self):
        assert len(STRATEGY_LABELS) == 47


class TestLongShortUCITS:
    """CRITICAL BUG FIX: Long/Short gate was limited to hedge fund_type."""

    def test_ucits_long_short_equity(self):
        """ESMA UCITS Long/Short fund should be Long/Short Equity despite fund_type=UCITS."""
        result = classify_fund(
            fund_name="Pictet Long Short Global Equity",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Long/Short Equity"

    def test_hedge_fund_long_short_still_works(self):
        result = classify_fund(
            fund_name="Bridgewater Long/Short Equity Fund",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Long/Short Equity"

    def test_long_short_in_description(self):
        result = classify_fund(
            fund_name="Global Alpha Fund",
            fund_type="UCITS",
            tiingo_description="employs a long-short equity strategy with paired positions in US and European markets",
        )
        assert result.strategy_label == "Long/Short Equity"


class TestConvertibleSecurities:
    def test_columbia_convertible_securities(self):
        result = classify_fund(
            fund_name="Columbia Convertible Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Securities"

    def test_franklin_convertible(self):
        result = classify_fund(
            fund_name="Franklin Convertible Securities",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Securities"

    def test_hedge_fund_convertible_arbitrage_still_works(self):
        """Hedge fund context preserved for Convertible Arbitrage."""
        result = classify_fund(
            fund_name="Marathon Convertible Arbitrage",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Arbitrage"


class TestSectorEquity:
    @pytest.mark.parametrize("name,expected_sector", [
        ("Fidelity Select Energy Portfolio", "energy"),
        ("Vanguard Health Care ETF", "healthcare"),
        ("First Trust Technology Dividend", "technology"),
        ("iShares Global Financials ETF", "financials"),
        ("Utilities Select Sector SPDR", "utilities"),
        ("Consumer Discretionary Select Sector", "consumer"),
        ("Industrial Select Sector SPDR", "industrials"),
    ])
    def test_sector_etf(self, name, expected_sector):
        result = classify_fund(
            fund_name=name,
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Sector Equity"
        assert expected_sector in (result.matched_pattern or "")


class TestMortgageAndAssetBacked:
    def test_pimco_mortgage_securities(self):
        result = classify_fund(
            fund_name="PIMCO Mortgage-Backed Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Mortgage-Backed Securities"

    def test_cmbs_fund(self):
        result = classify_fund(
            fund_name="BlackRock CMBS Opportunity Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Mortgage-Backed Securities"

    def test_asset_backed_securities(self):
        result = classify_fund(
            fund_name="TCW Asset-Backed Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asset-Backed Securities"

    def test_abs_capital_firm_not_abs_fund(self):
        """Firm name 'ABS Capital' should not trigger ABS classification."""
        result = classify_fund(
            fund_name="ABS Capital Partners Growth Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        # Should classify as PE, not ABS
        assert result.strategy_label == "Private Equity"

    def test_mortgage_real_estate_still_real_estate(self):
        """Round 1 regression: Mortgage Real Estate ETF stays as Real Estate."""
        result = classify_fund(
            fund_name="iShares Mortgage Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"


class TestLongLeverageETFs:
    def test_proshares_ultra_sp500(self):
        """ProShares Ultra S&P 500 is 2x S&P 500 — should classify underlying."""
        result = classify_fund(
            fund_name="ProShares Ultra S&P 500",
            fund_type="ETF",
            tiingo_description=None,
        )
        # Underlying is Large Blend (S&P 500)
        assert result.strategy_label == "Large Blend"
        assert "leveraged" in (result.matched_pattern or "")

    def test_direxion_daily_3x_bull(self):
        result = classify_fund(
            fund_name="Direxion Daily Financial Bull 3X Shares",
            fund_type="ETF",
            tiingo_description=None,
        )
        # Underlying is Financials sector
        assert result.strategy_label == "Sector Equity"
        assert "leveraged" in (result.matched_pattern or "")

    def test_inverse_still_works(self):
        """Round 1 regression: inverse ETFs still classify underlying."""
        result = classify_fund(
            fund_name="ProShares Short Real Estate",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"
        assert "short" in (result.matched_pattern or "")


class TestESGSustainable:
    def test_blackrock_sustainable_equity(self):
        result = classify_fund(
            fund_name="BlackRock Sustainable Advantage Large Cap Core",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"

    def test_vanguard_esg_etf(self):
        result = classify_fund(
            fund_name="Vanguard ESG U.S. Stock ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"

    def test_esg_bond_fund(self):
        result = classify_fund(
            fund_name="iShares ESG Aware U.S. Aggregate Bond ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Bond"

    def test_sri_fund(self):
        result = classify_fund(
            fund_name="Parnassus Core SRI Equity Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"


class TestEuropeanBondAndEquity:
    def test_european_bond_fund(self):
        result = classify_fund(
            fund_name="Fidelity European Bond Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Bond"

    def test_european_sovereign(self):
        result = classify_fund(
            fund_name="BlackRock European Sovereign",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Bond"

    def test_european_equity(self):
        result = classify_fund(
            fund_name="Fidelity European Equity Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Equity"

    def test_eurozone_equity(self):
        result = classify_fund(
            fund_name="Lyxor EuroZone Equity",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Equity"


class TestAsianEquityAndEMDebt:
    def test_asian_equity_fund(self):
        result = classify_fund(
            fund_name="Matthews Asian Growth Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_china_equity(self):
        result = classify_fund(
            fund_name="Invesco China Focus Equity Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_japan_equity(self):
        result = classify_fund(
            fund_name="Fidelity Japan Smaller Companies",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_em_debt_fund(self):
        result = classify_fund(
            fund_name="PIMCO Emerging Markets Debt Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Debt"

    def test_em_equity_still_works(self):
        """Round 1 regression: EM Equity patterns still work when name has 'equity'."""
        result = classify_fund(
            fund_name="DFA Emerging Markets Equity Portfolio",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Equity"


class TestNoRegressions:
    """Ensure Round 1 + existing tests still pass."""

    def test_goldman_still_not_precious_metals(self):
        result = classify_fund(
            fund_name="GOLDMAN SACHS TRUST - LARGE CAP GROWTH FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"

    def test_credit_allocation_still_balanced(self):
        result = classify_fund(
            fund_name="Credit Allocation Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Balanced"

    def test_pe_secondaries_still_works(self):
        result = classify_fund(
            fund_name="Apollo Private Equity Secondaries Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "secondaries" in (result.matched_pattern or "")

    def test_structured_credit_still_works(self):
        result = classify_fund(
            fund_name="BATTALION CLO XVI",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_tax_free_still_municipal(self):
        result = classify_fund(
            fund_name="Franklin California Intermediate-Term Tax-Free Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Municipal Bond"

    def test_hedge_generic_fallback_preserved(self):
        result = classify_fund(
            fund_name="Generic Alpha Partners",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label in ("Multi-Strategy", "Hedge Fund")
```

---

## VERIFICATION

1. `make lint` passes.
2. `make typecheck` passes.
3. `make test` passes — all Round 1 + Round 2 tests green.
4. Re-run the staging worker:
   ```python
   import asyncio
   from app.domains.wealth.workers.strategy_reclassification import run_strategy_reclassification
   result = asyncio.run(run_strategy_reclassification())
   ```

5. Validate new labels appear in stage table:
   ```sql
   SELECT proposed_strategy_label, COUNT(*)
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>'
     AND proposed_strategy_label IN (
       'European Equity', 'Asian Equity', 'ESG/Sustainable Equity',
       'European Bond', 'Emerging Markets Debt', 'ESG/Sustainable Bond',
       'Mortgage-Backed Securities', 'Asset-Backed Securities',
       'Convertible Securities', 'Long/Short Equity'
     )
   GROUP BY proposed_strategy_label
   ORDER BY COUNT(*) DESC;
   ```

6. Check `lost_class` decrease:
   ```sql
   SELECT source_table, COUNT(*) AS lost_class
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>'
     AND current_strategy_label IS NOT NULL
     AND proposed_strategy_label IS NULL
   GROUP BY source_table
   ORDER BY lost_class DESC;
   ```

Expected: `lost_class` drops from 13,409 to 6,000-8,000. ESMA `lost_class` should drop most (from 5,248 to ~2,000).

7. Verify no regressions on top-performing firms:
   ```sql
   -- PIMCO funds should classify (not fallback)
   SELECT proposed_strategy_label, COUNT(*)
   FROM strategy_reclassification_stage s
   JOIN sec_manager_funds f ON s.source_pk = f.id::text
   JOIN sec_managers m ON f.crd_number = m.crd_number
   WHERE s.run_id = '<NEW_RUN_ID>'
     AND m.firm_name ILIKE '%PIMCO%'
   GROUP BY proposed_strategy_label;
   ```

---

## INTERPRETING THE OUTPUT

**If `lost_class` on ESMA drops to <1,000:** Round 2 succeeded for ESMA coverage.

**If Sector Equity count is <200:** Sector patterns may need expansion. Inspect fallback samples for sector ETFs not caught.

**If Long/Short Equity UCITS count is 0:** Patch 1 didn't fire correctly. Check that the gate removal actually lets the pattern execute outside the hedge block.

**If ESG counts are dominated by ESG/Sustainable Equity (>90%):** Bond detection context check may be too strict. Inspect samples of funds with "ESG" + "Bond" in name.

---

## ANTI-PATTERNS

- Do NOT auto-apply any staged labels. Session B gate still applies.
- Do NOT remove `Convertible Arbitrage` — hedge-gated variant still needed.
- Do NOT rename existing labels. Only ADD.
- Do NOT use LLM fallback. Regex/keyword only.
- Do NOT add more patterns without tests. Every new pattern has at least one test.
- Do NOT merge without re-running worker and validating new label counts.

---

## OUT OF SCOPE

- **Additional Tiingo enrichment for SEC tables** — Phase 1.5 sprint
- **N-PORT holdings-based classification** — Phase 4
- **Round 3 patches** — only if empirical samples after Round 2 reveal new concentration
- **Renaming/reorganizing taxonomy** — taxonomy is additive only
- **Session B apply gate** — depends on Round 2 numbers stabilizing first
