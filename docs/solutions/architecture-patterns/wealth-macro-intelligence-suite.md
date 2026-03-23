---
title: "Wealth Macro Intelligence Suite"
date: 2026-03-15
category: architecture-patterns
tags:
  - wealth-management
  - macro-analysis
  - regime-detection
  - fred-data
  - committee-workflow
  - quant-engine
  - vertical-engine
  - multi-tenant
  - code-review
module: wealth
vertical: liquid_funds
pull_requests: [6, 7]
review_agents_used: 18  # 2 rounds of 9 agents each
---

# Wealth Macro Intelligence Suite

## Problem Statement

The Netz Wealth Management vertical had strong bottom-up capabilities (backtest, optimization, CVaR, rebalance, drift) but zero top-down macro intelligence. Tactical positions in `TacticalPosition` were 100% manual. Two parallel FRED data paths existed that needed unification. The platform needed a systematic way to incorporate regional macro conditions, regime signals, and committee-driven tactical overlays into portfolio construction.

## Architecture

### Four-Layer Design

```
Layer 1: quant_engine/ (pure sync, no I/O)
  ├── regional_macro_service.py   — series registry, percentile scoring, staleness decay
  ├── macro_snapshot_builder.py   — pure snapshot assembler
  └── regime_service.py           — regional + global regime classification

Layer 2: vertical_engines/wealth/ (domain logic)
  └── macro_committee_engine.py   — weekly reports, emergency cooldown

Layer 3: workers/ (I/O orchestration)
  └── macro_ingestion.py          — FRED fetch, snapshot persistence, advisory lock

Layer 4: routes/ (API surface)
  └── macro.py                    — 7 endpoints across 2 phases
```

### Data Flow

```
FRED API (45 series, 5 domains)
    │
    ▼
macro_ingestion worker
    │  asyncio.to_thread → FredService.fetch_batch_concurrent (5 threads)
    │
    ├──→ build_regional_snapshot() → macro_regional_snapshots (JSONB, global)
    └──→ macro_data upsert (backward compat with regime_service)

Committee workflow:
    snapshots → generate_weekly_report() → MacroReview (org-scoped, RLS)
                                              │
                                              ▼
                                    CIO approve/reject (RBAC)
```

### Key Patterns

**Concurrent Domain Fetching:** `FredService.fetch_batch_concurrent()` dispatches 5 domain groups (US, EUROPE, ASIA, EM, GLOBAL) via `ThreadPoolExecutor` with a shared `TokenBucketRateLimiter`. The rate limiter is thread-safe via `threading.Lock`. Realistic fetch time is ~18s (not ~6s as initially claimed — the global 2 req/s rate limit is the bottleneck, not thread count).

**Percentile-Rank Normalization:** Expanding-window percentile rank over full available history (minimum 60 observations). Each indicator maps to 0-100 where 50 = historical median. The `invert` flag handles indicators where higher values signal worse conditions. Source: Macrosynergy Research (2024).

**Staleness-Aware Weight Decay:** Per-frequency linear decay (daily: 3d fresh / 10d max, monthly: 45d / 90d, quarterly: 100d / 180d). Weight decays from 1.0 to a configurable floor, then drops to 0.0 beyond max useful days. Coverage threshold (50% of total dimension weight) must be met for a composite score.

**Frozen Dataclasses:** All result types crossing async/sync boundaries use `@dataclass(frozen=True)`: `RegionalMacroResult`, `GlobalIndicatorsResult`, `RegionalRegimeResult`, `DimensionScore`, `DataFreshness`, `ScoreDelta`, `WeeklyReportData`.

**Hierarchical Regime Detection:** Per-region classification using ICE BofA credit spread OAS signals (US: VIX + HY OAS, others: regional OAS). GDP-weighted global composition with pessimistic override (2+ regions CRISIS → global CRISIS, 1 significant region CRISIS → floor RISK_OFF).

**ConfigService Integration:** `macro_intelligence` config type added via migration 0005 CHECK ALTER. YAML seed in `calibration/seeds/liquid_funds/macro_intelligence.yaml`. Routes resolve config via `ConfigService(db).get("liquid_funds", "macro_intelligence", org_id)`.

## Critical Bugs Found During 18-Agent Review

Two rounds of 9 parallel review agents (kieran-python-reviewer, security-sentinel, performance-oracle, architecture-strategist, pattern-recognition-specialist, agent-native-reviewer, code-simplicity-reviewer, data-integrity-guardian, learnings-researcher) identified 6 critical bugs across the two phases.

### 1. Migration Downgrade Ordering (Phase 1, P1)

**Bug:** `downgrade()` restored narrow CHECK constraints before deleting `macro_intelligence` rows. PostgreSQL rejects the constraint when violating rows exist.

**Fix:** Delete rows from both `vertical_config_defaults` and `vertical_config_overrides` BEFORE restoring constraints.

**Prevention:** Treat `downgrade()` as first-class. Mental model: clean data first, restore constraints second. Add migration round-trip test.

### 2. Global Indicators Invert Bug (Phase 1, P1)

