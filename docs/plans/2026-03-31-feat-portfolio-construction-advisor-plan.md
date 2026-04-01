---
title: "feat: Portfolio Construction Advisor"
type: feat
status: active
date: 2026-03-31
deepened: 2026-03-31
---

# Portfolio Construction Advisor

## Enhancement Summary

**Deepened on:** 2026-03-31
**Sections enhanced:** 8
**Research agents used:** CVaR math, fund screening infra, overlap/correlation, model portfolio flow, greedy optimization theory, frontend UX patterns, documented learnings, Redis caching patterns

### Key Improvements
1. **Replace Cornish-Fisher with historical simulation CVaR** for the advisor (only ~15 evaluations — CF breaks at extreme levels like -84%)
2. **Brute-force search over greedy** for minimum viable set — C(15,5)=3003 is feasible; greedy is not optimal for CVaR (proven non-submodular)
3. **Recompute full (N+1)×(N+1) covariance** over common date window instead of augmenting existing matrix (avoids PSD violations from mixed lookback windows)
4. **Block-grouped accordion table** UX instead of flat card list — matches institutional platform conventions (Aladdin, FactSet)
5. **Candidate discovery gap identified** — no `strategy_label → block_id` mapping table exists; need explicit mapping logic or catalog-level block tagging

### New Considerations Discovered
- **CF CVaR invalidity at extremes:** |skewness| > 2.5 or excess kurtosis > 12 breaks the expansion — concentrated equity portfolios will hit this
- **SQL LIMIT bias:** NAV fetcher for 100+ candidates must use date floor, never `LIMIT(days * n)` — mixed density across asset classes
- **Thread safety:** ORM objects cannot cross async/thread boundary — extract to frozen dataclasses before `asyncio.to_thread()`
- **"Relax CVaR limit" alternative:** Sometimes the right answer is adjusting the profile, not adding funds — advisor should surface this option
- **Swap-pass improvement:** After greedy/brute-force solution, try replacing each fund with each unused candidate — catches most common failures

---

## Overview

Transform the "Construct Portfolio" step from a pass/fail CVaR gate into an intelligent advisor that diagnoses coverage gaps, screens candidate funds, projects impact, and guides users to viable portfolios. When the optimizer fails to meet CVaR limits (e.g., 3 equity funds producing -84% CVaR vs -6% limit), the system explains *why* and recommends *what to add* using existing engines (optimizer, correlation, N-PORT overlap, risk metrics, catalog). No ML or LLM required.

## Problem Statement

Today, when a user runs "Construct" with an insufficient universe:

1. The CLARABEL optimizer cascade runs all 4 phases (max return → robust SOCP → variance-cap → min-variance)
2. Even min-variance fallback produces CVaR far exceeding the profile limit (e.g., -84% vs -6%)
3. The frontend shows "Exceeds limit -- cannot activate" with no guidance
4. The user has no idea which blocks are missing, how many funds to add, or which specific funds would solve the problem
5. The user must manually browse 12k+ funds in the catalog, guessing which ones might improve the portfolio

This is the **primary friction point** in the portfolio lifecycle. A user who just completed the 5-step wizard (Profile → Fund Selection → Macro Inputs → Construct → Activate) hits a wall and abandons.

## Proposed Solution

### Architecture: Gap Analysis → Candidate Screener → Impact Projection

```
POST /model-portfolios/{id}/construct (existing)
    │
    ▼
FundOptimizationResult { cvar_within_limit: false }
    │
    ▼ (NEW)
POST /model-portfolios/{id}/construction-advice
    │
    ├─ 1. Block Gap Analysis
    │     Input:  optimizer result + strategic allocation targets
    │     Output: which blocks are missing/underweight, by how much
    │
    ├─ 2. Candidate Screening (per gap block)
    │     Input:  gap blocks + fund catalog + risk metrics
    │     Filter: funds in instruments_universe with NAV, assigned to gap block
    │     Rank:   lowest volatility × lowest correlation with current portfolio
    │
    ├─ 3. Overlap Filter
    │     Input:  candidate funds + current portfolio N-PORT holdings
    │     Output: overlap % per candidate, penalize >40% position overlap
    │
    └─ 4. Impact Projection (per candidate)
          Input:  current cov_matrix + candidate returns
          Output: projected CVaR if candidate added at target weight
          Method: recompute (N+1)×(N+1) cov from aligned returns, run historical simulation CVaR
```

### Research Insights — Architecture

**Institutional platform alignment:**
- BlackRock Aladdin uses **constraint violation decomposition** — shows ranked list of violated constraints with marginal impact. Our block gap analysis is the equivalent.
- Bloomberg PORT **always shows results** regardless of feasibility, with a "Constraint Diagnostics" sidebar. Our Phase 4 (always-show construct results) matches this.
- FactSet uses **wizard with inline feedback** and a "What-if" mode. Our candidate projections serve this role.

**"Relax CVaR limit" alternative:**
Sometimes the right answer is adjusting the risk profile, not adding 5 more funds. The advisor response should include an `alternative_profile_fit` field:
```json
{
  "alternative_profiles": [
    {
      "profile": "growth",
      "cvar_limit": -0.12,
      "current_cvar_would_pass": true,
      "note": "Current portfolio meets growth profile limits without changes"
    }
  ]
}
```

