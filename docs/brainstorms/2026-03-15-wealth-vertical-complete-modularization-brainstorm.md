---
title: "feat: Wealth Vertical Complete Modularization"
type: feature
status: brainstorm
date: 2026-03-15
---

# Wealth Vertical Complete Modularization

## What We're Building

A complete Wealth Management vertical engine that achieves parity with the Credit vertical's analytical depth, covering the full investment lifecycle: **Fund Analysis → Asset Universe → Model Portfolio Construction → Monitoring → Reporting (Fact-Sheets with Track-Record)**.

The WM vertical currently has a mature operational/quant layer (12 DB models, 7 workers, 14 quant services) but **zero AI-powered analysis intelligence** — the DD Report Engine, Quant Analyzer, and Prompts are empty scaffolds. This brainstorm defines what's needed to complete the product.

### The WM Investment Lifecycle

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      WEALTH MANAGEMENT LIFECYCLE                          │
│                                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ Fund DD  │───▶│ Asset Universe│───▶│Model Portfolio│                  │
│  │ Report   │    │ (Approved)   │    │ Construction  │                  │
│  └──────────┘    │              │    └──────┬───────┘                  │
│       ▲          │ ┌──────────┐ │           │                           │
│       │          │ │Bond Ficha│ │           ▼                           │
│  Doc Ingestion   │ │ Técnica  │─┘    ┌──────────────┐                  │
│  (global pipeline)│ └──────────┘     │  Track-Record │                  │
│                  └──────────────┘    │  (BT+Live+    │                  │
│                                      │   Stress)     │                  │
│                    ┌─────────────────┴──┬────────────┬──────────┐       │
│                    ▼                    ▼            ▼          ▼       │
│             ┌────────────┐    ┌──────────────┐ ┌─────────┐ ┌────────┐ │
│             │ Monitoring │    │  Fact-Sheet   │ │Rebalance│ │Content │ │
│             │ (Drift,Risk│    │  (Model Port.)│ │ Events  │ │Produtn.│ │
│             │  Regime)   │    │  Exec + Full  │ │         │ │Outlook │ │
│             └────────────┘    └──────────────┘ └─────────┘ │Flash   │ │
│                                      ▲                      │Spotlght│ │
│                                      │                      │ClientRp│ │
│                               ┌──────┴───────┐             └────────┘ │
│                               │ Client Report │                        │
│                               │ (personalized)│                        │
│                               └──────────────┘                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### Governance Flow (3 Approval Points)

1. **Fund → Asset Universe**: DD Report triggers committee review → fund approved/rejected for the universe
2. **Strategic Allocation Approved**: Macro committee approves asset allocation weights per profile (already partially implemented via `MacroReview` model)
3. **Rebalance Approved**: Each rebalance event requires individual approval before execution

## Why This Approach

### Approach Chosen: Mirrored Architecture (Espelhada ao Credit)

Replicate the Credit vertical's package architecture in `vertical_engines/wealth/`, adapted to the WM domain. Each capability becomes an independent package.

**Why this over alternatives:**
- **Architectural parity** with Credit reduces cognitive load for maintainers
- Each package is independently testable and deployable
- Reuses `ai_engine/` (global unified pipeline, currently being refactored) and `quant_engine/` (already wealth-oriented)
- The Credit vertical proved this architecture works at scale (91 files, 13 packages, all production)

**Rejected alternatives:**
- *Incremental by Layer* — risk of inconsistency; user wants complete pipeline delivery
- *Domain-Driven Bounded Contexts* — diverges from Credit architecture, increases complexity

## Key Decisions

### 1. Asset Universe is Multi-Class

The Asset Universe contains **two asset types**:
- **Funds** (traditional + hedge funds) → full DD Report with expanded chapters + adversarial critic
- **Bonds** (public traded, primarily fixed income) → automated technical sheet (yield, duration, rating, spread, maturity, issuer data). No narrative DD Report.
- **No stock picking** for now — explicitly out of scope.

Assets are classified according to the allocation schema (`AllocationBlock` model already exists as a global table).

### 2. DD Reports Expanded Beyond 7 Chapters

Current `profiles/liquid_funds/profile.yaml` defines 7 chapters. Expanding to include:
- Fund Manager Assessment (track record, team stability, AUM growth)
- Fee Analysis (TER, performance fees, hidden costs, peer comparison)
- Liquidity Risk (redemption gates, lock-ups, side pockets, NAV frequency)
- Peer Comparison (quantitative peer group analysis)
- Adversarial Critic Loop (challenges conclusions before finalizing, same pattern as Credit)

