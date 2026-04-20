---
title: EDHEC Quant Gap Closure — Sprint Strategy
date: 2026-04-19
author: wealth-architect (design round 1) + consolidation
status: approved — Cenário X3
scope: G1 Robust Sharpe, G2 ENB Meucci, G3 Attribution Cascade (3 fases), G4 EVT, G5 IPCA prod (Tiingo-fed)
non-goals: G6 copula, G7 entropy, Climate/ESG/TCFD/Carbon
---

# Quant Gap Closure — Sprint Strategy for EDHEC Parity (P0 + P1, Cenário X3)

**Audience:** senior engineer translating this into Opus execution prompts
**Scope:** G1 Robust Sharpe, G2 ENB Meucci, G3 Attribution Cascade (3 fases), G4 EVT, G5 IPCA prod
**Explicit non-goals:** G6 copula, G7 entropy, Climate/ESG/TCFD/Carbon

---

## 1. Sprint Phasing (Cenário X3 — 9 semanas)

The cascade **must** lead. Brinson-Fachler is currently shipped but empty (no inputs wired) — that is visible silence in DD ch.4. Every day it sits broken is a day the institutional credibility of the DD Report degrades. G1+G2 are additive enhancements to already-populated surfaces (scoring, dashboards); G3 unblocks a chapter that currently shows a placeholder.