### Single New Endpoint

```
POST /model-portfolios/{portfolio_id}/construction-advice
```

**Request body:** (empty or optional config overrides)

**Response:**

```json
{
  "portfolio_id": "uuid",
  "profile": "moderate",
  "current_cvar_95": -0.8405,
  "cvar_limit": -0.06,
  "cvar_gap": -0.7805,
  "coverage": {
    "total_blocks": 14,
    "covered_blocks": 2,
    "covered_pct": 0.143,
    "block_gaps": [
      {
        "block_id": "fi_us_aggregate",
        "display_name": "US Aggregate Bond",
        "asset_class": "fixed_income",
        "target_weight": 0.20,
        "current_weight": 0.0,
        "gap_weight": 0.20,
        "priority": 1,
        "reason": "Largest weight gap, negative equity correlation"
      }
    ]
  },
  "candidates": [
    {
      "block_id": "fi_us_aggregate",
      "instrument_id": "uuid",
      "name": "Vanguard Total Bond Market Index Fund",
      "ticker": "VBTLX",
      "strategy_label": "Fixed Income",
      "volatility_1y": 0.042,
      "correlation_with_portfolio": -0.15,
      "overlap_pct": 0.0,
      "projected_cvar_95": -0.18,
      "cvar_improvement": 0.66,
      "in_universe": false,
      "external_id": "cik_or_isin",
      "has_holdings_data": true
    }
  ],
  "minimum_viable_set": {
    "funds": ["uuid-1", "uuid-2", "uuid-3"],
    "projected_cvar_95": -0.052,
    "projected_within_limit": true,
    "blocks_filled": ["fi_us_aggregate", "alt_gold", "fi_us_treasury"],
    "search_method": "brute_force"
  },
  "alternative_profiles": [
    {
      "profile": "growth",
      "cvar_limit": -0.12,
      "current_cvar_would_pass": true
    }
  ],
  "projected_cvar_is_heuristic": true
}
```

## Technical Approach

### Phase 1: Backend — Gap Analysis + Candidate Screener

**New file:** `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py`

Pure functions, zero I/O. Receives pre-fetched data, returns advice.

```python
@dataclass(frozen=True)
class BlockGap:
    block_id: str
    display_name: str
    asset_class: str
    target_weight: float
    current_weight: float
    gap_weight: float
    priority: int
    reason: str

@dataclass(frozen=True)
class CandidateFund:
    block_id: str
    instrument_id: str
    name: str
    ticker: str | None
    strategy_label: str | None
    volatility_1y: float | None
    correlation_with_portfolio: float
    overlap_pct: float
    projected_cvar_95: float
    cvar_improvement: float   # (current - projected) / current
    in_universe: bool         # already in org universe?
    external_id: str          # CIK or ISIN for import
    has_holdings_data: bool   # N-PORT data available?

@dataclass(frozen=True)
class MinimumViableSet:
    funds: list[str]          # instrument_ids
    projected_cvar_95: float
    projected_within_limit: bool
    blocks_filled: list[str]
    search_method: str        # "brute_force" or "greedy"

@dataclass(frozen=True)
class ConstructionAdvice:
    portfolio_id: str
    profile: str
    current_cvar_95: float
    cvar_limit: float
    cvar_gap: float
    coverage: CoverageAnalysis
    candidates: list[CandidateFund]
    minimum_viable_set: MinimumViableSet | None
    alternative_profiles: list[AlternativeProfile]
    projected_cvar_is_heuristic: bool
```

#### 1a. Block Gap Analysis

```python
def analyze_block_gaps(
    optimizer_result: FundOptimizationResult,
    strategic_targets: dict[str, float],     # {block_id: target_weight}
    block_metadata: dict[str, BlockInfo],    # from AllocationBlock table
) -> list[BlockGap]:
```

**Logic:**
- Compare `optimizer_result.block_weights` vs `strategic_targets`
- Gap = target - current for each block
- Priority: sort by `gap_weight * diversification_value`
  - `diversification_value`: fixed_income > alternatives > cash > equity (blocks in same asset class as existing funds score lower)
- Top N gaps (N = min(5, uncovered blocks))

**Research Insights — Block Gap Analysis:**

**Candidate discovery gap:** There is NO `strategy_label → block_id` mapping table in the database. `block_id` lives on `InstrumentOrg` (org-scoped), while `strategy_label` lives on instrument `attributes` JSONB. For candidate discovery from the global catalog (`instruments_universe`), we need one of:
- **Option A (recommended):** Build an in-memory mapping dict `{strategy_label: [block_ids]}` from `AllocationBlock` definitions + a heuristic (e.g., `"Fixed Income"` → `fi_*` blocks, `"Growth"` → `na_equity_large`). Keep it simple — 17 blocks, ~37 strategy labels, hand-coded mapping.
- **Option B:** Add a `candidate_block_ids` column to `instruments_universe` populated by a background job. More work, more correctness.