Target: ~10-11 chapters with RAG evidence injection from ingested fund documents (prospectus, DDQ, fact-sheets).

### 3. Fact-Sheets in Two Formats (Model Portfolio scope)

Model Portfolio fact-sheets are **generic per model** (Conservative/Balanced/Growth) — they show the model's track-record and composition, not any individual client's position. Two PDF versions:
- **Executive Summary (1-2 pages)**: NAV chart vs benchmark, returns table (MTD/YTD/12M/SI), allocation pie, top holdings, key risk metrics (Vol, Sharpe, MaxDD, CVaR), manager commentary. For prospecting.
- **Institutional Complete (4-6 pages)**: Everything above + attribution analysis, regime overlay, stress scenarios (2008, COVID, rate hike), peer comparison, ESG score, rebalance history, regulatory disclaimer. For engaged clients.

**Distinction from Client Reports** (`content_production/client_report.py`): Client Reports are personalized per client — showing their actual allocation vs the model, their deposits/withdrawals, and client-specific metrics. Fact-sheets are the "product brochure"; client reports are the "account statement".

### 4. Track-Record = Backtest + Live + Stress

Model Portfolio track-record has three components:
- **Backtest (simulated)**: Walk-forward cross-validated backtest using historical NAV of constituent funds/bonds. Clearly marked as simulated in all outputs.
- **Live Forward**: Real track-record from portfolio inception date. NAV computed daily from constituent weights × constituent NAVs.
- **Stress Scenarios**: How the portfolio would have performed in historical crises (2008 GFC, 2020 COVID, 2022 Rate Hike cycle). Uses existing `quant_engine/backtest_service.py`.

All three appear on fact-sheets with clear delineation.

### 5. Document Ingestion via Global Pipeline

Fund documents (prospectus, DDQ, fact-sheets, regulatory filings) are ingested through the **global unified pipeline** being built in the Pipeline LLM-Deterministic Alignment refactor (Phase 2 of that plan). The pipeline is vertical-agnostic by design — WM just needs:
- Document type classification rules for WM document types (fund prospectus, DDQ, fund fact-sheet, etc.)
- Extraction templates for WM-specific entities (fund manager, AUM, fees, strategy description, etc.)
- RAG corpus segmented by fund for DD Report evidence injection

**Data sources for current development:** Public APIs only (FRED for macro, public NAV feeds, free bond data). The DevOps roadmap (Phase 2, ID:135) lists Bloomberg/Morningstar/Macrobond as future commercial data subscriptions — these are **not available now**. The only planned commercial API is **Lipper (LSEG)** for fund ratings, but this is also future. The engine must be architected to work with public data first, with commercial feeds as drop-in enrichments later.

### 6. Delivery: Complete Pipeline

The full lifecycle (DD → Universe → Model Portfolio → Monitoring → Fact-Sheet) is delivered as a cohesive product. Phased implementation is acceptable but the goal is a complete system, not partial capabilities.

## Proposed Package Structure

