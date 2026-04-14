# Fund Classifier — Patches Round 1 (Pre-Session B Calibration)

**Date:** 2026-04-14
**Branch:** `fix/classifier-patches-round1`
**Sessions:** 1
**Depends on:** PR #168 merged (cascade classifier + staging table live)

---

## Context

The cascade classifier shipped in PR #168 ran against 84,212 rows in the staging table. Empirical results revealed 4 critical blind spots and regressions vs the legacy classifier:

| Issue | Symptom | Impact |
|---|---|---|
| `tax-free` not in Municipal pattern | "Franklin California Intermediate-Term Tax-Free Income Fund" → Intermediate-Term Bond | Regression: lost Municipal Bond classification |
| Government pattern too strict (`\bgovernment\s+bond`) | "Limited Term U.S. Government Fund" → fallback | Government bond funds missed |
| PE substrategies collapsing | 26,821 rows labeled "Private Equity" hiding Secondaries, Co-Invest, Growth Equity, Infrastructure | Loss of granularity vs legacy |
| CLO → generic Private Credit | "BATTALION CLO", "VOYA CLO" → Private Credit | Less useful for FI analytics |
| Hedge fund → NULL when no substrategy match | 5,147 rows lost "Hedge Fund" label | Regression: generic bucket disappeared |
| Style without size → fallback | "Vanguard Selected Value Fund" falls through | Bare Value/Growth funds not classified |

Rationale for fixing NOW (before Session B):
- Re-running the worker after patches gives empirical numbers that calibrate the severity matrix in Session B correctly
- Avoids writing Session B twice (once against noisy data, once against clean data)
- Each patch has a test, preventing regressions in round 2

Decisions NOT to address in round 1 (explicitly deferred):
- **Sector Equity keyword map** (Health, Tech, Energy, etc.) — too many fragile mappings. N-PORT holdings (Phase 4) resolves this canonically
- **ESG Fixed Income** — ESG is orthogonal to strategy. Separate sprint, separate attribute `attributes.esg_flag`
- **Additional Tiingo enrichment for SEC tables** — separate Phase 1.5 sprint

---

## OBJECTIVE

Apply targeted patches to `backend/app/domains/wealth/services/strategy_classifier.py` that fix 6 documented regressions, add "Structured Credit" to taxonomy, and prevent the `lost_class` category from dominating future diffs.

Re-run the staging worker after patches and verify the 4 top blind spots are resolved.

---

## CONSTRAINTS

- **Additive only.** No existing tests should regress. All 14 existing tests must still pass.
- **Pure function changes.** No DB, route, or schema changes. Only edits to `strategy_classifier.py`.
- **Tests first.** Every patch has a regression test BEFORE the fix lands.
- **Keep deterministic.** No LLM, no heuristic probability. Regex + keyword.
- **Preserve taxonomy.** Add only "Structured Credit" to `STRATEGY_LABELS` set. Existing 37 labels stay.

---

## DELIVERABLES

### 1. Add "Structured Credit" to `STRATEGY_LABELS`

File: `backend/app/domains/wealth/services/strategy_classifier.py`

In the `STRATEGY_LABELS` set (around line 35-70 depending on current state):

```python
# Under "Private / Alts" section, ADD:
"Structured Credit",
```

Verify total count goes from 37 to 38.

### 2. Patch 1 — `tax-free` into Municipal Bond pattern

Both in `_classify_from_description()` (Layer 1) and `_classify_from_name()` (Layer 2).

**Layer 1 (description):**
```python
# Current:
if re.search(r"municipal\s+bonds?|muni\s+(?:bonds?|debt)|tax[- ]exempt", text):
    return ("Municipal Bond", "desc:municipal")

# Patched:
if re.search(r"municipal\s+bonds?|muni\s+(?:bonds?|debt)|tax[- ]exempt|tax[- ]free", text):
    return ("Municipal Bond", "desc:municipal")
```

**Layer 2 (name):**
```python
# Current:
if re.search(r"\bmunicipal\b|\bmuni\b|tax[- ]exempt", name):
    return ("Municipal Bond", "name:municipal")

# Patched:
if re.search(r"\bmunicipal\b|\bmuni\b|tax[- ]exempt|tax[- ]free", name):
    return ("Municipal Bond", "name:municipal")
```