For Phase 1, Option A is sufficient. The mapping only needs to be "close enough" for advisory purposes — the user confirms by clicking "Add to [block]".

#### 1b. Candidate Screening

```python
def screen_candidates(
    block_gaps: list[BlockGap],
    catalog_funds: dict[str, list[FundCandidate]],  # {block_id: [funds]}
    portfolio_returns: np.ndarray,                    # (T,) current portfolio daily returns
    candidate_returns: dict[str, np.ndarray],         # {instrument_id: (T,) returns}
    portfolio_holdings: set[str],                      # CUSIPs in current portfolio
    candidate_holdings: dict[str, set[str]],           # {instrument_id: CUSIPs}
    risk_metrics: dict[str, FundRiskRow],              # pre-computed from fund_risk_metrics
    max_candidates_per_block: int = 3,
) -> list[CandidateFund]:
```

**Ranking formula per candidate:**

```
score = (
    0.40 * (1 - norm_vol)              # prefer low volatility
  + 0.35 * (1 - norm_corr)             # prefer low/negative correlation
  + 0.15 * (1 - overlap_pct)           # prefer low position overlap
  + 0.10 * norm_sharpe                 # prefer higher risk-adjusted return
)
```

Where `norm_*` = min-max normalized within block candidates.

**Data sources (all existing):**
- `fund_risk_metrics.volatility_1y` — pre-computed by risk_calc worker
- `fund_risk_metrics.sharpe_1y` — pre-computed
- `nav_timeseries.return_1d` — for pairwise correlation with current portfolio
- `sec_nport_holdings` — for position overlap (latest quarter)

**Research Insights — Candidate Screening:**

