# Dynamic TAA System — Execution Wrapper

**Date:** 2026-04-12
**Specification:** `docs/plans/2026-04-12-dynamic-taa-system.md` (authoritative spec, 508 lines)
**Status:** Ready for execution in 4 sprints
**Priority:** CORE SYSTEM — the allocation engine is the reason the platform exists

## Context updates

### Alembic head

After Alt Sprint 3 merges: `0125_add_alternatives_risk_metrics` (or current head). TAA migrations start at `0126+`. Verify via `alembic heads`.

### Key discovery from the plan

**`allocation_proposal_service.py` already exists and computes regime-tilted weights — but is NEVER called in the construction pipeline.** Line ~1851 of `model_portfolios.py` reads static `StrategicAllocation` bounds verbatim. The gap is WIRING, not missing infrastructure.

### Scoring dispatch state (complete)

4-model scoring dispatch is fully operational:
- equity: 6 components (original)
- fixed_income: 5 components (FI Quant)
- alternatives: 5 components × 5 profiles (Alt Scoring)
- cash: 5 components (Cash Scoring)

ELITE ranking: 300 funds across 4 asset classes. Scoring is INDEPENDENT of allocation — no scoring changes needed for TAA.

### What does NOT change

- CLARABEL 4-phase cascade optimizer — only its INPUT constraints change
- StrategicAllocation model — kept as IPS outer bounds
- AllocationBlock taxonomy — kept as-is
- Scoring dispatch — independent of allocation
- regime_service.py classifier — kept as signal source

## 4-sprint execution

### Sprint 1 — Wire the Existing Plumbing (core wiring)

**Branch:** `feat/taa-sprint-1`
**Scope:** TAA band service + migrations + wire construction pipeline
**Read:** plan §1-4, §6, §10.1-10.3

**Deliverable:**
1. `quant_engine/taa_band_service.py` (NEW) — `resolve_effective_bands()`, `smooth_regime_centers()`, `compute_effective_band()` (band clamping). Pure-sync, config-driven.
2. Migration `0126_taa_regime_state` — new table with RLS, org-scoped daily snapshots of smoothed centers + effective bands
3. Migration `0128_taa_config_seed` — seed `vertical_config_defaults` with `config_type='taa_bands'` (regime band config JSON from plan §2.2)
4. Modify `_run_construction_async` in `model_portfolios.py` (~line 1851) — replace static `BlockConstraint` with `resolve_effective_bands()` call
5. Modify `risk_calc` worker — after risk metrics, run regime detection → compute smoothed centers via EMA → upsert `taa_regime_state` row
6. Add `taa_enabled` toggle to `PortfolioCalibration.expert_overrides` (default `true`)
7. Tests: band clamping (IPS invariant), EMA smoothing, optimizer with dynamic bands, fallback to static when no taa_regime_state row

**Critical test:** with `taa_enabled=false`, construction output must be IDENTICAL to current behavior. Zero regression.

**Instruction for Opus:**
```
Read docs/plans/2026-04-12-dynamic-taa-system.md sections 1-4, 6, and 10.1-10.3 fully, and docs/plans/2026-04-12-taa-execution-wrapper.md Sprint 1 section fully. Also read backend/quant_engine/allocation_proposal_service.py to understand the EXISTING regime-tilt computation that you are now wiring into the construction pipeline. Read backend/app/domains/wealth/routes/model_portfolios.py around line 1851 to understand the current static BlockConstraint construction. Implement Sprint 1: taa_band_service.py, 2 migrations, wire _run_construction_async, modify risk_calc worker for regime state persistence, add taa_enabled toggle. Critical: with taa_enabled=false, behavior must be identical to current. Report including EMA smoothing test output and band clamping IPS invariant proof.
```

### Sprint 2 — ELITE Dynamic + Transition Polish

**Branch:** `feat/taa-sprint-2`
**Depends on:** Sprint 1 merged
**Scope:** 4 ELITE sets + transition confidence gating + tactical position source
**Read:** plan §5, §4.4, §8