### 3. Patch 2 — Government bond pattern expansion

Both Layer 1 and Layer 2.

**Layer 1 (description):**
```python
# Current:
if re.search(r"treasury\s+(?:bonds?|notes?|securities)|government\s+bonds?", text):
    return ("Government Bond", "desc:government_bond")

# Patched:
if re.search(
    r"treasury\s+(?:bonds?|notes?|securities)|"
    r"government\s+(?:bonds?|securities|obligations|debt)|"
    r"\bus\s+government\b|\bu\.s\.\s+government\b",
    text,
):
    return ("Government Bond", "desc:government_bond")
```

**Layer 2 (name):**
```python
# Current:
if re.search(r"\btreasury\b|\bgovernment\s+bond", name):
    return ("Government Bond", "name:government")

# Patched:
if re.search(
    r"\btreasury\b|"
    r"\bgovernment\s+(?:bond|fund|securities|obligations|portfolio)",
    name,
):
    return ("Government Bond", "name:government")
```

### 4. Patch 3 — PE substrategy detection

Add granular PE detection BEFORE the generic `fund_type:pe` fallback.

**Layer 2 (name), in the private funds default block:**

```python
# Current:
if fund_type:
    ft = fund_type.lower()
    if "private equity" in ft: return ("Private Equity", "fund_type:pe")
    if "venture" in ft: return ("Venture Capital", "fund_type:vc")
    if "real estate" in ft: return ("Real Estate", "fund_type:re")
    if "securitized" in ft: return ("Private Credit", "fund_type:securitized")

# Patched:
if fund_type:
    ft = fund_type.lower()
    if "private equity" in ft:
        # PE substrategy detection BEFORE generic fallback
        if re.search(r"\bsecondar(?:y|ies|y\s+fund)\b", name):
            return ("Private Equity", "name:pe_secondaries")  # keeps PE label but with lineage
        if re.search(r"\bco[- ]invest", name):
            return ("Private Equity", "name:pe_coinvest")
        if re.search(r"\bgrowth\s+equit", name):
            return ("Private Equity", "name:pe_growth")
        if re.search(r"\binfrastructure", name):
            return ("Infrastructure", "name:pe_infra")
        return ("Private Equity", "fund_type:pe")
    if "venture" in ft: return ("Venture Capital", "fund_type:vc")
    if "real estate" in ft: return ("Real Estate", "fund_type:re")
    if "securitized" in ft:
        # CLO detection BEFORE generic securitized fallback
        if re.search(r"\bclo\b|collateralized\s+loan", name):
            return ("Structured Credit", "name:clo")
        return ("Private Credit", "fund_type:securitized")
```

**Note:** Secondaries/Co-Invest/Growth stay as "Private Equity" (the high-level label) but with distinct `matched_pattern` for lineage. Infrastructure gets promoted to its own label since it already exists in the taxonomy.

### 5. Patch 4 — Hedge fund fallback preserves generic bucket

Currently, `_classify_from_name()` returns `None` for hedge funds that don't match any specific pattern after the hedge block. This caused 5,147 rows to lose their "Hedge Fund" label.

**Layer 2 (name):**
```python
# Current (end of hedge block):
if fund_type and "hedge" in fund_type.lower():
    if re.search(r"long[/-]short", name): return ("Long/Short Equity", "name:long_short")
    # ... other hedge patterns ...
    return ("Multi-Strategy", "name:hedge_generic")  # Default for hedge

# This is already correct! Verify the code matches this.
```

**Verification:** If the current code lacks the final `return ("Multi-Strategy", "name:hedge_generic")`, ADD IT. The prompt originally specified this but the implementation may have regressed.

If `fund_type='Hedge Fund'` exists as a label in the current taxonomy and legacy classifier used it, consider preserving it:

```python
# Option A: Multi-Strategy default (current prompt)
return ("Multi-Strategy", "name:hedge_generic")

# Option B: Preserve Hedge Fund generic bucket
# Check STRATEGY_LABELS — is "Hedge Fund" in there?
# If yes: return ("Hedge Fund", "name:hedge_generic")
# If no: keep Multi-Strategy
```