**NAV fetching — SQL LIMIT bias (from documented learning #2):**
Candidates span multiple asset classes (equity, fixed income, alternatives) with wildly different NAV frequencies. **Never use `LIMIT(days * len(candidate_ids))`** — this starves sparse instruments. Always use a date floor filter:
```sql
WHERE nav_date >= :date_floor AND return_1d IS NOT NULL
```
Then apply date intersection in Python (`set.intersection()` on observation dates). Require minimum 126 trading days (6 months) — below this, correlation estimates are too noisy (SE ~ 1/sqrt(T) ~ 0.09).

**Scoring weights should be configurable:**
The hardcoded `0.40/0.35/0.15/0.10` weights should be defined as named constants at minimum, or resolved via `ConfigService.get("liquid_funds", "advisor_scoring_weights")` for per-tenant customization.

**Correlation computation — use existing `correlation_regime_service.py` patterns:**
- Use `np.corrcoef()` for pairwise correlation (portfolio return series vs candidate return series)
- Apply Ledoit-Wolf shrinkage if computing full cross-correlation matrix
- Contagion threshold from existing config: correlation > 0.7 is a red flag

#### 1c. Impact Projection

```python
def project_cvar_with_candidate(
    portfolio_daily_returns: np.ndarray,  # (T, N) current fund returns
    candidate_returns: np.ndarray,        # (T,) daily returns for candidate
    current_weights: np.ndarray,          # N weights
    candidate_target_weight: float,       # from strategic allocation
    alpha: float = 0.05,
) -> float:  # projected CVaR
```

**Research Insights — CVaR Projection Method (CRITICAL):**

**Replace Cornish-Fisher with historical simulation CVaR for the advisor.**

The plan originally proposed using `parametric_cvar_cf()`. Research reveals this is unreliable at extreme CVaR levels:

1. **Non-monotonicity failure:** The CF quantile function becomes non-monotonic when |skewness| > 2.5 or excess kurtosis > 12. A 3-fund concentrated equity portfolio will likely breach these bounds.
2. **-84% CVaR is outside CF domain:** The expansion is a Taylor series around the normal distribution — it only works for distributions "close to Gaussian." At -84%, the polynomial has likely diverged.
3. **For ~15 evaluations, historical simulation is fast enough:** The optimizer uses CF because it runs 20,000 fitness evaluations. The advisor evaluates 10-15 candidates — historical CVaR with T=252 takes microseconds per evaluation.

**Recommended method:**
```python
def historical_cvar(
    portfolio_daily_returns: np.ndarray,  # (T, N)
    candidate_returns: np.ndarray,        # (T,)
    current_weights: np.ndarray,          # (N,)
    candidate_target_weight: float,
    alpha: float = 0.05,
) -> float:
    # Build heuristic weights
    scaled_weights = current_weights * (1 - candidate_target_weight)
    new_weights = np.append(scaled_weights, candidate_target_weight)

    # Combine returns
    combined_returns = np.column_stack([portfolio_daily_returns, candidate_returns])
    portfolio_returns = combined_returns @ new_weights

    # Historical CVaR (annualized)
    sorted_returns = np.sort(portfolio_returns)
    cutoff = max(int(len(sorted_returns) * alpha), 1)
    daily_cvar = -np.mean(sorted_returns[:cutoff])
    return daily_cvar * np.sqrt(252)  # annualize
```

**Fallback to CF:** If candidate has < 126 observations (too few for historical), fall back to CF with a validity guard:
```python
if abs(port_skew) > 2.5 or abs(port_kurt) > 12:
    # CF unreliable — use historical or skip candidate
    return None
```

**Covariance matrix expansion — recompute, don't augment:**
Do NOT mix the original NxN covariance (computed over 1260 days) with cross-covariances computed over 252 days. This creates a non-PSD "Frankenstein matrix." Instead:
- **Option A (recommended):** Compute returns-based historical CVaR directly (no covariance matrix needed).
- **Option B:** Recompute the entire (N+1)×(N+1) covariance from returns over the common date window. Since N is small (2-10 funds), this is instant.

**Weight rescaling is mathematically correct:**
Proportional rescaling `w' = [(1-c)*w_1, ..., (1-c)*w_N, c]` preserves the correct portfolio variance decomposition. The quadratic form `w'^T Σ w'` is exact for those specific weights. However, this is sub-optimal compared to re-optimization — the true optimal response might shift weight between existing funds too. For advisory ranking purposes, this approximation is sufficient.

**Add `projected_cvar_is_heuristic: true` to the response** to document that actual CVaR after re-optimization may differ.

#### 1d. Minimum Viable Set

```python
def find_minimum_viable_set(
    block_gaps: list[BlockGap],
    ranked_candidates: list[CandidateFund],
    cvar_limit: float,
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
) -> MinimumViableSet | None:
```

**Research Insights — Greedy vs Brute-Force (CRITICAL):**

**CVaR minimization is NOT submodular.** Wilder (2018) proved that composing CVaR with any stochastic function destroys submodularity. The greedy `(1-1/e)` approximation guarantee does NOT apply.

**Concrete counterexample where greedy fails:**
- Portfolio has 3 equity funds, CVaR = -84%.
- Candidate X (gold): alone reduces CVaR to -40%. Candidate Y (treasury): alone reduces to -50%.
- Greedy picks X first. After adding X, the synergistic pair {Y, Z} is unavailable as a unit.
- But {Y, Z} achieves CVaR = -5% vs greedy's {X, Z} at -10%.

**Brute-force is feasible:** With top 3 per block × 5 blocks = 15 candidates, subset sizes k=1..5:
- C(15,1) + C(15,2) + C(15,3) + C(15,4) + C(15,5) = 15 + 105 + 455 + 1365 + 3003 = **4,943 combinations**
- Each evaluation is a single `historical_cvar()` call (~microseconds)
- Total: < 50ms for exhaustive search

**Recommended algorithm:**
```python
def find_minimum_viable_set(...) -> MinimumViableSet | None:
    candidates = ranked_candidates[:15]  # top 3 per block, max 5 blocks

    # Brute-force if small enough (≤ 15 candidates, ≤ 5 per set)
    if len(candidates) <= 15:
        best = _brute_force_search(candidates, cvar_limit, ...)
        if best:
            return MinimumViableSet(..., search_method="brute_force")

    # Greedy fallback for larger candidate sets
    best = _greedy_search(candidates, cvar_limit, ...)
    if best:
        # Swap-pass improvement: try replacing each fund
        best = _swap_pass(best, candidates, cvar_limit, ...)
        return MinimumViableSet(..., search_method="greedy_with_swap")

    return None
```

**Swap-pass improvement:** After finding a greedy solution of size k, try replacing each fund in the set with each unused candidate. This catches the most common greedy failures at O(k × m) additional evaluations.

### Phase 2: Backend — Route + I/O Orchestration

**New route in:** `backend/app/domains/wealth/routes/model_portfolios.py`

```python
@router.post(
    "/{portfolio_id}/construction-advice",
    response_model=ConstructionAdviceRead,
    summary="Diagnose CVaR gaps and recommend candidate funds",
)
async def get_construction_advice(
    portfolio_id: UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ConstructionAdviceRead:
```

**Orchestration steps (async):**

1. Load portfolio + fund_selection_schema
2. Load optimizer result from last construct (stored in fund_selection_schema.optimization_metadata)
3. Load strategic_targets from StrategicAllocation
4. Compute block gaps → identify missing blocks
5. For each gap block, query candidate funds:
   - `instruments_universe` WHERE `strategy_label` matches (via mapping dict) AND `is_active = True` AND has NAV
   - LEFT JOIN `instruments_org` to check `in_universe` status
   - JOIN `fund_risk_metrics` for pre-computed vol/sharpe
   - Limit to top 20 per block by manager_score
6. Fetch NAV returns for candidates (batch query on nav_timeseries, **date floor filter, NOT LIMIT**)
7. Fetch N-PORT holdings for overlap computation (latest quarter per CIK)
8. Run `screen_candidates()` in `asyncio.to_thread()` (CPU-bound numpy)
9. Run `project_cvar_with_candidate()` for top 3 per block (historical simulation CVaR)
10. Run `find_minimum_viable_set()` (brute-force or greedy+swap)
11. Check alternative profiles (compare current CVaR vs other profile limits)
12. Return ConstructionAdviceRead

**Performance target:** < 2 seconds for 5 gap blocks × 20 candidates each.

**Research Insights — I/O Layer:**

**Thread safety (from documented learnings #5, #6):**
- Extract ALL ORM attributes into frozen dataclasses BEFORE calling `asyncio.to_thread()`. ORM model instances are NOT thread-safe.
- Pattern: route handler builds `FundRiskRow`, `BlockInfo` frozen dataclasses from ORM queries, passes these to advisor pure functions.
- No module-level mutable state in `construction_advisor.py`. No `@lru_cache`, no singletons.

**RLS + global table mixing (from documented learning #1):**
- `instruments_universe`, `nav_timeseries`, `sec_nport_holdings` are GLOBAL (no RLS)
- `instruments_org`, `model_portfolios` are org-scoped (RLS)
- All org-scoped queries already use `(SELECT current_setting(...))` subselect — verify this holds in JOIN queries
- For catalog candidates NOT in the org's universe: query `instruments_universe` directly (global), mark `in_universe: false`

**Holdings overlap — reuse existing infrastructure:**
- `holdings_exploder.py:fetch_portfolio_holdings_exploded()` already resolves CIK→N-PORT→weighted holdings
- For candidate overlap: compute CUSIP set intersection between portfolio holdings and candidate's N-PORT holdings (latest quarter)
- Use the Jaccard pattern from `manager_screener.py`: `len(intersection) / len(union)` for overlap_pct
- If candidate has no N-PORT data: `overlap_pct = 0.0` with `has_holdings_data: false`

**ConfigService for thresholds:**
- Scoring weights (`0.40/0.35/0.15/0.10`) → `ConfigService.get("liquid_funds", "advisor_scoring_weights")`
- CVaR limits per profile → already resolved via `_resolve_cvar_limit()`
- Min NAV days threshold (126) → named constant `MIN_CANDIDATE_NAV_DAYS = 126`

### Phase 3: Frontend — Advisor Panel in Construct Step

**Modified file:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

**New component:** `frontends/wealth/src/lib/components/model-portfolio/ConstructionAdvisor.svelte`

**UX flow:**

1. User clicks "Construct Portfolio"
2. Construct runs → CVaR exceeds limit
3. **Instead of just "Exceeds limit"**, show the advisor panel:

```
┌──────────────────────────────────────────────────────────────┐
│  MODERATE — CVaR -84.0% (limit -6.0%)                        │
│  ⚠ Portfolio concentrated in 2 of 14 blocks                  │
│                                                               │
│  ┌─ COVERAGE ───────────────────────────────────────────────┐ │
│  │  ██████░░░░░░░░  14% blocks covered (2/14)               │ │
│  │  Equity: 100% · Fixed Income: 0% · Alts: 0% · Cash: 0%  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  SUGGESTED ADDITIONS (sorted by CVaR impact)                  │
│                                                               │
│  ▼ fi_us_aggregate — US Aggregate Bond (target: 20%, gap: 20%)│
│  ┌────────────────────────────────────────────────────────┐   │
│  │ # │ Fund (Ticker)       │ Vol  │ Corr  │ Overlap │ Proj │ │
│  │ 1 │ Vanguard Bond VBTLX │ 4.2% │ -0.15 │   0%    │ -18% │ │
│  │ 2 │ iShares Agg AGG     │ 4.5% │ -0.12 │   2%    │ -19% │ │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  ▼ alt_gold — Gold (target: 5%, gap: 5%)                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │ 1 │ SPDR Gold GLD       │15.1% │  0.02 │   0%    │ -14% │ │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  ── QUICK PATH (sticky footer) ──────────────────────────────│
│  Add VBTLX + GLD + VGSH → projected CVaR: -4.2% ✓           │
│  [Add All & Re-construct]                                     │
│                                                               │
│  ── ALTERNATIVE ─────────────────────────────────────────────│
│  Switch to "growth" profile (CVaR limit -12%) → current       │
│  portfolio would pass without changes.                        │
└──────────────────────────────────────────────────────────────┘
```

**Research Insights — Frontend UX:**

**Block-grouped accordion table, not cards:**
Cards fail at this density (4-5 metrics × 3 candidates × 5 blocks = excessive scroll). Institutional users are trained on tabular data (Bloomberg Terminal, FactSet). Use collapsible block sections as table group headers.

**Three-tier progressive action:**

| Tier | Action | UX |
|------|--------|-----|
| Preview | Hover/select candidate | Show projected portfolio pie chart update inline |
| Single add | "Add to [block]" button | Import + assign + undo toast (3-5s) |
| Batch commit | "Add All & Re-construct" | ConsequenceDialog → import all → auto-construct |

**After single "Add" — do NOT re-fetch advice:**
- Strike-through the candidate row, mark with checkmark
- Update block gap header: "1/3 candidates added"
- Update coverage bar to show projected improvement
- "Re-construct" button in sticky footer becomes primary

**Error states:**

| Case | UX |
|------|-----|
| No candidates for a block | Show empty state with "Browse Catalog for [asset_class] funds" link (pre-filtered) |
| Minimum viable set is null | "Available catalog cannot bring portfolio within limits. Consider: 1) Expand catalog 2) Adjust risk profile 3) Remove [fund X] which contributes 60% of risk" |
| Partial success (CVaR improved but still over limit) | "Adding 3 funds brings CVaR to -8% (limit -6%). 90% improvement — consider 1-2 more fixed income funds." |
| `has_holdings_data: false` | Inline warning icon: "Holdings data unavailable — overlap not computed" |

**Svelte 5 component pattern — discriminated union state machine:**

```svelte
<script lang="ts">
  type AdvisorState =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "loaded"; data: ConstructionAdvice };

  let advisorState = $state<AdvisorState>({ status: "idle" });
  let addedFunds = $state<Set<string>>(new Set());

  let advice = $derived(
    advisorState.status === "loaded" ? advisorState.data : null
  );

  let candidatesByBlock = $derived.by(() => {
    if (!advice) return new Map();
    const groups = new Map<string, CandidateFund[]>();
    for (const c of advice.candidates) {
      const list = groups.get(c.block_id) ?? [];
      list.push(c);
      groups.set(c.block_id, list);
    }
    return groups;
  });

  // Auto-fetch when CVaR fails
  $effect(() => {
    if (cvarWithinLimit || advisorState.status !== "idle") return;
    fetchAdvice();
  });
</script>
```

**Key pattern rules:**
- `$effect` for fetch trigger only, NOT for storing results
- `$derived.by()` for complex grouping/transformation
- `Set<string>` for tracking added funds (optimistic UI)
- ConsequenceDialog (existing component) for batch "Add All" confirmation
- Use API client, never raw `fetch()` (from documented learning #7)

**"Add to Portfolio" action:**
1. If fund not in org universe → call `POST /screener/import/{ticker}` to import
2. Call `PATCH /instruments/{id}/org` to assign block_id
3. Add to portfolio's instrument list
4. Show undo toast (3-5s): "VBTLX added to fi_us_aggregate block"
5. After all additions → "Re-construct" button re-triggers construct

**"Add All & Re-construct":**
1. Show ConsequenceDialog: "Import N funds and re-run portfolio construction?"
2. Import + assign all funds in minimum_viable_set
3. Auto-trigger construct
4. If CVaR now within limit → show success state with "Activate" enabled

### Phase 4: Construct Always Returns Results (UX Change)

**Current behavior:** Construct succeeds (200 OK) but `cvar_within_limit: false` blocks activation.

**New behavior:** Same, but:
- Frontend **always shows construct results** (weights, CVaR, Sharpe, block allocation)
- If `cvar_within_limit: false`, show results + advisor panel below
- "Activate" button disabled with tooltip "CVaR exceeds profile limit"
- "Re-construct" button always available

**No backend change needed** — the optimizer already returns full results even on min_variance_fallback. Only the frontend rendering changes.

## Acceptance Criteria

### Functional Requirements

- [ ] `POST /construction-advice` returns block gaps, candidates, projections, minimum viable set
- [ ] Block gap analysis correctly identifies uncovered/underweight blocks
- [ ] Candidates ranked by composite score (vol, correlation, overlap, sharpe)
- [ ] Projected CVaR computed via historical simulation (not CF) for reliability at extreme levels
- [ ] Minimum viable set found via brute-force (≤15 candidates) or greedy+swap (>15)
- [ ] Response includes `alternative_profiles` when current CVaR passes a different profile
- [ ] Frontend shows advisor panel when `cvar_within_limit: false`
- [ ] "Add to Portfolio" imports fund if needed and assigns block
- [ ] "Add All & Re-construct" imports batch + triggers construct (with ConsequenceDialog)
- [ ] Construct results always shown (not hidden behind "exceeds limit")
- [ ] `projected_cvar_is_heuristic: true` flag in response

### Non-Functional Requirements

- [ ] Advice endpoint completes in < 3s for typical case (5 blocks × 20 candidates)
- [ ] No new external API calls (all data from existing DB tables)
- [ ] Thread-safe (numpy operations in `asyncio.to_thread()`, frozen dataclasses across boundary, no module-level state)
- [ ] Advice endpoint cached in Redis (SHA-256 of `portfolio_id + updated_at + date.today()`, 10min TTL)
- [ ] NAV queries use date floor filter, never `LIMIT(days * n)` — mixed density across asset classes
- [ ] Minimum 126 trading days of NAV data required for candidate eligibility

### Quality Gates

- [ ] Unit tests for gap analysis, candidate ranking, historical CVaR projection, minimum viable set (brute-force + greedy)
- [ ] Integration test: 3 equity funds → advisor recommends FI + alt → re-construct passes
- [ ] Test: CF validity guard triggers correctly for extreme skewness/kurtosis
- [ ] `make check` passes (lint + typecheck + architecture + test)
- [ ] Svelte-check 0 errors on wealth frontend

## Implementation Phases

### Phase 1 — Backend Engine (construction_advisor.py)

Pure functions, fully testable without DB:

- `analyze_block_gaps()` — compare block weights vs targets
- `rank_candidates()` — composite scoring (configurable weights)
- `compute_holdings_overlap()` — CUSIP set intersection (Jaccard)
- `project_cvar_historical()` — historical simulation CVaR with heuristic weight rescaling
- `project_cvar_cf_guarded()` — CF CVaR with validity guard (fallback for short series)
- `find_minimum_viable_set()` — brute-force (≤15) or greedy+swap (>15)
- `STRATEGY_LABEL_TO_BLOCKS` — hand-coded mapping dict (17 blocks × ~37 labels)

**Files:**
- `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` (new)
- `backend/vertical_engines/wealth/model_portfolio/models.py` (add dataclasses)
- `backend/tests/test_construction_advisor.py` (new)

### Phase 2 — Route + I/O Layer

Async orchestration fetching data from existing tables:

- `POST /model-portfolios/{id}/construction-advice` route
- Pydantic response schemas
- Strategy-label-to-block mapping for candidate discovery from global catalog
- NAV + holdings batch fetchers (date floor, date intersection)
- ORM → frozen dataclass extraction before thread dispatch
- Redis cache (follow `analytics.py` pattern: `advice:cache:{sha256_24}`)

**Files:**
- `backend/app/domains/wealth/routes/model_portfolios.py` (add route)
- `backend/app/domains/wealth/schemas/model_portfolio.py` (add response schemas)
- `backend/app/domains/wealth/services/candidate_screener.py` (new — I/O layer)

### Phase 3 — Frontend Advisor Panel

- `ConstructionAdvisor.svelte` component (block-grouped accordion table)
- Integration into `[portfolioId]/+page.svelte`
- Three-tier actions: preview, single "Add" with undo toast, batch "Add All" with ConsequenceDialog
- Always-show construct results (remove gated rendering)
- Sticky footer for minimum viable set quick path
- Alternative profile suggestion display

**Files:**
- `frontends/wealth/src/lib/components/model-portfolio/ConstructionAdvisor.svelte` (new)
- `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte` (modify)
- `frontends/wealth/src/lib/types/model-portfolio.ts` (add types)

### Phase 4 — Polish

- Redis caching for advice endpoint (follow `analytics.py` `_hash_analytics_input` pattern)
- Block-to-strategy mapping refinement (strategy_label → block_id heuristic)
- Performance optimization (batch NAV queries, parallel overlap computation)
- E2E test: construct → advice → add → re-construct → activate

## System-Wide Impact

### Interaction Graph

1. User clicks "Construct" → `POST /construct` → optimizer cascade → result persisted
2. Frontend detects `cvar_within_limit: false` → calls `POST /construction-advice`
3. Advice route reads last construct result + strategic allocations + catalog + risk metrics + NAV + N-PORT
4. Returns ranked candidates with projected CVaR (historical simulation)
5. User clicks "Add to Portfolio" → `POST /screener/import/{ticker}` + `PATCH /instruments/{id}/org`
6. User clicks "Re-construct" → `POST /construct` again with expanded universe

### Error Propagation

- Advice endpoint is **advisory only** — errors do not block construct or portfolio workflow
- If NAV data unavailable for a candidate → exclude from ranking (log warning)
- If N-PORT holdings unavailable → overlap_pct = 0 with `has_holdings_data: false` flag
- If no candidates found for a block → return empty candidates for that block with "Browse Catalog" hint
- If CF validity guard triggers (|skew| > 2.5 or |kurt| > 12) → use historical CVaR instead
- All errors caught per-candidate, never fail the entire advice response

### State Lifecycle Risks

- **No persistent state created** — advice is computed on-demand, not stored
- "Add to Portfolio" creates `Instrument` + `InstrumentOrg` records (existing idempotent flow)
- If import fails mid-batch in "Add All": already-imported funds remain, user can retry remainder

### API Surface Parity

- Existing `POST /construct` unchanged — backward compatible
- New `POST /construction-advice` is independent, optional endpoint
- Frontend can call advice endpoint at any time after construct (not coupled to construct response)

## Dependencies & Prerequisites

- **Data requirements:** `instruments_universe` must have funds with NAV in all major blocks (FI, alt, cash). Current seed (5,461 active instruments) covers this.
- **Risk metrics:** `fund_risk_metrics` must be populated for candidate funds (risk_calc worker runs daily)
- **N-PORT holdings:** Overlap computation requires recent N-PORT data (nport_ingestion worker runs weekly)
- **No new infrastructure** — uses existing PostgreSQL tables, numpy, scipy
- **Strategy-to-block mapping:** Hand-coded dict mapping ~37 strategy labels to 17 block IDs (new, but trivial)

## Research Insights — Redis Caching

**Follow the `analytics.py` pattern exactly:**

| Aspect | Implementation | Precedent |
|--------|---------------|-----------|
| Cache key | `advice:cache:{sha256_24(portfolio_id + updated_at + date.today())}` | `_hash_analytics_input` |
| TTL | 600s (10 min) hard TTL | `_set_cached_result(..., ex=3600)` |
| Scope | Org-scoped via RLS (portfolio is already org-scoped) | `route_cache` org scoping |
| Invalidation | Implicit: `portfolio.updated_at` changes on any modification → new key; `date.today()` changes daily → new key | Date in `_hash_analytics_input` |
| Fail-open | Yes — Redis down means fresh compute | All existing patterns |
| Lock / SWR | Neither — not needed at current scale (<50 tenants) | No precedent in codebase |

**Why hard TTL, not stale-while-revalidate:**
- All upstream data changes on daily batch cadence (risk metrics, NAV at 03:00 UTC)
- SWR requires background revalidation machinery that doesn't exist in the codebase
- Advisory data recomputes in <3s — no perceptible UX gap on cache miss

**Why no stampede prevention:**
- Endpoint is org-scoped — two different orgs never share a cache key
- Same org, same portfolio: small team product, concurrent hits are rare
- Computation cost is moderate (aggregating pre-computed data, not running heavy optimization)

## Alternative Approaches Considered

### A. Full optimizer re-run per candidate

Run `optimize_fund_portfolio()` with each candidate added. **Rejected:** too slow (4-phase cascade × 15 candidates = 60 optimizer runs). Historical simulation CVaR projection is 1000x faster and sufficient for ranking.

### B. LLM-based fund recommendation

Use GPT-4 to reason about which funds to add. **Rejected:** non-deterministic, not auditable, adds latency and cost. The problem is purely mathematical — correlation + CVaR are computable.

### C. Pre-computed advice table

Background worker pre-computes advice for all possible portfolio states. **Rejected:** combinatorial explosion. With 5k instruments and 14 blocks, the state space is too large. On-demand computation is fast enough (< 3s).

### D. Cornish-Fisher CVaR for all projections

Use existing `parametric_cvar_cf()` for impact projections. **Rejected after research:** CF expansion fails at extreme CVaR levels (|skew| > 2.5, |kurt| > 12). Concentrated equity portfolios will hit these bounds. Historical simulation CVaR is equally fast for ~15 evaluations and always correct.

### E. Greedy-only minimum viable set

Pure greedy algorithm without brute-force or swap pass. **Rejected after research:** CVaR minimization is proven non-submodular (Wilder, 2018). Greedy has no approximation guarantee. With ≤15 candidates, brute-force C(15,5)=4,943 evaluations is trivial (<50ms).

## Success Metrics

- **Construct-to-Activate conversion:** Track % of portfolios that go from "construct" to "activate" within same session (target: >60%, from current ~10%)
- **Advice acceptance rate:** % of suggested funds that users actually add (target: >40%)
- **Time to viable portfolio:** Measure time from first construct to `cvar_within_limit: true` (target: < 5 minutes)

## Sources & References

### Internal References

- Optimizer cascade: `backend/quant_engine/optimizer_service.py:310-638`
- CVaR parametric (Cornish-Fisher): `backend/quant_engine/optimizer_service.py:46-75`
- Construct endpoint: `backend/app/domains/wealth/routes/model_portfolios.py:131-175`
- Construction flow: `backend/app/domains/wealth/routes/model_portfolios.py:537-865`
- Fund-level inputs: `backend/app/domains/wealth/services/quant_queries.py:386-531`
- Correlation service: `backend/vertical_engines/wealth/correlation/service.py:24-121`
- Overlap scanner: `backend/vertical_engines/wealth/monitoring/overlap_scanner.py:56-140`
- Holdings exploder: `backend/app/domains/wealth/services/holdings_exploder.py:39-150`
- Fund risk metrics model: `backend/app/domains/wealth/models/risk.py:13-81`
- Block definitions: `calibration/config/blocks.yaml`
- Allocation proposal: `backend/quant_engine/allocation_proposal_service.py`
- Screener import: `backend/app/domains/wealth/routes/screener.py:867-1024`
- Frontend construct: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte:68-80`
- Portfolio builder: `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py`
- Portfolio models: `backend/vertical_engines/wealth/model_portfolio/models.py`
- Analytics cache pattern: `backend/app/domains/wealth/routes/analytics.py:55-108`
- Route cache decorator: `backend/app/core/cache/route_cache.py`
- Manager screener Jaccard: `backend/app/domains/wealth/routes/manager_screener.py:1136-1149`
- FundOptimizationResult: `backend/quant_engine/optimizer_service.py:294-308`

### External References

- Cornish-Fisher expansion: Stuart & Ord (1994), Kendall's Advanced Theory of Statistics
- Cornish-Fisher validity bounds: Maillard (2012), "A User's Guide to the Cornish Fisher Expansion"
- CVaR non-submodularity: Wilder (2018), "Risk-Sensitive Submodular Optimization"
- Pairwise-complete covariance dangers: Lewis (2015), "Pairwise-complete correlation considered dangerous"
- Portfolio construction reference: `docs/reference/portfolio-construction-reference-v2-post-quant-upgrade.md`
- Institutional portfolio lifecycle: `docs/reference/institutional-portfolio-lifecycle-reference.md`

### Documented Learnings Applied

- RLS subselect 1000x slowdown (`docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md`)
- SQL LIMIT bias on multi-instrument queries (`docs/solutions/logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md`)
- Vertical engine extraction patterns (`docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md`)
- Thread-unsafe shared state (`docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md`)
- Phantom frontend API calls (`docs/solutions/integration-issues/phantom-calls-missing-ui-wealth-frontend-20260319.md`)
- Wealth macro intelligence suite architecture (`docs/solutions/architecture-patterns/wealth-macro-intelligence-suite.md`)