**Deliverable:**
1. Migration `0127_elite_regime_flags` — add `elite_risk_off`, `elite_inflation`, `elite_crisis` boolean columns to `fund_risk_metrics` + add `source` VARCHAR to `tactical_positions`
2. Modify `global_risk_metrics` worker — after scoring, compute ELITE ranking 4 times (once per regime scenario: RISK_ON uses existing `elite_flag`, plus 3 new sets)
3. Modify construction pipeline — filter universe by regime-appropriate ELITE flag (read current regime from `taa_regime_state`, pick matching flag column)
4. Confidence gating — `min_confidence_to_act` (0.60): no regime shift when `|stress_score - previous| < threshold`
5. Max daily shift cap — `max_daily_shift_pct` (3pp/day)
6. `TacticalPosition.source` discriminator — `ic_manual` overrides `regime_auto` within IPS
7. Tests: ELITE count = 300 per regime set, transition smoothing edge cases, confidence gating, IC override priority

**ELITE target counts per regime (from plan §5.2):**

| Regime | Equity | FI | Alt | Cash | Total |
|---|---|---|---|---|---|
| RISK_ON | 156 | 90 | 36 | 18 | 300 |
| RISK_OFF | 114 | 108 | 39 | 39 | 300 |
| INFLATION | 126 | 75 | 66 | 33 | 300 |
| CRISIS | 75 | 105 | 45 | 75 | 300 |

**Instruction for Opus:**
```
Read docs/plans/2026-04-12-dynamic-taa-system.md sections 5, 4.4, and 8 fully, and docs/plans/2026-04-12-taa-execution-wrapper.md Sprint 2 section fully. Verify Sprint 1 merged (taa_regime_state table exists, taa_band_service importable). Implement ELITE 4-set computation in global_risk_metrics worker, regime-appropriate ELITE filtering in construction pipeline, confidence gating, max daily shift, TacticalPosition source discriminator. Verify each regime's ELITE set sums to 300. Report including ELITE distribution table per regime.
```

### Sprint 3 — IPS Compliance + Audit + Routes

**Branch:** `feat/taa-sprint-3`
**Depends on:** Sprint 2 merged
**Scope:** Audit trail, routes, narrative, validation gate
**Read:** plan §3, §9, §10.3 routes

**Deliverable:**
1. Enrich `calibration_snapshot` JSONB with TAA provenance (raw regime, stress score, smoothed centers, effective bands, IPS clamps applied, IC overrides active, transition velocity)
2. TAA section in narrative templater (Jinja2) — institutional language per plan §9.2
3. New routes:
   - `GET /allocation/{profile}/regime-bands` — current smoothed centers + effective bands
   - `GET /allocation/{profile}/taa-history` — time series of regime states for audit
   - Update `GET /allocation/{profile}/effective` — include regime-adjusted info alongside strategic + tactical
4. Validation gate check #16: "TAA bands within IPS" — verify effective bands are always subset of IPS bounds
5. `write_audit_event()` calls for TAA state transitions (regime change, band shift, IC override applied)
6. Tests: audit trail completeness (construction run has full TAA provenance), route contracts, narrative output, validation gate fires when bands violate IPS (should never happen but defense-in-depth)

**Instruction for Opus:**
```
Read docs/plans/2026-04-12-dynamic-taa-system.md sections 3, 9, 10.3, and 12 Sprint 3 fully, and docs/plans/2026-04-12-taa-execution-wrapper.md Sprint 3 section fully. Verify Sprint 2 merged (4 ELITE sets computed, confidence gating active). Implement calibration_snapshot TAA enrichment, narrative templater TAA section, 3 routes (regime-bands, taa-history, effective update), validation gate check #16, audit events. Report including sample calibration_snapshot TAA JSON and narrative output.
```

### Sprint 4 — Frontend Visualization

**Branch:** `feat/taa-sprint-4`
**Depends on:** Sprint 3 merged
**Scope:** Builder UI shows regime bands and TAA state
**Read:** plan §12 Sprint 4