**Decision:** Use Option B if "Hedge Fund" is in `STRATEGY_LABELS`. Otherwise Multi-Strategy. Check taxonomy.

### 6. Patch 5 — Style without size defaults to Large

**Layer 2 (name):**

```python
# After the size+style blocks, ADD a style-only fallback:

# Current:
if is_large:
    # ... large blocks ...
if is_mid:
    # ... mid blocks ...
if is_small:
    # ... small blocks ...

# After the small block, ADD:
# Style without size → default to Large (most common for retail funds)
if is_growth:
    return ("Large Growth", "name:style_only_growth")
if is_value:
    return ("Large Value", "name:style_only_value")
```

This catches "Vanguard Selected Value Fund", "Dodge & Cox Growth", etc.

### 7. Patch 6 — CLO / Structured Credit (Layer 1 AND Layer 2)

Already partially covered in Patch 3 (Layer 2 via securitized fund_type). Also add to Layer 1 for funds with Tiingo descriptions mentioning CLO.

**Layer 1 (description), add BEFORE Private Credit patterns:**

```python
# ── Structured Credit / CLO (specific, before Private Credit) ──
if re.search(
    r"\bcollateralized\s+loan\s+obligation|"
    r"\bclo\b|"
    r"\bcdo\b|"
    r"securitized\s+credit|"
    r"structured\s+credit",
    text,
):
    return ("Structured Credit", "desc:clo")
```

**Layer 2 (name), add as standalone check before fund_type block:**

```python
# Early check — CLO in fund name regardless of fund_type
if re.search(r"\bclo\b|collateralized\s+loan", name):
    return ("Structured Credit", "name:clo")
```

---

## TESTS

### New test file: `backend/tests/domains/wealth/services/test_strategy_classifier_patches.py`

```python
"""Regression tests for classifier patches round 1."""
import pytest
from app.domains.wealth.services.strategy_classifier import (
    classify_fund,
    STRATEGY_LABELS,
)


class TestTaxonomyExpansion:
    def test_structured_credit_in_taxonomy(self):
        assert "Structured Credit" in STRATEGY_LABELS


class TestTaxFreeMunicipal:
    def test_franklin_california_tax_free(self):
        result = classify_fund(
            fund_name="Franklin California Intermediate-Term Tax-Free Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Municipal Bond"

    def test_tax_free_in_description(self):
        result = classify_fund(
            fund_name="Generic Income Fund",
            fund_type="Mutual Fund",
            tiingo_description="invests at least 80% of its assets in tax-free municipal obligations",
        )
        assert result.strategy_label == "Municipal Bond"


class TestGovernmentBondPatterns:
    def test_limited_term_us_government_fund(self):
        result = classify_fund(
            fund_name="Limited Term U.S. Government Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_integrity_short_term_government(self):
        result = classify_fund(
            fund_name="Integrity Short Term Government Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_government_securities_fund(self):
        result = classify_fund(
            fund_name="Pioneer Government Securities",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_government_obligations(self):
        result = classify_fund(
            fund_name="BlackRock Government Obligations Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"


class TestPESubstrategies:
    def test_secondaries_fund(self):
        result = classify_fund(
            fund_name="Apollo Global Private Equity Secondaries Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "secondaries" in (result.matched_pattern or "")

    def test_coinvest_fund(self):
        result = classify_fund(
            fund_name="Blackstone Co-Invest Partners",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "coinvest" in (result.matched_pattern or "")

    def test_growth_equity_fund(self):
        result = classify_fund(
            fund_name="General Atlantic Growth Equity Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "growth" in (result.matched_pattern or "")

    def test_infrastructure_pe(self):
        result = classify_fund(
            fund_name="KKR Global Infrastructure Investors",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Infrastructure"


class TestStructuredCredit:
    def test_battalion_clo(self):
        result = classify_fund(
            fund_name="BATTALION CLO XVI",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_voya_clo(self):
        result = classify_fund(
            fund_name="VOYA CLO 2020-1",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_clo_in_description(self):
        result = classify_fund(
            fund_name="Generic Fund",
            fund_type="Mutual Fund",
            tiingo_description="invests in collateralized loan obligations and other structured credit instruments",
        )
        assert result.strategy_label == "Structured Credit"

    def test_cdo_in_description(self):
        result = classify_fund(
            fund_name="Generic Fund",
            fund_type="Mutual Fund",
            tiingo_description="invests primarily in CDOs and CLOs",
        )
        assert result.strategy_label == "Structured Credit"


class TestStyleWithoutSize:
    def test_vanguard_selected_value(self):
        result = classify_fund(
            fund_name="Vanguard Selected Value Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Value"
        assert "style_only" in (result.matched_pattern or "")

    def test_dodge_and_cox_growth(self):
        result = classify_fund(
            fund_name="Dodge & Cox Growth Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"

    def test_generic_value_fund(self):
        result = classify_fund(
            fund_name="American Century Value Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Value"


class TestHedgeFallback:
    def test_hedge_fund_with_no_substrategy_match(self):
        """Hedge fund with no specific pattern should NOT return NULL.

        Legacy classifier assigned "Hedge Fund" or generic bucket.
        New classifier must preserve this via Multi-Strategy or Hedge Fund label.
        """
        result = classify_fund(
            fund_name="Generic Alpha Partners",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label is not None
        # Either Multi-Strategy (default) or Hedge Fund (if in taxonomy)
        assert result.strategy_label in ("Multi-Strategy", "Hedge Fund")


class TestNoRegressions:
    """Ensure existing 14 tests still pass with patches applied."""
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

    def test_pgim_real_estate_income_still_real_estate(self):
        result = classify_fund(
            fund_name="PGIM Real Estate Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"
```

