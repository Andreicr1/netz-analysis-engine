# Dynamic Tactical Asset Allocation (TAA) System

**Date:** 2026-04-12
**Status:** PLANNED
**Branch:** TBD
**Depends on:** Scoring dispatch (PR #123 merged), regime_service.py, allocation_proposal_service.py

---

## 1. Situation Analysis

### 1.1 What Exists Today

Three relevant layers that are currently **disconnected**:

**Layer A -- Regime Detection** (`regime_service.py`): Multi-signal classifier (`classify_regime_multi_signal`) scores 10 signals across two frequency tiers (55% fast / 45% slow) to classify RISK_ON / RISK_OFF / INFLATION / CRISIS. Regional regime detection via ICE BofA OAS spreads per geography. Asymmetric hysteresis documented but not yet implemented in code.

**Layer B -- Allocation Proposal** (`allocation_proposal_service.py`): Fully functional `compute_regime_tilted_weights()` that takes a regime classification and per-block strategic config with min/max/target, applies regime tilts (hardcoded `REGIME_TILTS` dict), regional score tilts, and renormalizes to sum=1.0. Produces `AllocationProposalResult` with `BlockProposal` per block. **This service EXISTS but is NEVER called in the construction pipeline.**

**Layer C -- Optimizer** (`optimizer_service.py`): CLARABEL 4-phase cascade reads `BlockConstraint(min_weight, max_weight)` from `StrategicAllocation` rows directly (line ~1851 of `model_portfolios.py`). These are static IPS bounds. The optimizer also receives `regime_cvar_multiplier` (RISK_OFF=0.85, CRISIS=0.70) but this only tightens the CVaR limit -- does NOT adjust allocation bands.

**Layer D -- Tactical Positions** (`TacticalPosition` model + allocation routes): Manual IC override mechanism where `overweight` per block is stored and combined with strategic weights via `get_effective()`. Manual-only today.

**Layer E -- ELITE Ranking** (`elite_ranking/allocation_source.py`): Distributes 300 global top funds proportionally to the `moderate` profile's static strategic weights: equity=50%, FI=33%, alt=12%, cash=5%. Source is `get_global_default_strategy_weights()` from `vertical_config_defaults`.

### 1.2 The Gap

Line ~1851 of `model_portfolios.py` is the bottleneck. `_run_construction_async` reads `StrategicAllocation` rows and passes their `min_weight`/`max_weight` verbatim to `BlockConstraint`. In CRISIS, the optimizer is constrained to keep equity at 45-55% (per IPS) when the optimal allocation might be equity:25%, FI:40%, alt:15%, cash:20%. The optimizer can minimize risk WITHIN blocks but not redistribute BETWEEN blocks.

The `allocation_proposal_service` already computes the correct regime-aware targets, but nobody calls it.

### 1.3 What This Plan Does NOT Change

- The CLARABEL 4-phase cascade -- kept intact, only constraint inputs change
- The `StrategicAllocation` model -- kept as IPS outer bounds
- The `AllocationBlock` taxonomy -- kept as-is
- The scoring dispatch (4-model) -- scoring is independent of allocation
- The `regime_service.py` classifier -- kept as signal source, only wired differently

---

## 2. Regime-to-Allocation Band Mapping

### 2.1 The Band Model

IPS bounds are outer guardrails; regime bands are inner operating ranges. The optimizer operates within regime bands, which are always a subset of IPS bounds.

```
IPS min          Regime min    Regime center    Regime max         IPS max
 |=================[===============|===============]==================|
 15%               25%            35%             45%               55%
                   <------------- band width = 20pp -------------->
```

### 2.2 Regime Band Configuration

Move `REGIME_TILTS` from hardcoded dict to ConfigService under `config_type = 'taa_bands'`:

```json
{
  "regime_bands": {
    "RISK_ON": {
      "equity":       {"center": 0.52, "half_width": 0.08},
      "fixed_income": {"center": 0.30, "half_width": 0.06},
      "alternatives": {"center": 0.12, "half_width": 0.04},
      "cash":         {"center": 0.06, "half_width": 0.03}
    },
    "RISK_OFF": {
      "equity":       {"center": 0.38, "half_width": 0.08},
      "fixed_income": {"center": 0.36, "half_width": 0.06},
      "alternatives": {"center": 0.13, "half_width": 0.04},
      "cash":         {"center": 0.13, "half_width": 0.05}
    },
    "INFLATION": {
      "equity":       {"center": 0.42, "half_width": 0.08},
      "fixed_income": {"center": 0.25, "half_width": 0.06},
      "alternatives": {"center": 0.22, "half_width": 0.06},
      "cash":         {"center": 0.11, "half_width": 0.04}
    },
    "CRISIS": {
      "equity":       {"center": 0.25, "half_width": 0.06},
      "fixed_income": {"center": 0.35, "half_width": 0.06},
      "alternatives": {"center": 0.15, "half_width": 0.05},
      "cash":         {"center": 0.25, "half_width": 0.08}
    }
  },
  "transition": {
    "ema_halflife_days": 5,
    "min_confidence_to_act": 0.60,
    "max_daily_shift_pct": 0.03
  },
  "ips_override_priority": true
}
```

**Center sum validation:** Each regime's centers must sum to 1.00 (within tolerance). Validated at ConfigService write time.

**Numerical calibration rationale:**

| Regime | Equity center | Rationale |
|--------|--------------|-----------|
| RISK_ON | 52% | Above-neutral: risk appetite drives equity overweight |
| RISK_OFF | 38% | Below-neutral: reduce equity ~12pp, flight to quality |
| INFLATION | 42% | Moderate reduction: equities partial inflation hedge |
| CRISIS | 25% | Maximum de-risk: equity to floor, cash/FI to ceiling |

### 2.3 Per-Block Disaggregation

Config operates at the asset-class level (equity, fixed_income, alternatives, cash). Per-block weights within each asset class derived by preserving the strategic allocation's internal proportions:

```
equity center = 38% (RISK_OFF)
na_equity_large target/total_equity_target = 0.19/0.50 = 38%
na_equity_large regime center = 0.38 * 0.38 = 0.1444 (14.44%)
```

Preserves IC committee's geographic/style preferences within each asset class while shifting the macro envelope.

---

## 3. IPS Compliance Layer

### 3.1 The Invariant

IPS bounds from `StrategicAllocation.min_weight` and `StrategicAllocation.max_weight` are HARD constraints that can NEVER be violated. These represent the Investment Policy Statement agreed with the client.

### 3.2 Band Clamping Algorithm

```python
def compute_effective_band(
    ips_min: float,
    ips_max: float,
    regime_center: float,
    regime_half_width: float,
) -> tuple[float, float]:
    """Compute effective optimizer band = intersection of IPS and regime band."""
    regime_min = regime_center - regime_half_width
    regime_max = regime_center + regime_half_width

    effective_min = max(ips_min, regime_min)
    effective_max = min(ips_max, regime_max)

    # If regime band falls entirely outside IPS, clamp to nearest IPS edge
    if effective_min > effective_max:
        if regime_center < ips_min:
            return ips_min, min(ips_min + 2 * regime_half_width, ips_max)
        elif regime_center > ips_max:
            return max(ips_max - 2 * regime_half_width, ips_min), ips_max
        else:
            return effective_min, effective_max

    return effective_min, effective_max
```

### 3.3 Priority Stack

```
1. IPS bounds (StrategicAllocation min/max)     -- HARD, never violated
2. Regime bands (ConfigService taa_bands)        -- SOFT, clamped by IPS
3. IC tactical overrides (TacticalPosition)     -- OVERRIDE, shifts center within IPS
4. Optimizer (CLARABEL)                          -- OPERATES within effective bands
```

When an IC member sets a manual tactical override (source='ic_manual'), it takes priority over the regime-computed center but is still clamped by IPS bounds.

---

## 4. Transition Management

### 4.1 The Whipsaw Problem

Regime transitions are noisy. A VIX spike from 24 to 26 flips RISK_ON to RISK_OFF. The next day VIX drops to 23 and flips back. Without smoothing, the optimizer would propose radically different portfolios on consecutive days, generating turnover costs that eat any defensive alpha.

### 4.2 Exponential Moving Average on Regime Centers

Smooth the ALLOCATION CENTERS, not the discrete regime classification:

```python
def smooth_regime_center(
    current_center: float,
    previous_smoothed_center: float,
    halflife_days: int = 5,
) -> float:
    """EMA smoothing on the regime-implied center.

    Halflife=5: ~50% of shift absorbed in 5 business days.
    Full convergence (>95%) in ~22 business days (~1 calendar month).

    Alpha = 1 - exp(-ln(2) / halflife)
    At halflife=5: alpha = 0.1294
    """
    alpha = 1 - math.exp(-math.log(2) / halflife_days)
    return alpha * current_center + (1 - alpha) * previous_smoothed_center
```

**Why EMA on centers, not on regime labels:**
1. Regime labels are categorical -- can't average "RISK_OFF" and "CRISIS"
2. The composite stress score (0-100) from `classify_regime_multi_signal` is already continuous
3. Smoothing centers directly gives the optimizer a gradually shifting feasible region
4. `max_daily_shift_pct` (default 3pp/day) provides a hard cap on single-day band movement

### 4.3 Persistence of Smoothed State

New table `taa_regime_state` stores smoothed centers per organization + profile, updated daily by `risk_calc` worker:

```sql
CREATE TABLE taa_regime_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    profile VARCHAR(20) NOT NULL,
    as_of_date DATE NOT NULL,
    raw_regime VARCHAR(20) NOT NULL,
    stress_score NUMERIC(5,1),
    smoothed_centers JSONB NOT NULL,  -- {"equity": 0.42, "fixed_income": 0.33, ...}
    effective_bands JSONB NOT NULL,   -- {"equity": {"min": 0.35, "max": 0.49}, ...}
    transition_velocity JSONB,        -- {"equity": -0.012, ...} daily delta for audit
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (organization_id, profile, as_of_date)
);
```

Org-scoped (has RLS). Daily snapshot allows full audit trail.

### 4.4 Confidence Gating

`min_confidence_to_act` (default 0.60) prevents regime shifts from acting unless the composite stress score has a clear directional signal. When `|stress_score - previous_score| < threshold`, smoothed centers hold previous values.

---

## 5. Dynamic ELITE Re-ranking

### 5.1 Current State

`get_global_default_strategy_weights()` returns static weights from moderate profile: `{equity: 0.50, fixed_income: 0.33, alternatives: 0.12, cash: 0.05}`. `compute_target_counts()` converts to `{equity: 150, fixed_income: 99, alternatives: 36, cash: 15}`.

### 5.2 Regime-Responsive ELITE

ELITE ranking is GLOBAL (no org context, runs in `global_risk_metrics` worker, lock 900_071). Approach: **pre-compute per-regime ELITE sets.**

Store 4 ELITE flags per fund: `elite_flag` (RISK_ON, existing), `elite_risk_off`, `elite_inflation`, `elite_crisis`. The `global_risk_metrics` worker computes all 4 sets in each daily run. Construction pipeline reads the flag matching current regime.

**Target counts per regime:**

| Regime | Equity | FI | Alt | Cash | Total |
|--------|--------|----|-----|------|-------|
| RISK_ON | 156 | 90 | 36 | 18 | 300 |
| RISK_OFF | 114 | 108 | 39 | 39 | 300 |
| INFLATION | 126 | 75 | 66 | 33 | 300 |
| CRISIS | 75 | 105 | 45 | 75 | 300 |

Derived from `round(300 * center)` per regime's asset-class centers.

### 5.3 Implementation

Add 3 new boolean columns to `fund_risk_metrics`:

```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN elite_risk_off BOOLEAN DEFAULT FALSE,
    ADD COLUMN elite_inflation BOOLEAN DEFAULT FALSE,
    ADD COLUMN elite_crisis BOOLEAN DEFAULT FALSE;
```

Existing `elite_flag` serves as RISK_ON set (backward compatible).

---

## 6. Optimizer Constraint Formulation Changes

### 6.1 Current Flow (Static)

```
StrategicAllocation rows
  -> BlockConstraint(block_id, min_weight, max_weight)  [IPS bounds]
  -> ProfileConstraints(blocks=[...], cvar_limit=...)
  -> optimize_fund_portfolio(constraints=constraints)
```

### 6.2 New Flow (Dynamic)

```
1. Read StrategicAllocation rows                       [IPS bounds]
2. Read taa_regime_state for current org+profile       [smoothed centers]
3. Disaggregate asset-class centers to per-block       [preserve IC proportions]
4. Clamp regime bands by IPS bounds                    [IPS compliance]
5. Apply IC tactical overrides if any                  [ic_manual priority]
6. Build BlockConstraint(block_id, effective_min, effective_max)
7. Pass to optimize_fund_portfolio()                   [unchanged optimizer]
```

### 6.3 Changes to `_run_construction_async`

Replace static bound reading at line ~1851 with a call to `resolve_effective_bands()` that:

1. Reads latest `taa_regime_state` row for org+profile
2. Disaggregates asset-class centers to per-block centers using `allocation_blocks.asset_class` join
3. Clamps each block's regime band by IPS min/max from `StrategicAllocation`
4. Applies any active `TacticalPosition` overrides (source='ic_manual')
5. Returns `list[BlockConstraint]` with regime-aware bands

**The optimizer itself does NOT change.** Only its input constraints change. CLARABEL cascade, robust SOCP, CVaR multipliers, turnover penalty -- all remain identical.

### 6.4 Interaction with CLARABEL Cascade

- Phase 1 (max risk-adj return): may find better solutions with tighter regime bands (less room for degenerate solutions)
- Phase 1.5 (robust SOCP): benefits from tighter bands (smaller ellipsoidal uncertainty set)
- Phase 2 (variance-capped): may be reached less often because regime bands already steer toward lower-risk allocations in RISK_OFF/CRISIS
- Phase 3 (min-variance): unchanged
- Regime CVaR multiplier (RISK_OFF=0.85, CRISIS=0.70) continues to work orthogonally -- tightens CVaR limit while TAA tightens allocation bands

---

## 7. Interaction with Scoring Dispatch

**Scoring is independent of allocation.** The 4-model scoring dispatch (equity, fixed_income, alternatives, cash) scores each fund based on its asset class, not on the portfolio's allocation regime. A fund's `manager_score` does not change based on whether the portfolio is in RISK_ON or CRISIS.

What DOES change: which funds enter the optimization universe (ELITE set per regime) and how much weight the optimizer allocates to each asset class. No scoring model changes needed.

---

## 8. TacticalPosition Enhancement

### 8.1 Source Discriminator

```sql
ALTER TABLE tactical_positions
    ADD COLUMN source VARCHAR(20) DEFAULT 'ic_manual'
    CHECK (source IN ('ic_manual', 'regime_auto', 'model_signal'));
```

- `ic_manual`: IC committee override (current behavior, always wins within IPS)
- `regime_auto`: Machine-generated from TAA regime bands
- `model_signal`: Future extensibility for factor-model signals

### 8.2 Priority Logic

When both `ic_manual` and `regime_auto` exist for the same block:
- `ic_manual` overrides `regime_auto` (IC committee has final authority)
- `regime_auto` positions still persisted for audit trail
- If `ic_manual` position expired (valid_to < today), `regime_auto` resumes

---

## 9. Audit and Provenance

### 9.1 Construction Run Enrichment

`portfolio_construction_runs.calibration_snapshot` JSONB gains TAA section:

```json
{
  "taa": {
    "enabled": true,
    "raw_regime": "RISK_OFF",
    "stress_score": 38.2,
    "smoothed_centers": {"equity": 0.42, "fixed_income": 0.34},
    "effective_bands": {"na_equity_large": {"min": 0.15, "max": 0.22}},
    "ips_clamps_applied": ["na_equity_large_min_raised"],
    "ic_overrides_active": [],
    "transition_velocity": {"equity": -0.008}
  }
}
```

### 9.2 Narrative Templater

TAA section added to Jinja2 narrative:

> "The portfolio was constructed under RISK_OFF market conditions (composite stress score: 38.2/100). Regime-adjusted allocation bands shifted equity exposure from the strategic center of 50% to an effective range of 35-49%, and increased fixed income to 30-42%. The smoothed transition reflects a 5-day EMA from the previous RISK_ON allocation. All regime-adjusted bands remain within Investment Policy Statement constraints."

---

## 10. Migration Plan

### 10.1 New Database Objects

**Migration `0126_taa_regime_state`:**
- `taa_regime_state` table (Section 4.3)
- RLS policy (org-scoped)
- Index on `(organization_id, profile, as_of_date DESC)`

**Migration `0127_elite_regime_flags`:**
- Add `elite_risk_off`, `elite_inflation`, `elite_crisis` columns to `fund_risk_metrics`
- Add `source` column to `tactical_positions`

**Migration `0128_taa_config_seed`:**
- Seed `vertical_config_defaults` with `config_type = 'taa_bands'`

### 10.2 Worker Changes

**`risk_calc` worker (lock 900_007, daily):**
- After computing fund-level risk metrics, run regime detection via `classify_regime_multi_signal`
- Compute smoothed centers via EMA against previous `taa_regime_state` row
- Compute effective bands (intersect with IPS from `StrategicAllocation`)
- Upsert `taa_regime_state` row for org+profile+date

**`global_risk_metrics` worker (lock 900_071, daily):**
- After scoring all funds, run ELITE ranking 4 times (once per regime scenario)
- Write `elite_risk_off`, `elite_inflation`, `elite_crisis` flags

### 10.3 Route Changes

**`_run_construction_async` in `model_portfolios.py`:**
- Replace static `BlockConstraint` construction with `resolve_effective_bands()` call
- Log regime source and effective bands in construction run's `optimizer_trace`
- Pass effective bands to `construction_run_executor` for persistence in `calibration_snapshot`

**Allocation routes:**
- `GET /allocation/{profile}/effective` -- include regime-adjusted bands alongside strategic+tactical
- New `GET /allocation/{profile}/regime-bands` -- expose current smoothed centers + effective bands
- `GET /allocation/{profile}/taa-history` -- time series of regime states for audit

---

## 11. Files Touched

| File | Change Type |
|------|------------|
| `quant_engine/taa_band_service.py` | NEW -- core TAA logic |
| `quant_engine/allocation_proposal_service.py` | EVOLVE -- move REGIME_TILTS to config |
| `app/domains/wealth/workers/risk_calc.py` | MODIFY -- compute + persist taa_regime_state |
| `app/domains/wealth/workers/construction_run_executor.py` | MODIFY -- read regime state |
| `app/domains/wealth/routes/model_portfolios.py` | MODIFY -- call resolve_effective_bands |
| `app/domains/wealth/routes/allocation.py` | MODIFY -- new regime-bands + taa-history routes |
| `app/domains/wealth/models/allocation.py` | MODIFY -- add source to TacticalPosition |
| `app/domains/wealth/schemas/allocation.py` | MODIFY -- add regime band schemas |
| `vertical_engines/wealth/elite_ranking/allocation_source.py` | MODIFY -- per-regime weight computation |
| `app/domains/wealth/models/risk.py` | MODIFY -- add elite regime flag columns |
| `vertical_engines/wealth/model_portfolio/narrative_templater.py` | MODIFY -- TAA narrative section |
| `vertical_engines/wealth/model_portfolio/validation_gate.py` | MODIFY -- add check #16 |
| Migrations 0126, 0127, 0128 | NEW |

---

## 12. Phased Execution

### Sprint 1: Wire the Existing Plumbing (3-4 days)

**Goal:** Make the construction pipeline regime-responsive using existing code.

1. Create `taa_band_service.py` in `quant_engine/` with:
   - `resolve_effective_bands()` -- reads `taa_regime_state`, disaggregates to per-block, clamps by IPS
   - `smooth_regime_centers()` -- EMA computation
   - `compute_effective_band()` -- single-block IPS clamp
2. Migration `0126_taa_regime_state`
3. Migration `0128_taa_config_seed` -- seed default TAA config
4. Modify `_run_construction_async` to call `resolve_effective_bands()` instead of reading static bounds
5. Modify `risk_calc` worker to compute and persist `taa_regime_state` rows daily
6. Add `taa_enabled` toggle to `PortfolioCalibration.expert_overrides` (default `true`)
7. Tests: unit tests for band clamping, EMA smoothing, IPS invariant, optimizer with dynamic bands

**Deliverable:** Construction runs produce regime-responsive portfolios. Existing behavior preserved when `taa_enabled=false`.

### Sprint 2: ELITE Dynamic + Transition Polish (2-3 days)

**Goal:** ELITE ranking becomes regime-aware, transition smoothing is production-quality.

1. Migration `0127_elite_regime_flags` -- add 3 boolean columns
2. Modify `global_risk_metrics` worker to compute 4 ELITE sets
3. Modify construction pipeline to filter universe by regime-appropriate ELITE flag
4. Add `source` discriminator to `tactical_positions`
5. Implement confidence gating (`min_confidence_to_act`) and max daily shift cap
6. Tests: ELITE count validation per regime, transition smoothing edge cases

**Deliverable:** ELITE ranking shifts with regime. Transition smoothing prevents whipsaw.

### Sprint 3: IPS Compliance + Audit + Routes (2-3 days)

**Goal:** Full audit trail, institutional routes, narrative enrichment.

1. Enrich `calibration_snapshot` JSONB with TAA provenance data
2. Add TAA section to narrative templater
3. New routes: `GET /allocation/{profile}/regime-bands`, `GET /allocation/{profile}/taa-history`
4. Update `GET /allocation/{profile}/effective` to include regime-adjusted info
5. Add `write_audit_event()` calls for TAA state transitions
6. Validation gate: add check #16 "TAA bands within IPS"
7. Tests: audit trail completeness, route contract validation, narrative output

**Deliverable:** Full institutional audit trail. IC can reconstruct why any portfolio was proposed.

### Sprint 4 (optional): Frontend Visualization (2 days)

**Goal:** Builder UI shows regime bands and TAA state.

1. CalibrationPanel gains "Market Regime" indicator (current regime + stress score)
2. Allocation chart shows IPS bounds (grey), regime bands (colored), current weights (dots)
3. Transition history sparkline showing smoothed center evolution over 60 days
4. All labels use institutional vocabulary (`formatPercent` from `@netz/ui`, no quant jargon)

---

## 13. Risk Analysis

| Risk | Mitigation |
|------|-----------|
| EMA smoother creates phantom drift in stable regimes | Confidence gating: no shift when `abs(delta_score) < threshold` |
| Regime flips at market close generate overnight trades | `max_daily_shift_pct` caps single-day movement at 3pp |
| IPS clamp makes regime bands degenerate (min > max) | `compute_effective_band()` has explicit degenerate-band handler |
| Missing `taa_regime_state` row (first run, new org) | Fallback to static IPS bands (identical to current behavior) |
| ELITE 4x computation doubles `global_risk_metrics` runtime | Scoring already computed; ELITE selection is O(n log n) sort -- negligible |
| Config drift between `taa_bands` and `portfolio_profiles` | Validation at write time: centers must sum to 1.0, must fit within default IPS ranges |

### Backward Compatibility

- **Default behavior unchanged.** Without `taa_regime_state` row, falls back to static `StrategicAllocation` bounds
- **`taa_enabled` toggle** in `expert_overrides` allows per-portfolio opt-out
- **`elite_flag`** (existing column) continues to serve as RISK_ON set
