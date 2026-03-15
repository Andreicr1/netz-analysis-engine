---
date: 2026-03-15
topic: wealth-macro-intelligence-suite
---

# Wealth Macro Intelligence Suite — Top-Down Analysis & Tactical Allocation

## What We're Building

A comprehensive top-down macro analysis suite for the Wealth Management vertical that flows: **Global Macro → Regional Analysis → Sector Rotation → Tactical Asset Allocation**. The system generates tactical allocation proposals (deviations from strategic targets) that a Macro Committee reviews and approves.

Today, Netz Wealth has strong bottom-up capabilities (backtest, optimization, CVaR, rebalance) but zero top-down intelligence. Tactical positions are 100% manual. This suite closes the gap, creating an institutional-grade macro-driven investment process.

## Why This Approach

Three approaches were considered:

1. **Macro Intelligence Layer (chosen)** — New composable services (RegionalMacro, PredictiveSignal, SectorRotation, TacticalAllocation) + MacroCommittee workflow. Modular, testable, phased delivery.
2. **Dashboard + Manual Tactical** — Visibility first, automation later. Lower risk but defers the most valuable part (tactical suggestions).
3. **Predictive-First** — Start with the quantitative model. Rejected because it requires regional data that doesn't exist yet (circular dependency).

Approach 1 was chosen because each phase delivers standalone value, the architecture scales with the platform, and it integrates naturally with the existing `regime_service` and `quant_engine/` patterns.

## Key Decisions

- **Geographic scope:** Global from day one (US, Europe, Asia, Emerging Markets)
- **Data sources:** FRED as global bridge + Eurostat API for European granularity in future phase. Commodities + geopolitical risk indices included from Phase 1.
- **Macro → Tactical flow:** System generates tactical allocation proposals (suggested deviations from strategic allocation within pre-defined bands). Macro Committee approves, adjusts, or rejects. Not fully automatic.
- **Regime architecture:** Hierarchical — one global regime (defines risk budget) + per-region regimes (define where to allocate). Expands existing `regime_service` rather than replacing it.
- **Sector taxonomy:** GICS 11 sectors at macro level + strategic sub-sectors. Scoring: over/under/neutral per sector based on economic cycle + regional signals. (Future phase)
- **Committee cadence:** Monthly full macro review + weekly snapshot (delta: "what changed this week"). Audience: CIO + portfolio managers (internal).
- **FRED path unification:** The two existing parallel FRED paths must converge through the universal `quant_engine/fred_service.py`.
- **Geopolitical neutrality:** System measures intensity of stress and disruption — never classifies nations, never favors geopolitical outcomes. Data is neutral; interpretation is the committee's job.

## Resolved Questions

1. **FRED international series lag (30-60 days):** Accept lag for most indicators with staleness flags + weight reduction via per-frequency linear decay.
2. **Mixed-frequency data (daily VIX vs quarterly GDP):** Use LOCF (Last Observation Carried Forward) with staleness-aware weight decay. No proxy adjustment needed.
3. **Tactical band width:** Configurable per profile AND per asset class via ConfigService.
4. **Committee voting model:** CIO approval only. No individual voting, no e-signatures. Simple approve/adjust workflow.
5. **Sector ETF data source:** Deferred to future phase.

## Next Steps

→ Plan at `docs/plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md`