---

## VERIFICATION

1. `make lint` passes.
2. `make typecheck` passes.
3. `make test` passes with ALL tests green (14 old + new tests for each patch).
4. Re-run the staging worker against the catalog:
   ```bash
   python -c "
   import asyncio
   from app.domains.wealth.workers.strategy_reclassification import run_strategy_reclassification
   result = asyncio.run(run_strategy_reclassification())
   print(result)
   "
   ```
5. Compare the diff table between old `run_id` and new `run_id`:
   ```sql
   -- Count lost_class rows (current non-null → proposed NULL)
   -- BEFORE patches: 14,178
   -- AFTER patches: should be significantly lower (expect <5,000)
   SELECT COUNT(*) AS lost_class_count
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>'
     AND current_strategy_label IS NOT NULL
     AND proposed_strategy_label IS NULL;
   
   -- Count Municipal Bond (should increase from baseline — includes tax-free now)
   SELECT COUNT(*) 
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>' AND proposed_strategy_label = 'Municipal Bond';
   
   -- Count Government Bond (should increase)
   SELECT COUNT(*)
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>' AND proposed_strategy_label = 'Government Bond';
   
   -- Count Structured Credit (new label, should be >0)
   SELECT COUNT(*)
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>' AND proposed_strategy_label = 'Structured Credit';
   
   -- Count by matched_pattern for PE substrategies
   SELECT matched_pattern, COUNT(*)
   FROM strategy_reclassification_stage
   WHERE run_id = '<NEW_RUN_ID>' 
     AND proposed_strategy_label IN ('Private Equity', 'Infrastructure')
   GROUP BY matched_pattern
   ORDER BY COUNT(*) DESC;
   ```

6. Report back with:
   - New lost_class count vs 14,178 baseline
   - New Municipal Bond / Government Bond / Structured Credit counts
   - PE substrategy distribution
   - Top 20 still-in-fallback samples (candidates for round 2 patches or Phase 4 N-PORT)

---

## ANTI-PATTERNS

- Do NOT add Sector Equity keyword map. Deferred to Phase 4 (N-PORT holdings).
- Do NOT add ESG detection. Orthogonal dimension, separate sprint.
- Do NOT change the staging table schema. Pure classifier patches.
- Do NOT touch the worker, only the pure classifier module.
- Do NOT touch the 14 existing tests. Patches must not regress them.
- Do NOT add new Tiingo enrichment. That's Phase 1.5, separate sprint.
- Do NOT auto-apply any staged labels. Session B gate still applies.