Tiingo Fundamentals (Power tier, Andrei's account) unlocks G5 IPCA full (6 chars Kelly-Pruitt-Su) without blocking the quant track — data-layer reviewer is orthogonal to quant-math reviewer. Timeline stays 9 weeks.

```
S1  G1 + G2 + G3-F1                     (3 PRs paralelos, quant reviewer)
S2  G3-F2 + GICS diagnostic (+3-4d buffer) + 0133 condicional
S3  G3-F3 + 0132 canonical_map          ‖  Tiingo worker (data reviewer)
S4  G4 EVT                              ‖  Equity characteristics matview + backfill
S5  G5 IPCA prod (6 chars, Option A)
S6  Hardening + DD ch.4 cascade (4ª via completa)
S7  Agent-native surfaces (Fund Copilot IPCA queries)
S8  E2E + prod rollout
S9  Slack / institutional readiness
```

**S1 collision analysis** — zero real overlap:
- PR-Q1 (G1) touches `scoring_service.py` + new `scoring_components/robust_sharpe.py` + migration for `sharpe_cf` cols + worker `global_risk_metrics`
- PR-Q2 (G2) is new-file-only `diversification_service.py`; derives factor_cov internally (zero change to `factor_model_service.py`)
- PR-Q3 (G3-F1) lives in `vertical_engines/wealth/attribution/`
- Merge order: Q3 → Q2 → Q1 (Q1 last, flag default OFF)

---

## 2. Critical Path

```
         [G1 Robust Sharpe] ──┐
                              │
         [G2 ENB Meucci] ─────┼──► DD ch.5 Risk Framework (additive)
                              │
[G3 Fase1 returns-based] ─────┼──► DD ch.4 Performance (FIRST content)
            │                 │
            ▼                 │
[GICS diagnosis → 0133?] ─────┤
            │                 │
            ▼                 │
[G3 Fase2 holdings-based] ────┼──► DD ch.4 upgrade + screener holdings facet
            │                 │
            ▼                 │
[G3 Fase3 benchmark proxy] ───┘──► DD ch.4 Brinson-Fachler restored
            │                                     ▲
            │                                     │
[Tiingo worker] ──► [chars matview] ──► [G5 IPCA prod] ──► 4ª via cascata
            │
[G4 EVT] ──► DD ch.5 tail metrics (independent branch)
```

Hard dependencies:
- G3-F3 depends on G3-F2 (proxy resolves `primary_benchmark → canonical ETF → holdings_based(ETF)`)
- G5-prod depends on Tiingo worker + chars matview (all three Tiingo-chain must ship before S5)
- G2 depends on existing `factor_model_service.decompose_portfolio()` returning loadings + factor_returns (confirmed)

Independent: G1, G4.

---

## 3. PR Decomposition (9 PRs)

| PR | Title | Branch | LOC | Sprint |
|---|---|---|---|---|
| PR-Q1 | `feat(quant/g1): robust Sharpe with Cornish-Fisher + Opdyke CI` | `feat/quant-g1-robust-sharpe` | ~280 | S1 |
| PR-Q2 | `feat(quant/g2): effective number of bets (Meucci 2009 + Minimum Torsion 2013)` | `feat/quant-g2-enb-meucci` | ~220 | S1 |
| PR-Q3 | `feat(wealth/g3-fase1): returns-based style attribution` | `feat/wealth-g3-returns-based` | ~480 | S1 |
| PR-Q4 | `feat(wealth/g3-fase2): holdings-based attribution via N-PORT + matview + GICS diagnostic + 0133 conditional` | `feat/wealth-g3-holdings-based` | ~750 | S2 |
| PR-Q5 | `feat(wealth/g3-fase3): benchmark proxy attribution + canonical ETF map (0132)` | `feat/wealth-g3-benchmark-proxy` | ~320 | S3 |
| PR-Q6 | `feat(quant/g4): EVT extreme risk via POT + GPD fit` | `feat/quant-g4-evt-gpd` | ~620 | S4 |
| PR-Q7 | `feat(ingest/tiingo-fundamentals): statements + daily hypertables + worker 900_060` | `feat/tiingo-fundamentals-worker` | ~950 | S3 (parallel) |
| PR-Q8 | `feat(quant/equity-chars): equity_characteristics_monthly matview + refresh hook` | `feat/equity-characteristics-matview` | ~350 | S4 (parallel) |
| PR-Q9 | `feat(quant/g5): IPCA production (Kelly-Pruitt-Su, 6 chars) + 4th attribution rail` | `feat/quant-g5-ipca-prod` | ~1100 | S5 |

Branch convention: `feat/quant-*` for pure `quant_engine/` changes, `feat/wealth-*` when surface crosses into `vertical_engines/wealth/`, `feat/ingest-*` for data ingestion workers.

---

## 4. Integration Points

**G1 Robust Sharpe**
- `quant_engine/scoring_service.py` — `risk_adjusted_return` component branches on `ScoringConfig.use_robust_sharpe`
- `vertical_engines/wealth/dd_report/chapters/ch5_risk.py` (verificar) — expose traditional + robust + CI as table row
- ConfigService: new key `wealth.scoring.use_robust_sharpe` (default false); rollback = flip flag

**G2 ENB**
- New `quant_engine/diversification_service.py` — pure function, no state
- Consumers: `construction_run_executor` worker (lock 900_101) persists to `portfolio_construction_runs.diversification_metrics` JSONB; DD ch.5; `(terminal)/builder/[run_id]` stress tab
- Minimum Torsion (Meucci 2013) default for DD; entropy-based for scoring (latency cheaper)

**G3 Fase 1 — returns-based**
- Dispatcher `attribution/service.py` decides which rail runs per fund
- Reads `nav_timeseries` (fund) + `benchmark_nav` (SPY/IWM/EFA/EEM/AGG/HYG/LQD)
- Feeds: `dd_report/chapters/ch4_performance.py`

**G3 Fase 2 — holdings-based**
- Reads `sec_nport_holdings` (global hypertable). Aggregates via matview `mv_nport_sector_attribution`
- GICS diagnostic runs **first** (Cenário A/B/C decision tree); 0133 SIC→GICS only if Cenário B
- Feeds: DD ch.4 (higher confidence than F1) + screener holdings facet

**G3 Fase 3 — benchmark proxy + Brinson-Fachler wake-up**
- New table `benchmark_etf_canonical_map` (migration 0132; 20 seed rows inline)
- `sec_registered_funds.primary_benchmark` → canonical map → ETF ticker → call Fase 2
- `brinson_fachler.py` gets two real inputs and computes allocation/selection/interaction

**G4 EVT**
- Extension to `quant_engine/cvar_service.py`. `extreme_var_evt(returns, q, threshold_method)` → `(var, xi_shape, u_threshold, fit_diag)`
- Surface: DD ch.5 only. NOT in scoring. Telemetry in `portfolio_stress_results` JSONB

**G5 IPCA (Tiingo-fed)**
- Tiingo worker (lock 900_060) → 2 hypertables (statements, daily) → matview `equity_characteristics_monthly` (6 chars)
- `bkelly-lab/ipca` ALS fits quarterly via `ipca_estimation` worker (lock 900_091 reserved)
- 4th rail in `attribution/service.py` dispatcher: `r_fund = α + Σ β_k f_k + ε`
- Vantagem vs returns-based: cobre funds com <36m histórico quando IPCA foi fitado em universo amplo

---

## 5. Smart-Backend / Dumb-Frontend Checkpoints

**NEVER in UI strings:**

| Quant term | Sanitized UI copy |
|---|---|
| Cornish-Fisher expansion | "Robust Sharpe" or "Skew/kurtosis-adjusted Sharpe" |
| Opdyke 95% CI | "Statistical confidence range" |
| Effective Number of Bets / Meucci | "Diversification strength (higher = more independent bets)" |
| GPD shape parameter ξ | "Tail heaviness" (Light / Normal / Heavy / Extreme) |
| Peaks-over-threshold u | Never shown. Only derived VaR quantile |
| IPCA β / factor loading | "Style exposure" per factor (Value / Momentum / Quality) |
| Brinson-Fachler allocation/selection/interaction | "Why the manager beat/lagged: asset mix vs stock picks vs timing" |

Rule: if an analyst couldn't paraphrase it to a family-office CIO in one sentence without whiteboard, it belongs in a tooltip's "methodology" footnote, not in the primary label.

---

## 6. Confidence Badges — DD ch.4 Attribution Rail Selector

Dispatcher decides per fund, in order of preference:

1. **Holdings-based (Fase 2)** — available iff fund ∈ `registered_us ∪ etf ∪ bdc` AND latest `sec_nport_holdings` snapshot ≤9 months old. Badge: **HIGH CONFIDENCE — position-level**
2. **IPCA (G5)** — when rail ships AND IPCA OOS R² ≥ 0.50 for fund's asset class. Badge: **MEDIUM-HIGH CONFIDENCE — factor model**
3. **Benchmark proxy (Fase 3)** — available iff `primary_benchmark` present + canonical map hit + ETF has holdings. Badge: **MEDIUM CONFIDENCE — benchmark proxy** + secondary line "Benchmark: S&P 500 → tracked via SPY"
4. **Returns-based (Fase 1)** — fallback for funds sem holdings e sem benchmark. Badge: **LOW-MEDIUM CONFIDENCE — style regression** + "Based on 36 months of returns"
5. **None** — <36 months NAV. Badge: **INSUFFICIENT DATA**

Badges are Netz-owned enum values (`RAIL_HOLDINGS`, `RAIL_IPCA`, `RAIL_PROXY`, `RAIL_RETURNS`, `RAIL_NONE`) stored on `dd_report_chapters.metadata`; frontend maps to copy. No quant vocabulary leaks.

---

## 7. Risk Register (Top 5)

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | `benchmark_etf_canonical_map` covers <70% of `primary_benchmark` (vendor-inconsistent strings) | High | Degrades F3 rail | 20 seeded mappings + pg_trgm fuzzy + asset_class fallback; audit table tracks coverage |
| R2 | GICS diagnosis returns Cenário C (both industry_sector AND SIC null) | Low | Cripples F2 | Replan F2 to `issuer_category × country` with confidence='low' flag; wealth-architect replan triggered |
| R3 | Tiingo SLA/restatement gaps break IPCA fit | Medium | Kills G5 | Row versioning via `filing_date`; `DISTINCT ON` query picks latest; missingness >5% → alert + degrade to Option B momentum+size only |
| R4 | G2 ENB requires factor_loadings; PCA unavailable for <36m funds | Medium | 10-15% universe NaN | Degrade to "N/A — insufficient history"; never fabricate |
| R5 | G1 Robust Sharpe with <36 months produces wide CI, rank-flips | Low | Scoring instability on new funds | Flag per-tenant; require ≥60 months for production; below → report traditional only |

---

## 8. Acceptance Criteria (per PR)

1. **`make check` green** — lint + import-linter + mypy + pytest
2. **Unit tests minimum**: Q1 ≥12, Q2 ≥8, Q3 ≥20, Q4 ≥25, Q5 ≥15, Q6 ≥18, Q7 ≥15, Q8 ≥10, Q9 ≥25
3. **DD Report integration test** — Q3/Q4/Q5/Q9 must include e2e rendering ch.4 for seeded fund + rail badge assertion
4. **Stability Guardrails checklist** — PR description ticks P1–P6. P3 isolation (no new module-level asyncio primitives). P5 idempotent (attribution recompute safe for same `fund_id × asof`)
5. **RLS audit** — no `organization_id` leaks in new queries; global hypertables unfiltered, tenant-scoped tables JOIN `instruments_org`
6. **No new external API calls in hot path** — G3 reads `sec_nport_holdings` only. G4 reads `nav_timeseries`. Tiingo only in worker
7. **Feature flag** — all new outputs behind ConfigService flag defaulting off in prod for one release
8. **Migration reversibility** — all migrations (0132, 0133 conditional, Tiingo hypertables) have `downgrade()` that drops clean
9. **Invariant scanner** — blocklist terms in DD copy strings: cornish-fisher, gpd, meucci, brinson-fachler, ipca, cvar, kurtosis, opdyke
10. **Performance** — DD ch.4 render ≤2s p95 with F2 on 200-holdings fund

---

## 9. Deferrals / Non-Goals

- G6 copula dependence structures — deferred indefinitely
- G7 entropy-based diversification — ENB sufficient
- Climate / ESG / Carbon / TCFD — removed from roadmap
- Factor zoo expansion beyond IPCA — separate backlog
- Intraday / tick-level EVT — daily only
- Cross-asset Brinson (equity + FI one report) — single-asset-class per chapter
- Self-service benchmark registration by tenants — curated globally
- Full fundamentals expansion beyond 6 chars (quality subcomponents, working capital detail) — separate sprint

---

## 10. Open Questions Resolved

- **Lock ID Tiingo worker**: 900_060 (user decision)
- **G5 staged validation**: skip (Option A direct; `bkelly-lab/ipca` ALS already validated in paper)
- **Tiingo ToS**: Power tier covers development; Andrei will upgrade to Enterprise at SaaS stage
- **X3 vs Y**: X3 approved

---

## 11. Final Sequencing Call

Start **S1 Monday**: kick `feat/quant-g1-robust-sharpe`, `feat/quant-g2-enb-meucci`, `feat/wealth-g3-returns-based` as three independent Opus tasks. Merge G1/G2 within 10 days; G3-F1 lands mid-W2 and unblocks first real ch.4 output. F2 immediately after F1. F3 waits on F2. Tiingo worker starts S3 in parallel (different reviewer). G4 S4. G5 S5 using characteristics matview that shipped S4.

The longest visible-value-to-user gap right now is **empty ch.4**. Fix it in 2 weeks.