**Deliverable:**
1. CalibrationPanel gains "Market Regime" indicator — current regime label + stress score (0-100) with color coding
2. Allocation chart shows 3 layers:
   - Grey: IPS outer bounds (hard limits)
   - Colored (regime-specific): regime bands (where the optimizer can operate)
   - Dots: current portfolio weights (where the optimizer placed the allocation)
3. Transition history sparkline — 60-day smoothed center evolution per asset class
4. All labels use institutional vocabulary — `formatPercent` from `@netz/ui`, zero quant jargon (no "EMA halflife", no "stress score" — say "Market Conditions" and "Defensive Posture")
5. Responsive to regime changes — when a new `taa_regime_state` row lands (SSE or polling), the chart updates

**Instruction for Opus:**
```
Read docs/plans/2026-04-12-dynamic-taa-system.md section 12 Sprint 4 fully, and docs/plans/2026-04-12-taa-execution-wrapper.md Sprint 4 section fully. Verify Sprint 3 merged (regime-bands route available, calibration_snapshot has TAA provenance). Implement CalibrationPanel regime indicator, 3-layer allocation chart (IPS/regime/current), transition history sparkline, institutional labels (smart backend/dumb frontend — no quant jargon). Report including screenshot of the regime visualization.
```

## Post-completion validation

After all 4 sprints merge:

```sql
-- Verify taa_regime_state has daily snapshots
SELECT as_of_date, raw_regime, stress_score, smoothed_centers
FROM taa_regime_state
WHERE organization_id = '<test-org>'
ORDER BY as_of_date DESC
LIMIT 5;

-- Verify 4 ELITE sets all sum to 300
SELECT
  COUNT(*) FILTER (WHERE elite_flag) AS risk_on,
  COUNT(*) FILTER (WHERE elite_risk_off) AS risk_off,
  COUNT(*) FILTER (WHERE elite_inflation) AS inflation,
  COUNT(*) FILTER (WHERE elite_crisis) AS crisis
FROM fund_risk_metrics
WHERE calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics);

-- Verify construction run has TAA provenance
SELECT calibration_snapshot->'taa' FROM portfolio_construction_runs
ORDER BY started_at DESC LIMIT 1;
```

## Backward compatibility guarantee

- **`taa_enabled=false` or missing `taa_regime_state` row → identical to current behavior.** Static IPS bounds passed to optimizer. No regime adjustment. This is the safety net.
- **`elite_flag` (existing) = RISK_ON set.** Backward compatible. New columns are additive.
- **All new routes are NEW paths.** No existing route contract changed.

## Valid escape hatches

1. `allocation_proposal_service.py` API differs from what the plan assumes → read the actual function signatures, adapt `taa_band_service` to call them correctly
2. `classify_regime_multi_signal` returns a different format than expected → read `regime_service.py` actual output, adapt
3. `taa_regime_state` table conflicts with an existing table name → rename to `portfolio_regime_state` or similar
4. EMA smoothing produces numerical drift over hundreds of days → add periodic re-anchoring to raw regime centers (e.g., every 30 days, reset smoothed = raw)
5. ELITE 4x computation exceeds worker time budget → profile; ELITE selection is O(n log n) per regime and should be negligible vs the scoring computation
6. Sprint 4 frontend components conflict with existing CalibrationPanel → read the current component, compose alongside existing content, don't replace

## Not valid escape hatches

- "TAA is too complex for one sprint" → each sprint is scoped to 3-4 days. If it's taking longer, the brief needs adjustment, not abandonment.
- "Let's skip the EMA smoothing and just use raw regime" → NO, whipsaw would generate massive turnover and erode alpha. The plan §4.1 explains why.
- "IPS clamping is unnecessary, regime bands are already reasonable" → NO, IPS is a fiduciary obligation. The band MUST be clamped. One violation = one lawsuit.
- "Let's keep ELITE static and just change allocation bands" → NO, if allocation shifts to 25% equity but ELITE still has 150 equity slots, the universe doesn't match the allocation. Both must be regime-responsive.