**Bug:** `score_global_indicators()` applied blanket `invert=True` to all series in a category group. Copper and gold (registry: `invert=False`) were incorrectly inverted, producing wrong commodity_stress scores.

**Fix:** Build per-series lookup `{s.series_id: s.invert for s in GLOBAL_SERIES}` and use registry flags instead of blanket parameter.

**Prevention:** Never use a blanket boolean for a per-item property. Test with known fixtures where indicators move in opposite directions.

### 3. Missing Regional Credit Spread Series (Phase 2, P0)

**Bug:** `get_latest_macro_values()` only queried 5 US-centric FRED series. The 4 regional OAS signals (BAMLH0A0HYM2, BAMLHE00EHYIOAS, BAMLEMRACRPIASIAOAS, BAMLEMCBPIOAS) were never fetched, causing `classify_regional_regime()` to silently default to RISK_ON for all non-US regions.

**Fix:** Added 4 regional series to the `series_staleness` dict with `STALENESS_DAILY`.

**Prevention:** When adding regional analysis, update the data layer in lockstep. Integration test per region asserting all required series are fetched.

### 4. Race Condition on Approve/Reject (Phase 2, P1)

**Bug:** Approve and reject endpoints used plain SELECT without row locking. Concurrent requests could both read `status="pending"` and both succeed.

**Fix:** Added `.with_for_update()` to both endpoints.

**Prevention:** Any read-then-write on a status field needs SELECT FOR UPDATE. Code review checklist item.

### 5. Hardcoded Threshold Divergence (Phase 2, P1)

**Bug:** `classify_regional_regime()` used magic numbers `35`, `25`, `4.0` for VIX/CPI thresholds instead of referencing `_DEFAULT_THRESHOLDS` constants used by `classify_regime_multi_signal()`.

**Fix:** Replaced with `_DEFAULT_THRESHOLDS["vix_extreme"]`, `_DEFAULT_THRESHOLDS["vix_risk_off"]`, `_DEFAULT_THRESHOLDS["cpi_yoy_high"]`.

**Prevention:** Bare numeric literals in analytical functions are a code smell. Single source of truth for thresholds.

### 6. Non-Deterministic Migration Cleanup (Phase 2, P2)

**Bug:** Tactical positions cleanup subquery used `ORDER BY created_at DESC LIMIT 1` without tiebreaker. Timestamp ties produce non-deterministic results.

**Fix:** Added `position_id DESC` as secondary sort.

**Prevention:** Any `ORDER BY ... LIMIT 1` in data cleanup should have a deterministic tiebreaker column.

## YAGNI Items Removed

**`get_hysteresis_days()`:** Implemented with config, defaults dict, and tests — but zero callers. Hysteresis requires a state machine (daily runs + transition log) that doesn't exist yet. Removed ~35 LOC.

**`TacticalPositionInput`:** Pydantic model for creating tactical positions on approval — but the approve endpoint explicitly deferred position creation to a future phase. Removed ~10 LOC.

## Prevention Checklist

| # | Check | Catches |
|---|-------|---------|
| 1 | Does `downgrade()` clean data before restoring constraints? | Migration ordering |
| 2 | Does any scoring function apply a uniform transform to heterogeneous inputs? | Blanket invert bugs |
| 3 | Does any analytical function return a "happy" default when inputs are missing? | Silent data gaps |
| 4 | Does any read-then-write on a status field use SELECT FOR UPDATE? | Race conditions |
| 5 | Are there bare numeric literals in analytical comparison logic? | Config divergence |
| 6 | Does every new public function/class have a caller in the same PR? | YAGNI / dead code |

## Related Documents

- [Plan](../../plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md) — Full implementation plan with 45 FRED series, phase breakdown
- [Brainstorm](../../brainstorms/2026-03-15-wealth-macro-intelligence-suite-brainstorm.md) — Approach selection, key decisions
- [RLS Subselect Slowdown](../performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md) — Critical for MacroReview RLS policy
- [Thread-Unsafe Rate Limiter](../runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md) — Prerequisite fix for concurrent domain fetching
- [FRED API Key Case Mismatch](../runtime-errors/fred-api-key-case-mismatch-MarketDataEngine-20260315.md) — Silent failure pattern for FRED config
- [Alembic Migration FK/RLS Ordering](../database-issues/alembic-monorepo-migration-fk-rls-ordering.md) — Migration phasing patterns
- [Vertical Engine Extraction](../architecture-patterns/vertical-engine-extraction-patterns.md) — BaseAnalyzer, ProfileLoader, ConfigService patterns
- [Platform Plan](../../plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md) — Multi-tenant architecture foundation
- [ConfigService Plan](../../plans/2026-03-14-feat-customizable-vertical-config-plan.md) — Configuration system used by macro_intelligence

## Metrics

- **Total LOC:** ~3,500 across 27 files
- **Tests:** 65 new (280 total, all passing)
- **Migrations:** 2 (0005 + 0006)
- **API Endpoints:** 7
- **FRED Series:** 45 across 5 domains
- **Review Agents:** 18 (2 rounds of 9)
- **Bugs Found by Review:** 6 critical + 5 important
- **YAGNI Removed:** ~45 LOC
