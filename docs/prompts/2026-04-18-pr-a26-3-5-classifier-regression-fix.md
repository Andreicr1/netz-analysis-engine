# PR-A26.3.5 — Classifier Regression Fix (3 Sessions)

**Date**: 2026-04-18
**Status**: P0 REGRESSION FIX — Round 2/2.5 classifier patches (PRs #173, #176) introduced greedy keyword patterns that mislabel institutional ETFs. SCHD/QQQM/SCHB/VMIAX/FJUL/AGG/XLF all confirmed mislabeled with `confidence=high` via empirical direct-run test 2026-04-18.
**Branch prefix**: `feat/pr-a26-3-5-classifier-*` (one branch per session)
**Predecessors merged**: A21–A26.3.3 full sequence, #167 Tiingo enrichment, #168/169/173/176 classifier cascade + patches, #174/175 apply gate, #220 authoritative-first refresh, #221 fuzzy bridge + sec_etfs backfill.

---

## Context — the regression, with evidence

Direct-run against current classifier (`backend/scripts/debug_classifier.py`, 2026-04-18):

| Ticker | Fund | Classifier output | Matched pattern | Should be |
|---|---|---|---|---|
| SCHD | Schwab U.S. Dividend Equity ETF | **Real Estate** (high) | `desc:real_estate:\breal\s+estate\s+(?:securities\|investment...` | Large Value / Dividend |
| QQQM | Invesco NASDAQ 100 ETF | **Real Estate** (high) | same pattern | Large Growth |
| SCHB | Schwab U.S. Broad Market ETF | **Cash Equivalent** (high) | `desc:cash` | Large Blend |
| VMIAX | Vanguard Materials Index Fund | **Precious Metals** (high) | `\bmining\s+(?:companies\|equities\|stocks)` | Sector Equity |
| FJUL | FT Vest U.S. Equity Buffer ETF | **Commodities** (high) | `desc:commodities:\bcommodit...` | Balanced / Defined Outcome |
| AGG | iShares Core U.S. Aggregate Bond | **Government Bond** (high) | `desc:government_bond` | Intermediate Core Bond |
| XLF | Financial Select Sector SPDR | **Real Estate** (high) | real_estate pattern | Sector Equity |
| SPY | SPDR S&P 500 ETF Trust | Large Blend ✓ | `name:large_blend` (Layer 2) | Large Blend ✓ |

**Root causes:**

1. **Description patterns are greedy.** They match ANY keyword appearance, not primary-intent phrases. Tiingo descriptions are rich and cite many asset classes. SCHD mentions "real estate securities" as an eligible holding within the Dow Jones Dividend 100 → classifier assumes fund IS real estate.
2. **Cascade ordering: Layer 1 (description) runs BEFORE Layer 2 (name regex).** Name contains less ambiguity ("Dividend Equity", "Broad Market", "NASDAQ 100") than long descriptions. SPY works because generic description falls through to name layer. SCHD/SCHB/QQQM fail because greedy description patterns fire first.
3. **Round 2/2.5 patches added patterns without context gates.** Coverage went up, precision went down.

---

## Strategy — 3 sessions, sequenced

Each session is a separate PR. Sessions build on each other but can merge independently.

- **Session 1 (P0, small):** explicit overrides table + seed ~40 canonical tickers + priority 0 in refresh_authoritative_labels.py. **Cheap, high-leverage — resolves 90% of visible contamination without touching classifier.**
- **Session 2 (P1, medium):** cascade re-order — Layer 2 name regex runs BEFORE Layer 1 description. Preserves existing patterns but changes priority. Fixes broad-market ETFs that have specific keywords in name.
- **Session 3 (P2, larger):** Round 3 pattern hardening — add context gates (`invest primarily`, `at least X%`, `tracks the ... index`) to real_estate / commodities / cash / government_bond / precious_metals description patterns.

Each session is independently valuable. Ship in order but evaluate empirical gain after each before committing to the next.

---

## Session 1 — Explicit overrides table + seed + priority 0

**Branch:** `feat/pr-a26-3-5-session-1-overrides`

### Scope

**In scope:**
- Migration 0158: `instrument_strategy_overrides (ticker, strategy_label, rationale, curated_by, curated_at)` table, global, no RLS.
- Seed migration with ~40 canonical institutional tickers (complete list in Section B below).
- Integration into `refresh_authoritative_labels.py` — add **priority 0** before sec_mmf. If ticker matches an override, use that label unconditionally.
- Audit — store `strategy_label_source = 'override'` when applied.
- Tests for priority ordering + override precedence.
- Regression: run refresh_authoritative_labels --apply, confirm SCHD/QQQM/SCHB/VMIAX/FJUL/AGG/XLF flip to correct labels.
- Post-apply smoke: run pr_a26_2_smoke.py, expect cash 5-15%, alt 10-20%, Sharpe 1.5-2.5.

**Out of scope:**
- Do NOT touch the classifier itself. Overrides bypass entirely.
- Do NOT build admin UI for override management — CLI / migration only in v1.
- Do NOT add fuzzy matching — exact ticker only.
- Do NOT override labels for non-equity tickers unless they appear in the seed list.

### Section A — Migration 0158 + table

**File:** `backend/app/core/db/migrations/versions/0158_instrument_strategy_overrides.py`

Down_revision: `0157_fuzzy_bridge_audit`.

```sql
CREATE TABLE instrument_strategy_overrides (
  ticker TEXT PRIMARY KEY,
  strategy_label TEXT NOT NULL,
  rationale TEXT NOT NULL,
  curated_by TEXT NOT NULL DEFAULT 'seed_migration',
  curated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

No RLS. Global lookup table. Reversible.

Include the ~40 seed rows as INSERTs in the same migration — explicit, auditable, reviewable in diff.

### Section B — Seed list (canonical institutional tickers)

Exact mapping. Every ticker MUST correspond to a `strategy_label` that is a key in `STRATEGY_LABEL_TO_BLOCKS` in `block_mapping.py`.

```python
SEED_OVERRIDES: dict[str, tuple[str, str]] = {
    # ── Equity US — Large Blend ──
    "SPY":  ("Large Blend", "SPDR S&P 500 ETF Trust"),
    "IVV":  ("Large Blend", "iShares Core S&P 500 ETF"),
    "VOO":  ("Large Blend", "Vanguard S&P 500 ETF"),
    "VTI":  ("Large Blend", "Vanguard Total Stock Market ETF"),
    "SCHB": ("Large Blend", "Schwab U.S. Broad Market ETF — regression fix, mislabeled Cash Equivalent"),
    "ITOT": ("Large Blend", "iShares Core S&P Total U.S. Stock Market ETF"),

    # ── Equity US — Large Growth ──
    "QQQ":  ("Large Growth", "Invesco QQQ Trust"),
    "QQQM": ("Large Growth", "Invesco NASDAQ 100 ETF — regression fix, mislabeled Real Estate"),
    "VUG":  ("Large Growth", "Vanguard Growth ETF"),
    "IWF":  ("Large Growth", "iShares Russell 1000 Growth ETF"),
    "SCHG": ("Large Growth", "Schwab U.S. Large-Cap Growth ETF"),

    # ── Equity US — Large Value ──
    "VTV":  ("Large Value", "Vanguard Value ETF"),
    "IWD":  ("Large Value", "iShares Russell 1000 Value ETF"),
    "SCHV": ("Large Value", "Schwab U.S. Large-Cap Value ETF"),
    "SCHD": ("Large Value", "Schwab U.S. Dividend Equity ETF — regression fix, mislabeled Real Estate"),

    # ── Equity US — Small/Mid ──
    "IWM":  ("Small Blend", "iShares Russell 2000 ETF"),
    "VB":   ("Small Blend", "Vanguard Small-Cap ETF"),
    "IJR":  ("Small Blend", "iShares Core S&P Small-Cap ETF"),
    "VO":   ("Mid-Cap Blend", "Vanguard Mid-Cap ETF"),

    # ── Equity DM (Europe / Asia) ──
    "EFA":  ("Foreign Large Blend", "iShares MSCI EAFE ETF — regression fix"),
    "VEA":  ("Foreign Large Blend", "Vanguard Developed Markets ETF"),
    "IEFA": ("Foreign Large Blend", "iShares Core MSCI EAFE ETF"),
    "VXUS": ("Foreign Large Blend", "Vanguard Total International Stock ETF"),
    "FEZ":  ("Europe Stock", "SPDR EURO STOXX 50 ETF — regression fix"),

    # ── Equity EM ──
    "EEM":  ("Diversified Emerging Mkts", "iShares MSCI Emerging Markets ETF"),
    "VWO":  ("Diversified Emerging Mkts", "Vanguard FTSE Emerging Markets ETF"),
    "IEMG": ("Diversified Emerging Mkts", "iShares Core MSCI Emerging Markets ETF"),

    # ── FI US Aggregate ──
    "AGG":  ("Intermediate Core Bond", "iShares Core U.S. Aggregate Bond ETF — regression fix, mislabeled Government Bond"),
    "BND":  ("Intermediate Core Bond", "Vanguard Total Bond Market ETF"),
    "SCHZ": ("Intermediate Core Bond", "Schwab U.S. Aggregate Bond ETF"),

    # ── FI US Treasury ──
    "TLT":  ("Long Government", "iShares 20+ Year Treasury Bond ETF"),
    "IEF":  ("Intermediate Government", "iShares 7-10 Year Treasury Bond ETF"),
    "SHY":  ("Short Government", "iShares 1-3 Year Treasury Bond ETF"),
    "GOVT": ("Intermediate Government", "iShares U.S. Treasury Bond ETF"),

    # ── FI TIPS / HY / IG ──
    "TIP":  ("Inflation-Protected Bond", "iShares TIPS Bond ETF"),
    "SCHP": ("Inflation-Protected Bond", "Schwab U.S. TIPS ETF"),
    "HYG":  ("High Yield Bond", "iShares iBoxx High Yield Corporate Bond ETF"),
    "JNK":  ("High Yield Bond", "SPDR Bloomberg High Yield Bond ETF"),
    "LQD":  ("Corporate Bond", "iShares iBoxx Investment Grade Corporate Bond ETF"),

    # ── Alt — Commodities / Gold ──
    "DBC":  ("Commodities Broad Basket", "Invesco DB Commodity Index Tracking Fund"),
    "GSG":  ("Commodities Broad Basket", "iShares S&P GSCI Commodity-Indexed Trust"),
    "GLD":  ("Precious Metals", "SPDR Gold Shares"),
    "IAU":  ("Precious Metals", "iShares Gold Trust"),

    # ── Alt — Real Estate ──
    "VNQ":  ("Real Estate", "Vanguard Real Estate ETF"),
    "SCHH": ("Real Estate", "Schwab U.S. REIT ETF"),

    # ── Sector Equity (regression fixes) ──
    "XLF":  ("Sector Equity", "Financial Select Sector SPDR Fund — regression fix, mislabeled Real Estate"),
    "XLE":  ("Sector Equity", "Energy Select Sector SPDR Fund"),
    "XLK":  ("Sector Equity", "Technology Select Sector SPDR Fund"),
    "XLV":  ("Sector Equity", "Health Care Select Sector SPDR Fund"),
    "VMIAX":("Sector Equity", "Vanguard Materials Index Fund — regression fix, mislabeled Precious Metals"),
}
```

Total: 48 entries. Verify every `strategy_label` value exists in `block_mapping.py` before migration. If any don't, add them to `block_mapping.py` in the same PR.

**FT Vest Buffer ETFs note:** FJUL, FAUG, FSEP, FOCT, FNOV, FDEC, FJAN, FFEB, FMAR, FAPR, FMAY, FJUN — all share the SPY-buffered structure. Instead of 12 entries, add one class-level override via a name-regex fallback *inside the override resolver* (see Section C). These are listed separately for documentation but not seeded individually to keep the table small.

### Section C — Integration into `refresh_authoritative_labels.py`

Modify the priority ladder:

```python
PRIORITY_LADDER = [
    ("override",       _resolve_override),        # NEW — priority 0
    ("sec_mmf",        _resolve_sec_mmf),
    ("sec_etf",        _resolve_sec_etf),
    ("sec_bdc",        _resolve_sec_bdc),
    ("esma_funds",     _resolve_esma),
    ("tiingo_cascade", _resolve_tiingo_cascade),
    ("needs_review",   _resolve_null),
]

async def _resolve_override(iu_row, db) -> str | None:
    """Priority 0: check instrument_strategy_overrides by ticker.
    Also applies FT Vest Buffer family regex (FJUL/FAUG/FSEP/...).
    """
    if not iu_row.ticker:
        return None
    # Exact lookup
    override = await db.execute(
        text("SELECT strategy_label FROM instrument_strategy_overrides WHERE ticker = :t"),
        {"t": iu_row.ticker},
    )
    if row := override.scalar_one_or_none():
        return row
    # Class-level FT Vest Buffer ETF family
    if re.match(r"^F(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)$", iu_row.ticker):
        return "Balanced"  # Defined-outcome, SPY-buffered — Balanced is closest canonical
    return None
```

On apply, set `iu.attributes.strategy_label_source = 'override'` so future audits recognize the path.

### Section D — Tests

- Unit test `test_override_priority.py` — seed an iu row with `ticker=SCHD`, assert refresh resolves to "Large Value" via override path despite sec_etfs having "Real Estate".
- Unit test FT Vest family — `ticker=FJUL` resolves to Balanced.
- Integration test — run `refresh_authoritative_labels.py --apply` against seed DB, assert backup rows created for changed tickers.
- Regression test — full override list applied produces zero validator warnings.

### Section E — Smoke validation

After migration + apply, run:

1. `python backend/scripts/debug_classifier.py` — unchanged (classifier not modified), still shows regression output.
2. Query `SELECT ticker, attributes->>'strategy_label', attributes->>'strategy_label_source' FROM instruments_universe WHERE ticker IN (<48 seed tickers>)`. Expect all tickers have `source='override'` and correct label.
3. `python backend/scripts/pr_a26_2_smoke.py` — propose → approve → realize for 3 profiles. Expected:
   - Cash: 5-15% (was 60%)
   - Alt: 10-20% (was 30-45%)
   - FI: 30-50%
   - Equity: 20-50%
   - Sharpe: 1.5-2.5 (was 3.2-3.8 inflated)
4. Paste complete allocation distribution by family in PR description.

### Section F — Runbook extension

Add section to `docs/reference/authoritative-label-refresh-runbook.md` describing override lifecycle:
- How to add a new override (SQL INSERT or manual migration).
- When to use overrides vs fixing classifier (classifier fix preferred for categorical issues; override preferred for single-ticker outliers).
- Review cadence (quarterly audit of overrides table, prune entries that classifier now handles correctly).

---

## Session 2 — Cascade Re-order (Name Before Description)

**Branch:** `feat/pr-a26-3-5-session-2-cascade-reorder`

### Scope

**In scope:**
- Modify `strategy_classifier.py` `classify_fund` to call `_classify_from_name` BEFORE `_classify_from_description` when both are available.
- Layer 0 (N-PORT holdings) stays first.
- New order: Layer 0 → Layer 2 (name) → Layer 1 (description) → Layer 3 (brochure) → fallback.
- Preserve all existing patterns (don't rewrite).
- Run full reclassification after the change to see empirical impact.
- Regression tests — all 30+ existing classifier tests must still pass (may need re-pinning some if they assumed old order).

**Out of scope:**
- Do NOT add new patterns. That's Session 3.
- Do NOT change the description patterns to be stricter. That's Session 3.
- Do NOT modify holdings classifier.

### Section A — Re-order

In `classify_fund`, swap the layer sequence. Document in code comment why (name is less ambiguous than description for broad-market ETFs).

### Section B — Tests

- Update `test_classify_fund_order.py` if exists — assert name-based label wins when both layers would match.
- Add regression test: SCHD with Tiingo description containing "real estate securities" but name "Dividend Equity ETF" → should resolve via name layer to Large Value (or whatever name pattern gives) rather than description layer Real Estate.
- Existing tests that depend on description-first ordering may need updates. Review each failing test and decide: was the test assertion capturing a bug (update test) or was it capturing intended behavior (need alternative fix)?

### Section C — Empirical validation

Before merge:
1. Re-run `refresh_local_reclassification.py` — compare distribution of proposed labels vs previous run.
2. Expected: Real Estate, Cash Equivalent, Commodities, Precious Metals counts DROP materially. Large Blend, Large Growth, Large Value, Sector Equity counts RISE.
3. Document changes in PR description.

### Section D — Session 1 overrides still win

After Session 2, the override table (priority 0) still takes precedence. Session 2 only affects the `tiingo_cascade` layer in `refresh_authoritative_labels.py`. Smoke test should show the same result as after Session 1 (overrides still authoritative).

---

## Session 3 — Round 3 Pattern Hardening (Context Gates)

**Branch:** `feat/pr-a26-3-5-session-3-context-gates`

### Scope

**In scope:**
- Audit of all "greedy" patterns in `strategy_classifier.py` that match asset-class keywords in description.
- Add context gates — patterns must match near primary-intent phrases:
  - `invest(?:s|ing)?\s+(?:primarily|at\s+least\s+\d+%|substantially)`
  - `tracks?\s+the\s+.*\s+(?:index|benchmark)`
  - `the\s+fund\'s\s+(?:investment\s+)?objective\s+is\s+to`
- Add negative gates:
  - If description also contains "broad market" or "total market" or "S&P 500" or "NASDAQ 100", don't fire narrow-asset-class patterns.
  - If fund_type is equity-primary, don't fire FI/Commodities/Cash patterns unless context gate is strong.
- Full regression test suite — all existing tests + new tests covering the specific regression cases (SCHD, QQQM, SCHB, VMIAX, FJUL, AGG, XLF).
- Empirical validation as in Session 2.

**Out of scope:**
- Do NOT remove any existing label from taxonomy.
- Do NOT change cascade ordering (that's Session 2).
- Do NOT modify holdings classifier.

### Section A — Pattern audit

Enumerate every pattern in `strategy_classifier.py` that fires on description:
- Real Estate (4 patterns)
- Precious Metals (4 patterns)
- Commodities (4 patterns)
- Government Bond (likely 1 pattern)
- Cash (likely 1 pattern)
- Round 2 additions: CMBS, MBS, ESG, Long/Short, Sector, European Bond, Asian Equity

For each, decide:
- Needs context gate (primary-intent required): most.
- Can stay as-is (highly specific keyword that rarely appears outside primary intent): few.

### Section B — Patch application

Rewrite each greedy pattern with context gate. Example:

**Before:**
```python
real_estate_patterns = (
    r"\breal\s+estate\s+(?:securities|investment|sector|companies|stocks?)",
    r"\breits?\b",
    ...
)
```

**After:**
```python
# Context-gated: pattern must match near primary-intent phrase
_PRIMARY_INTENT = r"(?:invest(?:s|ing)?\s+(?:primarily|at\s+least\s+\d+%|substantially)|tracks?\s+the\s+|the\s+fund\'s\s+(?:investment\s+)?objective\s+is|fund\s+(?:seeks|employs)\s+)"
real_estate_patterns = (
    rf"{_PRIMARY_INTENT}.*?\breal\s+estate\s+(?:securities|investment|sector|companies|stocks?)",
    r"\b(?:real\s+estate|reit)\s+(?:etf|fund|trust)\b",  # still allow name-form hits
    ...
)
```

Repeat for Precious Metals, Commodities, Government Bond, Cash, MBS, CMBS, etc.

### Section C — Tests

New test file `test_context_gated_patterns.py`:
- SCHD description → NOT Real Estate (context gate fails).
- VNQ description → Real Estate (context gate passes — VNQ description says "the fund invests primarily in real estate").
- AGG description → NOT Government Bond (aggregate mentions government bonds as part of mix, not primary).
- TLT description → Government Bond (primary intent is clear).
- VMIAX description → NOT Precious Metals (materials sector mentions mining as sub-component).

Each test names the specific ticker + asserts the expected non-regression behavior.

### Section D — Empirical validation + overrides review

After Session 3 merges:
1. Re-run `refresh_local_reclassification.py`.
2. Expected: distribution looks similar to Session 2 (since cascade is already re-ordered) but with fewer false positives in edge cases.
3. Review `instrument_strategy_overrides` table — entries now redundant (classifier handles them correctly) can be removed. Document in runbook.

---

## Global guardrails (all 3 sessions)

- `CLAUDE.md` rules. No new dependencies.
- `make check` green.
- Each session: one PR, 4-6 commits.
- Do NOT touch A26 frontend (PR #219 still draft).
- Do NOT touch optimizer, composition, propose/approve flows.

## Final report format (per session)

1. Migration (if any) up/down round-trip.
2. Test output.
3. Empirical validation:
   - Session 1: overrides applied, 48 tickers flipped, smoke distribution pasted.
   - Session 2: reclassification distribution comparison (before/after re-order).
   - Session 3: regression test output + reclassification distribution.
4. Specific regression table for SCHD/QQQM/SCHB/VMIAX/FJUL/AGG/XLF showing correct label post-session.
5. Deviations from spec.

## Sequencing guidance

- Session 1 can merge without Session 2/3 (it ships user-visible fix via overrides).
- Session 2 should merge after empirical validation that name-first ordering doesn't break other classifications.
- Session 3 can merge without Session 2 if preferred (independent patches) but Sessions 2+3 together are stronger than either alone.
- After all 3 sessions merge, re-evaluate `instrument_strategy_overrides` — entries that are now redundant can be pruned.