```
backend/vertical_engines/wealth/
├── __init__.py
├── fund_analyzer.py          # EXISTING — BaseAnalyzer impl, needs rewiring
├── macro_committee_engine.py  # EXISTING — production, keep as-is
│
├── dd_report/                 # NEW — Fund Due Diligence Report Engine
│   ├── __init__.py
│   ├── dd_report_engine.py    # Orchestrator: chapter generation, critic loop
│   ├── chapter_engine.py      # Per-chapter LLM generation with RAG + quant injection
│   ├── evidence_pack.py       # Evidence gathering from ingested fund documents
│   ├── critic_engine.py       # Adversarial critic (reuse pattern from credit/critic/)
│   ├── quant_injection.py     # Bridge to quant_engine for quantitative data injection
│   └── models.py              # DDReport, DDChapter, DDEvidence dataclasses
│
├── bond_analysis/             # NEW — Bond Technical Sheet Generator
│   ├── __init__.py
│   ├── bond_sheet_engine.py   # Automated technical sheet from market data
│   └── models.py              # BondSheet dataclass
│
├── asset_universe/            # NEW — Approved Asset Universe Management
│   ├── __init__.py
│   ├── universe_service.py    # Add/remove/classify assets, approval workflow
│   ├── fund_approval.py       # DD Report → committee → approved/rejected
│   └── models.py              # UniverseAsset, ApprovalDecision dataclasses
│
├── model_portfolio/           # NEW — Model Portfolio Construction + Track-Record
│   ├── __init__.py
│   ├── portfolio_builder.py   # Construct portfolios from universe assets
│   ├── track_record.py        # NAV computation (backtest + live + synthetic)
│   ├── stress_scenarios.py    # Historical stress scenario simulation
│   └── models.py              # ModelPortfolio, TrackRecord, StressResult dataclasses
│
├── fact_sheet/                # NEW — PDF Fact-Sheet Generation
│   ├── __init__.py
│   ├── fact_sheet_engine.py   # Orchestrator: data gathering → PDF rendering
│   ├── executive_renderer.py  # 1-2 page executive summary PDF
│   ├── institutional_renderer.py  # 4-6 page institutional complete PDF
│   ├── chart_builder.py       # NAV charts, allocation pies, attribution charts
│   └── models.py              # FactSheetData dataclass
│
├── monitoring/                # NEW — Portfolio Monitoring (extends existing workers)
│   ├── __init__.py
│   ├── alert_engine.py        # Threshold alerts, regime change alerts
│   ├── drift_monitor.py       # Bridge to quant_engine/drift_service
│   └── risk_dashboard.py      # Aggregated risk view data preparation
│
├── content_production/        # NEW — Proprietary Content Generation (Roadmap Phase 2, ID:137)
│   ├── __init__.py
│   ├── investment_outlook.py  # Quarterly macro outlook (extends macro_committee_engine)
│   ├── flash_report.py        # Event-driven market flash reports
│   ├── manager_spotlight.py   # Deep-dive on single fund manager
│   ├── client_report.py       # Personalized per-client monthly/quarterly reports
│   └── models.py              # ContentPiece, OutlookData, FlashContext dataclasses
│
├── prompts/                   # NEW — Jinja2 prompt templates
│   ├── __init__.py
│   ├── dd_chapters/           # One template per DD chapter
│   ├── critic/                # Critic loop prompts
│   ├── fact_sheet/            # Commentary generation prompts
│   ├── content/               # Investment outlook, flash report, spotlight prompts
│   └── bond/                  # Bond analysis prompts
│
└── quant/                     # NEW — WM-specific quant bridge
    ├── __init__.py
    ├── quant_analyzer.py      # EXISTING scaffold → rewire to quant_engine
    ├── portfolio_metrics.py   # Portfolio-level quant aggregation
    └── peer_comparison.py     # Fund peer group quantitative analysis
```

### Domain Layer Additions Needed (`backend/app/domains/wealth/`)

The existing domain layer (models, routes, schemas, workers) needs extensions for:
- **Asset Universe routes** — CRUD for universe assets, approval workflow endpoints
- **DD Report routes** — trigger DD generation, retrieve reports, approval endpoints
- **Fact-Sheet routes** — trigger generation, download PDFs
- **Model Portfolio routes** — portfolio construction, track-record queries (extend existing `portfolios` routes)
- **Bond routes** — bond universe management, technical sheet generation

### Calibration Seeds Needed

- `calibration/seeds/liquid_funds/calibration.yaml` — CVaR limits, portfolio profile configs (currently hardcoded fallbacks)
- `calibration/seeds/liquid_funds/scoring.yaml` — fund scoring weights (currently hardcoded)
- `calibration/seeds/liquid_funds/dd_report.yaml` — DD chapter configs, critic thresholds, evidence requirements

### Profile Expansion Needed

- `profiles/liquid_funds/profile.yaml` — expand from 7 to ~11 chapters, add critic config, evidence requirements

## Gap Summary: What Exists vs What's Needed

| Component | Current State | Target State |
|---|---|---|
| `vertical_engines/wealth/` | 6 files (3 scaffold, 1 production, 1 empty) | ~45-50 files across 10 packages |
| DD Report Engine | Returns `status: "scaffold"` | Full LLM pipeline with RAG + critic |
| Quant Analyzer | Returns `status: "scaffold"` | Wired to quant_engine, portfolio metrics |
| Prompts | Empty `__init__.py` | Full Jinja2 templates for ~11 DD chapters + critic + fact-sheet commentary |
| Asset Universe | Not implemented | Full CRUD + classification + approval workflow |
| Bond Analysis | Not implemented | Automated technical sheets from market data |
| Model Portfolio Track-Record | Backtest exists in quant_engine | Backtest + live NAV + stress scenarios, all surfaced in fact-sheets |
| Fact-Sheet PDF | Not implemented | Two formats: executive (2pg) + institutional (6pg) |
| Monitoring Engine | Workers exist but no alert/dashboard engine | Alert engine + drift monitor + risk dashboard |
| Calibration Seeds | Only `macro_intelligence.yaml` | + calibration + scoring + dd_report configs |
| Content Production | Not implemented | Investment Outlook, Flash Reports, Manager Spotlight, Client Reports |
| Document Ingestion (WM types) | Not implemented | Classification rules + extraction templates for WM docs (via global pipeline) |

