# Netz Analysis Engine — Complete System Map

**Date:** 2026-03-21
**Scope:** All services, pipelines, calculations, reports, content, and frontend tools across Credit and Wealth verticals.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Infrastructure Layer](#2-infrastructure-layer)
3. [AI Engine — Unified Document Pipeline](#3-ai-engine--unified-document-pipeline)
4. [Quant Engine — Calculations & Analytics](#4-quant-engine--calculations--analytics)
5. [Credit Vertical](#5-credit-vertical)
6. [Wealth Vertical](#6-wealth-vertical)
7. [Credit Frontend — Tools & Capabilities](#7-credit-frontend--tools--capabilities)
8. [Wealth Frontend — Tools & Capabilities](#8-wealth-frontend--tools--capabilities)
9. [End-to-End Pipeline Flows](#9-end-to-end-pipeline-flows)

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTENDS (SvelteKit)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│  │ Credit Intel  │  │ Wealth OS    │  │ Admin Panel  │                │
│  │ (team+investor│  │ (team+investor│  │ (super_admin)│                │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
│         │                  │                  │                        │
│         └──────────────────┴──────────────────┘                       │
│                            │ HTTP/SSE                                 │
└────────────────────────────┼──────────────────────────────────────────┘
                             │
┌────────────────────────────┼──────────────────────────────────────────┐
│                    FASTAPI BACKEND                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │ app/core/   │  │ app/domains/│  │ ai_engine/  │  │quant_engine│  │
│  │ auth, rls,  │  │ credit/     │  │ pipeline,   │  │ cvar, regime│ │
│  │ config, sse │  │ wealth/     │  │ classify,   │  │ optimizer, │  │
│  │ storage     │  │ admin/      │  │ extract,    │  │ scoring,   │  │
│  │             │  │             │  │ embed       │  │ drift, fred│  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │              vertical_engines/                                   │  │
│  │  credit/ (12 packages)          wealth/ (8 engines)             │  │
│  │  memo, critic, edgar, quant,    dd_report, fact_sheet,          │  │
│  │  sponsor, kyc, pipeline,        macro_committee, screener,      │  │
│  │  portfolio, domain_ai,          quant_analyzer, correlation,    │  │
│  │  deal_conversion, market_data   attribution, fee_drag           │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬────────────────────────────────────────────┘
                           │
┌──────────────────────────┼────────────────────────────────────────────┐
│                    DATA LAYER                                         │
│  ┌──────────────┐  ┌──────────┐  ┌────────────┐  ┌───────────────┐  │
│  │ PostgreSQL 16│  │ Redis 7  │  │LocalStorage│  │ External APIs │  │
│  │ + pgvector   │  │ pub/sub  │  │ .data/lake/│  │ OpenAI,Mistral│  │
│  │ + TimescaleDB│  │ jobs,    │  │ bronze/    │  │ FRED, SEC     │  │
│  │              │  │ idempot. │  │ silver/    │  │ Clerk, Yahoo  │  │
│  │              │  │          │  │ gold/      │  │ OFR, Treasury │  │
│  └──────────────┘  └──────────┘  └────────────┘  └───────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 2. Infrastructure Layer

### 2.1 Authentication (Clerk JWT v2)

| Component | Purpose |
|-----------|---------|
| `get_actor()` | Verify JWT, extract Actor (actor_id, roles, organization_id) |
| `require_role(*roles)` | Dependency factory for role-based endpoint access |
| `require_fund_access()` | Fund-level access with lazy membership resolution from DB |
| Dev bypass | `X-DEV-ACTOR` header (JSON) or static `dev_token` |

**Roles:** SUPER_ADMIN, ADMIN, INVESTMENT_TEAM, GP, DIRECTOR, COMPLIANCE, AUDITOR, INVESTOR, ADVISOR

### 2.2 Multi-Tenancy (RLS)

| Component | Purpose |
|-----------|---------|
| `get_db_with_rls()` | AsyncSession + `SET LOCAL app.current_organization_id` |
| `get_db_admin()` | Cross-tenant admin session (sets `app.admin_mode = 'true'`) |
| `OrganizationScopedMixin` | Base mixin adding `organization_id` column to all tenant tables |

**Critical:** RLS policies use `(SELECT current_setting(...))` subselect (not bare call) to avoid 1000x slowdown.

### 2.3 Configuration (ConfigService)

Cascade resolution: **TTL Cache (60s) → DB Override (tenant) → DB Default (global) → YAML fallback (emergency)**

- `VerticalConfigDefault` — Global seed data, no RLS
- `VerticalConfigOverride` — Tenant-scoped sparse overrides, deep-merged at read time
- `CLIENT_VISIBLE_TYPES` — IP protection (prompts never exposed to clients)

### 2.4 Storage Abstraction

| Backend | Feature Flag | Usage |
|---------|-------------|-------|
| `LocalStorageClient` | default | Filesystem at `.data/lake/` — dev and production until Milestone 3 |
| `R2StorageClient` | `FEATURE_R2_ENABLED` | Cloudflare R2 S3-compatible |
| `ADLSStorageClient` | `FEATURE_ADLS_ENABLED` | Azure ADLS Gen2 (deprecated, kept for rollback) |

**Path convention:** `{tier}/{organization_id}/{vertical}/...` with regex-validated segments.

### 2.5 Jobs & SSE (Redis Pub/Sub)

| Component | Purpose |
|-----------|---------|
| `publish_event(job_id, event_type, data)` | Push progress event to Redis channel |
| `create_job_stream(request, job_id)` | EventSourceResponse for SSE |
| `register_job_owner(job_id, org_id)` | Job→org mapping with 1hr TTL |
| `idempotent_worker_wrapper()` | Redis-based dedup for background workers |

Frontend uses `fetch()` + `ReadableStream` (not EventSource — needs auth headers).

### 2.6 Audit Trail

- `write_audit_event()` → Immutable `AuditEvent` rows (before/after JSONB snapshots)
- Correlated via `request_id` across all operations in a request

---

## 3. AI Engine — Unified Document Pipeline

Single ingestion path for all sources (UI, batch, API). Vertical-agnostic.

```
PDF Input
  ↓
[0] Pre-filter ──── skip compliance forms (W-8BEN, FATCA, KYC)
  ↓
[1] OCR ─────────── Mistral API (mistral-ocr-latest) → Markdown + HTML tables
  ↓
[GATE 1] ────────── min 100 chars, max 30% non-printable
  ↓
[2] Classification ─ 3-layer hybrid (rules → TF-IDF cosine → LLM fallback)
  ↓
[GATE 2] ────────── doc_type ∈ 31 canonical types, confidence ≥ 0.3
  ↓
[3] Governance ──── 15 deterministic regex patterns (side_letter, MFN, clawback...)
  ↓
[4] Chunking ────── Semantic markdown chunking, size-adaptive by doc_type
  ↓
[GATE 3] ────────── chunks > 0, content loss < 25%
  ↓
[5] Extraction ──── Parallel metadata + summarization (GPT-4.1)
  ↓
[6] Embedding ───── text-embedding-3-large (3072 dimensions)
  ↓
[GATE 4] ────────── count match, dimension match, no NaN
  ↓
[7] Storage ─────── Dual-write: LocalStorage/ADLS (truth) → pgvector (index)
  ↓
Searchable Index
```

### 3.1 Classification — Hybrid 3-Layer

| Layer | Coverage | Method | Confidence |
|-------|----------|--------|------------|
| Layer 1 | ~60% | 28 filename regex + 12 content regex | 1.0 (certainty) |
| Layer 2 | ~30% | TF-IDF cosine similarity vs exemplar descriptions | cosine score |
| Layer 3 | ~10% | gpt-4.1-mini LLM fallback | LLM 0-100 → 0.0-1.0 |

**31 canonical doc types:** legal_lpa, legal_side_letter, legal_subscription, financial_statements, financial_nav, fund_presentation, credit_policy, investment_memo, risk_assessment, etc.

**6 vehicle types:** standalone_fund, fund_of_funds, feeder_master, direct_investment, spv, other

### 3.2 Storage Paths

| Tier | Path | Content |
|------|------|---------|
| Bronze | `bronze/{org_id}/{vertical}/documents/{doc_id}.json` | Raw OCR text |
| Silver | `silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet` | Chunks + embeddings (zstd) |
| Silver | `silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json` | Classification + extraction |
| Gold | `gold/{org_id}/{vertical}/memos/{deal_id}/...` | Generated reports |

### 3.3 Search Rebuild

`search_rebuild.py` reconstructs pgvector from silver Parquet without re-OCR/re-embed. Validates `embedding_dim` match before upsert.

---

## 4. Quant Engine — Calculations & Analytics

All services accept optional `config` parameter (never read YAML directly). Pure computation functions are sync; I/O functions are async.

### 4.1 Risk Services

| Service | Key Functions | Outputs |
|---------|--------------|---------|
| **CVaR** (`cvar_service.py`) | `compute_cvar_from_returns(returns, 0.95)` | (cvar, var) as negative floats |
| | `check_breach_status(profile, cvar, days)` | BreachStatus: trigger_status, utilization_pct |
| | `classify_trigger_status(util_pct, days)` | "ok" / "warning" / "breach" |
| **Regime** (`regime_service.py`) | `classify_regime_multi_signal(vix, yield_curve, cpi, sahm)` | CRISIS > INFLATION > RISK_OFF > RISK_ON |
| | `get_current_regime(db)` | RegimeRead from macro_data table |
| | `classify_regional_regime(region, signals)` | Per-region via ICE BofA OAS spreads |
| | `compose_global_regime(regional)` | GDP-weighted aggregation |
| **Drift** (`drift_service.py`) | `compute_block_drifts(current, target, thresholds)` | BlockDrift[]: ok / maintenance / urgent |
| | `compute_dtw_drift(fund_returns, bench_returns)` | DtwDriftResult: DTW distance score |
| **Stress** (`stress_severity_service.py`) | `compute_stress_severity(snapshot)` | score (0-100), level (none/mild/moderate/severe) |

### 4.2 Portfolio Optimization

| Service | Key Functions | Outputs |
|---------|--------------|---------|
| **Optimizer** (`optimizer_service.py`) | `optimize_portfolio(blocks, returns, cov, constraints)` | weights, expected_return, Sharpe, volatility |
| | `optimize_portfolio_pareto(...)` | NSGA-II Pareto front (2-3 objectives), 45-135s. Runs as background job with SSE progress. |
| | `parametric_cvar_cf(weights, mu, cov, skew, kurt)` | Cornish-Fisher adjusted CVaR |
| **Metrics** (`portfolio_metrics_service.py`) | `aggregate(portfolio_returns, bench_returns)` | Sharpe, Sortino, max_drawdown, information_ratio |
| **Scoring** (`scoring_service.py`) | `compute_fund_score(metrics, lipper, flows)` | Composite 0-100 score (6 weighted dimensions). Momentum pre-computed by worker. |
| **Backtest** (`backtest_service.py`) | `walk_forward_backtest(returns, weights, n_splits)` | Per-fold Sharpe, CVaR, drawdown. Results cached in Redis (1h TTL). |
| **Rebalance** (`rebalance_service.py`) | `determine_cascade_action(trigger, prev, util, days)` | State machine: ok → warning → breach → hard_stop |

### 4.3 Technical & Momentum

| Service | Key Functions | Outputs |
|---------|--------------|---------|
| **Momentum** (`talib_momentum_service.py`) | `compute_momentum_signals_talib(close)` | RSI(14), Bollinger position, momentum_score 0-100 |
| | `compute_flow_momentum(nav, net_flows)` | OBV-style accumulation slope |
| **Correlation** (`correlation_regime_service.py`) | `compute_correlation_regime(returns_matrix)` | Correlation matrix, contagion pairs, diversification ratio, absorption ratio |
| **Attribution** (`attribution_service.py`) | `compute_attribution(portfolio, benchmark)` | Brinson-Fachler: allocation + selection + interaction effects |

### 4.4 External Data Services (DB-First Pattern)

All external time-series data is ingested by background workers into TimescaleDB hypertables. Routes and vertical engines read from DB only — never call external APIs in user-facing requests.

| Service | Source | Auth | Hypertable | Ingestion Worker |
|---------|--------|------|-----------|-----------------|
| **FRED** (`fred_service.py`) | Federal Reserve | `FRED_API_KEY` | `macro_data` | `macro_ingestion` (~65 series: 4 regions + global + credit) |
| **Treasury** (`fiscal_data_service.py`) | US Treasury | None | `treasury_data` | `treasury_ingestion` (rates, debt, auctions, FX, interest) |
| **OFR** (`ofr_hedge_fund_service.py`) | SEC/CFTC/FRB | None | `ofr_hedge_fund_data` | `ofr_ingestion` (leverage, AUM, strategy, repo, stress) |
| **Data Commons** (`data_commons_service.py`) | Google | `DC_API_KEY` | — (on-demand) | — |

**DB reader functions:** Each service provides `get_*_from_db()` async functions that read from the hypertable instead of calling the API. Callers should prefer DB readers; API functions are used only by workers.

**Credit market_data:** Reads all macro data from `macro_data` hypertable (zero FRED API calls at runtime). Regional Case-Shiller (20 metros) also from `macro_data`. The `fred_client.py` has been eliminated.

### 4.5 Macro Intelligence

| Service | Key Functions | Outputs |
|---------|--------------|---------|
| **Regional Macro** (`regional_macro_service.py`) | `score_region(region, observations)` | Composite 0-100 per region (US, EU, ASIA, EM) via 6 dimensions |
| | `score_global_indicators(observations)` | geopolitical_risk, energy_stress, commodity_stress, usd_strength |
| | `CREDIT_SERIES` (24 + 20 Case-Shiller) | Credit-specific FRED series ingested alongside regional data |
| **Snapshot Builder** (`macro_snapshot_builder.py`) | `build_regional_snapshot(observations)` | Assembled snapshot for macro_regional_snapshots |

---

## 5. Credit Vertical

### 5.1 Vertical Engines (12 Packages)

| Package | Service Function | Contract | Purpose |
|---------|-----------------|----------|---------|
| **critic** | `critique_intelligence(context, call_openai_fn)` | Never-raises | Adversarial IC critique → fatal_flaws, material_gaps, optimism_bias, confidence_score |
| **deal_conversion** | `convert_pipeline_to_portfolio(db, deal_id, fund_id)` | Raises | Pipeline→portfolio conversion with vector chunk reclassification |
| **domain_ai** | `run_deal_ai_analysis(db, deal_id, domain)` | Never-raises | RAG + GPT analysis for pipeline or portfolio mode |
| **edgar** | `fetch_edgar_data(entity_name)` | Never-raises | SEC EDGAR: CIK resolution, financials, ratios, going concern, insider signals |
| | `fetch_edgar_multi_entity(entities)` | Never-raises | Parallel multi-entity with CIK dedup |
| **kyc** | `run_kyc_screenings(analysis, deal_fields)` | Never-raises | PEP, sanctions, adverse media screening via KYC Spider |
| **market_data** | `get_macro_snapshot(db, deal_geography)` | Never-raises | Daily-cached FRED macro + regional Case-Shiller |
| **memo** | `generate_memo_book(db, evidence_pack, ...)` | Never-raises | 14-chapter IC memo with per-chapter evidence budgets |
| | `async_generate_memo_book(...)` | Never-raises | Parallel via asyncio.TaskGroup (Semaphore 5) |
| **pipeline** | `run_pipeline_ingest(db, fund_id)` | Returns dict | Orchestrate deal discovery, document aggregation, intelligence profiles |
| **portfolio** | `run_portfolio_ingest(db, fund_id)` | Never-raises | 7 sub-engines: metrics, drift, covenants, liquidity, risk, monitoring |
| **quant** | `compute_quant_profile(analysis, deal_fields, macro)` | Raises | Maturity, rate decomposition, sensitivity, scenarios, risk-adjusted returns |
| **sponsor** | `analyze_sponsor(corpus, deal_fields, analysis)` | Never-raises | Sponsor profile, key persons, governance red flags, reputation signals |

### 5.2 Deep Review V4 — 13-Stage IC Memorandum Pipeline

```
[1] Cache check (artifact versioning)
[2] Deal lookup & validation
[3] RAG context extraction (per-chapter specialized retrieval)
[4] Structured deal analysis (GPT-4o → structured_analysis_v2)
[5] Macro snapshot injection (FRED, deterministic)
[6] Quant profile computation (deterministic)
[7] Concentration profile (deterministic)
[8] Hard policy checks (deterministic)
[9] Policy compliance assessment (LLM)
[10] Sponsor & KYC analysis (LLM + external API)
[11] Evidence pack building (frozen truth surface, ≤5k tokens)
[12] IC Critic loop (adversarial LLM review)
[13] 14-Chapter Memo Book generation (LLM × 14)
[14] Atomic versioned persist
```

### 5.3 IC Memo — 14 Chapters

| # | Tag | Chapter | Evidence Budget |
|---|-----|---------|----------------|
| 1 | ch01_exec | Executive Summary | Critical (30 chunks × 8000 chars) |
| 2 | ch02_macro | Market Context | Analytical (20 × 4000) |
| 3 | ch03_exit | Macro Regime & Exit Environment | Analytical |
| 4 | ch04_sponsor | Sponsor & Management Analysis | Analytical |
| 5 | ch05_legal | Legal Structure & Document Analysis | Critical |
| 6 | ch06_terms | Detailed Investment Terms & Covenants | Critical |
| 7 | ch07_capital | Capital Structure Analysis | Analytical |
| 8 | ch08_returns | Return Modeling | Analytical |
| 9 | ch09_downside | Downside Scenario Model | Analytical |
| 10 | ch10_covenants | Covenant Strength Assessment | Analytical |
| 11 | ch11_risks | Key Risks | Analytical |
| 12 | ch12_peers | Peer Comparison | Lightweight (10 × 3000) |
| 13 | ch13_recommendation | Final Recommendation | Synthesis-only (no raw evidence) |
| 14 | ch14_governance_stress | Governance Under Adverse Event & Stress | Forced sources: credit_policy, investment_policy |

**Appendices:** A1 = Source Citation Index, A2 = Critical Data Gaps

### 5.4 Credit Quant Profile Outputs

| Category | Metrics |
|----------|---------|
| Maturity | maturity_years, confidence, tenor_bucket (<1y, 1-3y, 3-5y, >5y) |
| Rate Decomposition | gross_coupon, base_rate, spread_bps, floor_bps, fee_stack, net_return_proxy |
| Credit Metrics | prob_default, loss_given_default, expected_loss |
| Sensitivity | 2D rate/leverage grids, 3D summary |
| Scenarios | Base case, downside, stress (deterministic) |
| Risk-Adjusted | expected_return, risk_adjusted_return, liquidity_hooks |

### 5.5 Credit Domain Modules

| Module | Tables | Purpose |
|--------|--------|---------|
| **deals/** | PipelineDeal, Deal, DealStageHistory, DealEvent, DealConversionEvent, DealCashflow | Pipeline management, stage transitions, cashflow analytics (MOIC, IRR) |
| **portfolio/** | ActiveInvestment | Post-conversion asset-centric portfolio view |
| **documents/** | Document, DocumentVersion, DocumentRootFolder | Upload, ingestion, classification lifecycle |
| **ai/** | MemoChapter, EvidencePack | IC memo persistence with chapter versioning |
| **reporting/** | NAVSnapshot, ReportPack | NAV snapshots, investor statement generation |
| **dashboard/** | — | Aggregated fund-level analytics |
| **dataroom/** | — | Folder governance, access control |
| **actions/** | — | Covenant violation alerts, monitoring actions |
| **global_agent/** | — | Fund Copilot RAG (Q&A, document search) |

---

## 6. Wealth Vertical

### 6.1 Vertical Engines

| Engine | Key Functions | Purpose |
|--------|--------------|---------|
| **DDReportEngine** | `generate(db, instrument_id, actor_id)` | 8-chapter fund DD report (sequential, never-raises) |
| **FundAnalyzer** | BaseAnalyzer implementation | Orchestrates DD reports + portfolio analysis for liquid_funds profile |
| **MacroCommitteeEngine** | `generate_weekly_report()` | Regional macro scores, regime transitions, staleness alerts |
| **QuantAnalyzer** | CVaR, scoring, peer comparison | Portfolio-level quantitative analysis |
| **FactSheetEngine** | `generate(db, portfolio_id, format, language)` | Executive + Institutional PDF renderers (PT/EN i18n) |
| **InvestmentOutlook** | `generate(db, org_id, actor_id)` | Quarterly macro narrative with regional outlook |
| **FlashReport** | `generate(db, org_id, actor_id)` | Event-driven market flash (48h cooldown) |
| **ManagerSpotlight** | `generate(db, instrument_id)` | Deep-dive single fund manager analysis |
| **ScreenerService** | 3-layer deterministic screening | Eliminatory → Mandate Fit → Quant Scoring |
| **CriticService** | Adversarial chapter review | Circuit-breaker (3min timeout), ACCEPT/REFINE/ESCALATE verdicts |
| **CorrelationService** | `compute_correlation_regime()` | Rolling correlation, Marchenko-Pastur denoising, absorption ratio |
| **AttributionService** | Policy benchmark attribution | Brinson-Fachler: allocation + selection + interaction |
| **FeeDragService** | `compute_fee_drag()` | Fee drag ratio, efficiency flag per instrument |
| **DriftMonitor** | `drift_scan()` | DTW style drift + universe removal impact |
| **WatchlistService** | `check_transitions()` | PASS→FAIL transition alerts |

### 6.2 DD Report — 8 Chapters

| # | Tag | Chapter | Token Budget |
|---|-----|---------|-------------|
| 1 | executive_summary | Executive Summary | 3000 |
| 2 | investment_strategy | Investment Strategy & Process | 2500 |
| 3 | fund_manager | Fund Manager Assessment | 4000 |
| 4 | performance | Performance Analysis | 4000 |
| 5 | risk_management | Risk Management Framework | 4000 |
| 6 | fees | Fee Analysis | 2500 |
| 7 | operational_dd | Operational Due Diligence | 2500 |
| 8 | recommendation | Recommendation | 4000 (sequential, depends on ch 1-7) |

**Confidence Scoring (deterministic, no LLM):**
- Chapter completeness (30%) + evidence coverage (25%) + quant data quality (25%) + critic outcome (20%)

**Decision Anchor:** APPROVE (≥70), CONDITIONAL (≥40), REJECT (>0), null (insufficient data)

**Approval Workflow:** draft → generating → pending_approval → approved/rejected(draft)

### 6.3 Screener — 3-Layer Deterministic Screening

| Layer | Purpose | Criteria |
|-------|---------|----------|
| Layer 1: Eliminatory | Hard gates | Asset class, liquidity, AUM minimum, rating |
| Layer 2: Mandate Fit | Client constraints | Currency, domicile, ESG, risk bucket |
| Layer 3: Quant Scoring | Peer percentile | Manager score, return, Sharpe, volatility |

### 6.4 Content Production

| Content Type | Engine | Trigger | Approval | PDF |
|-------------|--------|---------|----------|-----|
| DD Report | DDReportEngine | Manual per fund | IC role, self-approval blocked | Yes (PT/EN) |
| Fact Sheet | FactSheetEngine | Manual per portfolio | No (direct storage) | Yes (Executive/Institutional, PT/EN) |
| Investment Outlook | InvestmentOutlook | Manual trigger | Status workflow | Yes |
| Flash Report | FlashReport | Event-driven | Status workflow, 48h cooldown | Yes |
| Manager Spotlight | ManagerSpotlight | Manual per fund | Status workflow | Yes |
| Macro Review | MacroCommitteeEngine | Weekly trigger | Director/Admin approve | JSON (not PDF) |

### 6.5 Background Workers (13 Workers)

| Worker | Lock ID | Scope | Timeout | Purpose |
|--------|---------|-------|---------|---------|
| `ingestion` | — | org | 10m | NAV fetch from Yahoo Finance → nav_timeseries |
| `risk_calc` | 900_007 | org | 10m | Rolling CVaR, VaR, returns, volatility, **momentum** (RSI, Bollinger, OBV) → fund_risk_metrics |
| `portfolio_eval` | 900_008 | org | 5m | CVaR evaluation, regime detection → portfolio_snapshots |
| `macro_ingestion` | 43 | global | 10m | ~65 FRED series (4 regions + global + credit + 20 Case-Shiller metros) → macro_data + macro_regional_snapshots |
| `treasury_ingestion` | 900_011 | global | 10m | Treasury rates, debt, auctions, FX, interest expense → treasury_data |
| `ofr_ingestion` | 900_012 | global | 10m | Hedge fund leverage, AUM, strategy, repo, stress → ofr_hedge_fund_data |
| `fact_sheet_gen` | — | global | 10m | PDF generation for all active portfolios |
| `screening_batch` | — | org | 5m | Re-screen all instruments → instruments_screening_results |
| `watchlist_batch` | — | org | 5m | Watchlist transition detection, Redis pub/sub alerts |
| `instrument_ingestion` | 900_010 | org | 10m | NAV fetch for instruments_universe by provider |
| `benchmark_ingest` | 900_004 | global | 10m | Benchmark ticker NAV → benchmark_nav (global table) |
| `drift_check` | 42 | org | 5m | DTW drift scan across fund universe |
| `regime_fit` | — | org | 5m | Regime fitness evaluation |

All workers wrapped with `asyncio.wait_for(timeout)` + Redis idempotency guard (409 on concurrent trigger). Advisory locks use deterministic IDs (never `hash()`).

### 6.6 Wealth Domain Tables

| Table | Scope | Purpose |
|-------|-------|---------|
| `instruments_universe` | org | Polymorphic fund/bond/equity with JSONB attributes |
| `dd_reports` | org | DD report versioning with approval fields |
| `dd_chapters` | org | Individual chapters with critic status |
| `universe_approvals` | org | Investment universe approval workflow |
| `nav_timeseries` | org | Daily NAV + returns |
| `fund_risk_metrics` | org | Risk snapshots (CVaR, Sharpe, volatility, momentum: RSI, Bollinger, OBV) |
| `benchmark_nav` | global | Benchmark timeseries (no org_id) |
| `model_portfolios` | org | Model construction with fund_selection_schema |
| `portfolio_snapshots` | org | Daily portfolio state (weights, CVaR, regime) |
| `macro_regional_snapshots` | global | Weekly macro data (4 regions + global indicators) |
| `macro_reviews` | org | Macro committee review records |
| `instruments_screening_results` | org | 3-layer screening outcomes with config_hash |
| `allocation_blocks` | global | Strategic allocation buckets with benchmark_ticker |
| `macro_data` | global | Operational macro series (~65 FRED: regime detection, credit market_data, Case-Shiller metros) |
| `treasury_data` | global | US Treasury rates, debt, auctions, FX, interest expense (hypertable, 1-month chunks) |
| `ofr_hedge_fund_data` | global | OFR hedge fund leverage, AUM, strategy, repo volumes, stress (hypertable, 3-month chunks) |
| `wealth_content` | org | Generated outlooks, flash reports, spotlights |
| `strategy_drift_alerts` | org | DTW drift alerts with severity |
| `wealth_documents` | org | Document management |
| `wealth_document_versions` | org | Document version history |

---

## 7. Credit Frontend — Tools & Capabilities

### 7.1 Team Routes

| Route | Page | Key Actions |
|-------|------|-------------|
| `/dashboard` | Fund Dashboard | Tier 1-3 analytics, FRED Explorer (search series, view observations), TaskInbox, PipelineFunnel |
| `/funds` | Fund Selector | Grid of fund cards, auto-redirect if single fund |
| `/funds/{id}/pipeline` | Deal Pipeline | DataTable + Kanban view, stage filter (8 stages), create deal dialog, drag-drop stage transitions with ConsequenceDialog |
| `/funds/{id}/pipeline/{dealId}` | Deal Detail | 4 tabs (Overview, IC Memo, Documents, Compliance), stage timeline, MOIC/cashflow KPIs, approve/reject/convert decisions with rationale, SSE-streamed IC memo generation |
| `/funds/{id}/portfolio` | Portfolio | 4 tabs (Assets, Obligations, Alerts, Actions), add asset/obligation, fulfill/waive obligations with audit trail |
| `/funds/{id}/documents` | Document Management | Folder sidebar + DataTable, process pending (SSE progress), upload, reviews, dataroom, auditor view |
| `/funds/{id}/documents/upload` | Upload | Drag-drop, magic bytes validation, SAS URL two-step upload, SSE ingestion progress (OCR→classify→chunk→embed) |
| `/funds/{id}/documents/{docId}` | Document Detail | Classification provenance (layer, model, confidence), version history, submit for review |
| `/funds/{id}/documents/reviews` | Review Queue | Summary cards (pending/under review/approved/rejected), DataTable |
| `/funds/{id}/documents/reviews/{id}` | Review Detail | Assignment table, interactive checklist, approve/reject/request revision with rationale |
| `/funds/{id}/reporting` | Reporting | 3 tabs (NAV snapshots, Report Packs, Evidence), create NAV snapshot, generate/publish report packs |
| `/copilot` | Fund Copilot | 4 tabs (Chat, History, Activity, Document Search), SSE streaming answers, citation display |

### 7.2 Investor Routes

| Route | Page | Actions |
|-------|------|---------|
| `/documents` | Approved Documents | Download approved-for-distribution documents |
| `/report-packs` | Published Reports | PDFDownload with language selector (PT/EN) |
| `/statements` | Investor Statements | PDFDownload with language selector |

---

## 8. Wealth Frontend — Tools & Capabilities

### 8.1 Team Routes

| Route | Page | Key Actions |
|-------|------|-------------|
| `/dashboard` | Dashboard | RegimeBanner, 3 PortfolioCards (NAV, CVaR, Sharpe), drift alerts panel, quick actions, macro summary chips, live SSE risk data |
| `/funds` | Funds Universe | 4 status tabs (All/Approved/DD Pending/Watchlist), DataTable with ContextPanel (fund metrics sidebar) |
| `/funds/{id}` | Fund Detail | Metadata cards, risk metrics cards (CVaR, VaR, Sharpe, Sortino, Calmar), NAV chart |
| `/model-portfolios` | Model Portfolios | Card grid (3 profiles), inception NAV, status |
| `/model-portfolios/{id}` | Portfolio Detail | Backtest equity curve chart, annual metrics, stress test bar chart, fund selection schema |
| `/portfolios/{profile}` | Portfolio Workbench | Multi-region allocation navigator, DataTable with row expansion, before/after rebalance comparison, drift history export, StaleBanner |
| `/risk` | Risk Monitor | CVaR utilization bars (3 profiles), regime area chart, CVaR history, macro chips, drift alerts, RegimeBanner |
| `/allocation` | Allocation Editor | Profile selector, 3 tabs (Strategic/Tactical/Effective), BarChart with min/max bands, simulate CVaR impact, save with ConsequenceDialog + rationale |
| `/macro` | Macro Intelligence | Regional scores table, global indicators, regime hierarchy, committee reviews with generate/approve/reject |
| `/instruments` | Instruments | Search filter, DataTable (500+), create instrument dialog, detail panel |
| `/universe` | Investment Universe | 2 tabs (Approved/Pending), approve/reject with rationale |
| `/screener` | Screener | Funnel sidebar (layer pass counts), status tabs, VirtualList (500+ rows), ContextPanel with layer_results detail |
| `/analytics` | Analytics | Profile selector, correlation heatmap, regime-conditioned correlation, backtest + optimization triggers |
| `/exposure` | Exposure Monitor | Portfolio/Manager toggle, geographic + sector heatmap tables, freshness badges per fund |
| `/documents` | Documents | DataTable, domain filter, process pending batch, upload link |
| `/documents/upload` | Upload | Presigned URL pattern, drag-drop, magic bytes, SSE ingestion progress |
| `/dd-reports` | DD Reports | Fund selector → report list |
| `/dd-reports/{fundId}` | Fund DD Reports | Version history, status badges, generate new, regenerate, download PDF |
| `/dd-reports/{fundId}/{reportId}` | Report Detail | Chapter sidebar navigation, markdown rendering, approval bar (approve/reject with rationale), DOMPurify sanitization |
| `/content` | Content Production | Generate Outlook/Flash Report/Spotlight, spotlight fund picker, approve content, download PDF, poll for generating status |

### 8.2 Investor Routes

| Route | Page | Actions |
|-------|------|---------|
| `/fact-sheets` | Fact Sheets | Portfolio-grouped fact sheets, generate + download PDF |
| `/reports` | Published Reports | Approved outlooks, flash reports, spotlights with PDF download |
| `/inv-portfolios` | Model Portfolios | Read-only view with track record and stress test results |
| `/inv-documents` | Published Documents | Approved/published content download |
| `/inv-dd-reports` | DD Reports | Approved DD reports only, grouped by fund, PDF download |

### 8.3 Live Risk Store (SSE)

```
SSE Primary: GET /risk/stream
  ↓ (heartbeat 15s, timeout 45s)
Poll Fallback: GET /risk/summary?profiles={list}
  ↓ (30s interval when SSE fails)

State exposed:
  - cvarByProfile (Record<profile, CVaRStatus>)
  - regime (current + history)
  - driftAlerts (DTW + behavior change)
  - macroIndicators (VIX, yield curve, CPI, fed funds)
  - connectionQuality (live | degraded | offline)

Monotonic version gate prevents stale poll data from overwriting fresh SSE data.
```

---

## 9. End-to-End Pipeline Flows

### 9.1 Credit: Deal-to-IC-Memo Pipeline

```
1. Deal created in pipeline (stage: INTAKE)
   ↓
2. Documents uploaded → unified pipeline (OCR → classify → chunk → embed → index)
   ↓
3. Deal qualified (stage: QUALIFIED → IC_REVIEW)
   ↓
4. Deep Review V4 triggered (13-stage pipeline):
   RAG → structured analysis → macro → quant → concentration → policy →
   sponsor + KYC → evidence pack → critic → 14-chapter memo → persist
   ↓
5. IC Memo streamed via SSE (chapters render in-flight)
   ↓
6. Committee votes (approve/conditional/reject with rationale)
   ↓
7. Deal approved → Convert to Portfolio (deal_conversion engine):
   Creates portfolio Deal + ActiveInvestment + reclassifies vector chunks
   ↓
8. Portfolio monitoring (7 sub-engines):
   Metrics → drift → covenants → liquidity → risk → monitoring → briefs
```

### 9.2 Wealth: Fund Analysis Pipeline

```
1. Instruments ingested (Yahoo Finance → nav_timeseries)
   ↓
2. Risk calculation worker (CVaR, Sharpe, volatility → fund_risk_metrics)
   ↓
3. Screening (3-layer: eliminatory → mandate fit → quant scoring)
   ↓
4. Universe approval (pending → approved by IC, self-approval blocked)
   ↓
5. DD Report triggered per fund:
   Evidence pack → 8 chapters (sequential) → confidence scoring → persist
   Status: draft → generating → pending_approval → approved
   ↓
6. Portfolio construction:
   Strategic allocation → optimizer (CLARABEL/NSGA-II) → fund selection
   ↓
7. Daily evaluation (worker):
   CVaR breach check → regime detection → drift monitoring → snapshot persist
   ↓
8. Content generation:
   Fact Sheets (PDF per portfolio) | Outlook (quarterly) | Flash (event-driven)
   Status workflow: draft → pending_approval → approved → published
   ↓
9. Investor portal: approved DD reports, published content, fact sheets
```

### 9.3 Macro Intelligence Pipeline

```
1. Macro ingestion worker (global, ~45 FRED series)
   ↓
2. Regional normalization (US, EU, ASIA, EM):
   6 dimensions × 4 regions → composite scores (0-100)
   ↓
3. Global indicators: geopolitical_risk, energy_stress, commodity_stress, usd_strength
   ↓
4. Regime classification:
   Multi-signal (VIX + yield curve + CPI + Sahm) → CRISIS/INFLATION/RISK_OFF/RISK_ON
   Regional regime (ICE BofA OAS) → GDP-weighted global regime
   ↓
5. Stress severity scoring:
   6 dimensions → composite (0-100) → none/mild/moderate/severe
   ↓
6. Dashboard consumption:
   SSE stream → live regime banner + macro chips + drift alerts
   ↓
7. Weekly macro committee review:
   Generate report → approve/reject → persist to macro_reviews
```

---

## Appendix: External Integrations

**DB-First Rule:** All time-series external data is ingested by background workers into hypertables. Routes and vertical engines read from DB only. External APIs are never called in user-facing requests.

| Service | Protocol | Auth | Hypertable | Worker | Usage |
|---------|----------|------|-----------|--------|-------|
| OpenAI | REST | API key | — | — | GPT-4o/4.1 (analysis, memos, content), text-embedding-3-large (3072d) |
| Mistral | REST | API key | — | — | mistral-ocr-latest (PDF OCR) |
| Clerk | JWKS | JWT v2 | — | — | Authentication, organization context |
| FRED | REST | API key | `macro_data` | `macro_ingestion` | ~65 series: 4 regions + global + credit + 20 Case-Shiller metros |
| US Treasury | REST | None | `treasury_data` | `treasury_ingestion` | Rates, debt, auctions, FX, interest expense |
| OFR Hedge Fund | REST | None | `ofr_hedge_fund_data` | `ofr_ingestion` | Leverage, AUM, strategy, repo volumes, stress scenarios |
| SEC EDGAR | REST | None (8 req/s) | `sec_13f_holdings` | SEC seed/worker | CIK resolution, financials, 13F holdings, insider signals |
| Yahoo Finance | yfinance lib | None | `nav_timeseries`, `benchmark_nav` | `instrument_ingestion`, `benchmark_ingest` | NAV, prices, instrument metadata |
| Data Commons | REST | API key | — (on-demand) | — | Demographics, economic observations, geographic hierarchy |
| KYC Spider | REST | API key | — | — | PEP, sanctions, adverse media screening |