## Azure DevOps Roadmap Alignment

Cross-referenced with `Netz-International-Roadmap` project (6 Epics, 18 User Stories, ~160 Tasks).

### Strong Alignment (Analysis Engine covers these)

| Roadmap Item | Engine Package | Notes |
|---|---|---|
| Phase 1 > Manager DD Framework (ID:131) | `dd_report/` + `asset_universe/` | DDQ, scoring model, approval workflow |
| Phase 1 > Strategic Model Portfolios Design (ID:132) | `model_portfolio/` + `quant/` | Risk profiles, allocation ranges, rebalancing, benchmarks |
| Phase 2 > Data Infrastructure Setup (ID:135) | Global pipeline + `quant_engine/` | Public APIs only for now (FRED, public NAV). Commercial feeds (Lipper/LSEG) are future. |
| Phase 2 > Analytical Toolkit (ID:136) | `monitoring/` + `dd_report/` | Macro/asset class/manager templates, stress testing, dashboard |
| Phase 4 > Institutional Track Record (ID:143) | `model_portfolio/track_record.py` | Decision repo, performance attribution, historical analytics |
| Phase 4 > Professional Client Reporting (ID:144) | `fact_sheet/` | Monthly + quarterly report templates |

### Added to Scope (Proprietary Content Production)

Roadmap Phase 2 > Proprietary Content (ID:137) includes content types beyond fact-sheets:

| Content Type | Roadmap Tasks | Engine Package |
|---|---|---|
| Investment Outlook (quarterly) | ID:222-224 | `content_production/investment_outlook.py` — extends `macro_committee_engine.py` |
| Flash Reports (market events) | ID:225 | `content_production/flash_report.py` — triggered by regime changes or macro alerts |
| Manager Spotlight | ID:226 | `content_production/manager_spotlight.py` — deep-dive on single fund manager |
| Client Monthly Reports | ID:227 | `content_production/client_report.py` — personalized per-client portfolio summary |

### Out of Scope (Operational — not Analysis Engine)

| Roadmap Phase | Reason |
|---|---|
| Phase 0: Diagnostics & Foundations | Business process, not technology |
| Phase 3: Custody & Operations | Physical custody, trade execution, compliance (future add-on modules per CLAUDE.md) |
| Phase 5 > Capacity Expansion | Hiring, private markets expansion |
| Phase 5 > Market Positioning | Branding, whitepapers, events |

### Manager Relationship Structuring (Phase 4, ID:145)

CRM/database of managers, quarterly review calendar, fee negotiation — operational module, out of scope for analysis engine. However, the `dd_report/` engine produces the analytical artifacts that feed this process.

## Open Questions

*All resolved during brainstorm dialogue.*

## Resolved Questions

1. **Asset Universe composition?** → Funds + Bonds (no stocks). Funds get full DD, bonds get automated technical sheet.
2. **DD Report depth?** → Expanded beyond 7 chapters to ~10-11, including Fund Manager Assessment, Fee Analysis, Liquidity Risk, Peer Comparison, Adversarial Critic.
3. **Fact-Sheet format?** → Two versions: Executive (1-2pg) + Institutional (4-6pg).
4. **Track-record approach?** → Backtest (simulated, clearly marked) + Live Forward + Stress Scenarios (2008, COVID, Rate Hike).
5. **Document ingestion?** → Global unified pipeline (Pipeline LLM-Deterministic Alignment refactor). WM adds classification rules + extraction templates.
6. **Governance model?** → 3 approval points: Fund → Universe, Strategic Allocation, Rebalance Events.
7. **Delivery strategy?** → Complete pipeline as cohesive product.
8. **Architecture approach?** → Mirrored to Credit vertical's package structure.
9. **Proprietary content production?** → Include all types from roadmap: Investment Outlook (quarterly, extends macro_committee_engine), Flash Reports (event-driven), Manager Spotlight, Client Monthly Reports.
