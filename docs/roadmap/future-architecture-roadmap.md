# Future Architecture Roadmap — Netz Analysis Engine

## Status

- **Type:** Strategic roadmap (non-binding)
- **Source:** Brainstorms + architectural direction from Andrei
- **Not validated against runtime**
- **Last updated:** 2026-03-17

---

## Purpose

Capture **future system directions** without contaminating:

- current system map (`docs/audit/`)
- correction plans (`docs/plans/backend-correction-plan-v1.md`)
- validated architecture

---

## Critical Separation (MANDATORY)

| Layer | Description | Location |
|-------|-------------|----------|
| Current System | What exists in code | `docs/audit/` system maps |
| Correction Plan | What is being fixed | `docs/plans/backend-correction-plan-v1.md` |
| Future Roadmap | What may exist later | **This document** |

Future components must:
- NEVER appear in system maps as "existing"
- ALWAYS be explicitly marked as **FUTURE**

---

# 1. Infrastructure Rebuild (Post-Legacy AI Engine)

### Problem

The current backend inherits patterns from a **legacy AI Engine** (Private Credit OS), resulting in:

- Azure Blob direct usage (should be ADLS via StorageClient)
- Inconsistent ingestion paths
- Missing bronze/silver/gold hierarchy in some flows
- Duplicated pipeline logic

### Target Direction

- Full migration to **StorageClient + ADLS Gen2**
- Bronze / silver / gold hierarchy enforced everywhere
- Azure Search as **derived index only** (rebuildable from silver Parquet)
- Elimination of ALL direct Blob SDK usage
- `search_rebuild.py` as the canonical rebuild path

### Key Principle

> **ADLS = source of truth**
> **Search = derived**
> **Everything else = stateless compute**

### References

- Pipeline Alignment Refactor: [`docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md`](../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md)
- Extraction/Ingestion Cleanup: [`docs/plans/2026-03-15-refactor-ai-engine-extraction-ingestion-cleanup-plan.md`](../plans/2026-03-15-refactor-ai-engine-extraction-ingestion-cleanup-plan.md)

---

# 2. Unified Analytical Stack

### Components

| Layer | Role |
|-------|------|
| ADLS Gen2 | Persistent data (bronze/silver/gold) |
| DuckDB | Query layer — analytics directly on Parquet |
| `quant_engine/` | Quantitative analytics (CVaR, regime, optimizer) |
| `ai_engine/` | Reasoning (classification, extraction, embedding) |

### Goal

Eliminate:
- Duplicated data paths (PostgreSQL vs ADLS vs in-memory)
- In-memory-only analytics that can't be reproduced
- Non-reproducible results (all inputs must be traceable to ADLS artifacts)

### Future: DuckDB Query Layer

- DuckDB reads directly from silver/gold Parquet in ADLS
- Replaces ad-hoc pandas aggregations
- Enables cross-fund correlation, backtesting, time-series analytics
- Path: `gold/_global/` for cross-tenant aggregates, `gold/{org_id}/{vertical}/` for tenant-specific

---

# 3. Wealth Vertical — Full Institutional Stack

### Current State

- `quant_engine/` exists (CVaR, regime, optimizer, scoring, drift, rebalance)
- `vertical_engines/wealth/` modularized (fund_analyzer, dd_report_engine, macro_committee_engine, quant_analyzer)
- Screener suite complete (6 engines, polymorphic instruments)
- Senior analyst engines in progress (attribution, drift, correlation, liquidity)

### Missing Layers (FUTURE)

- **DD Report Engine v2:** LLM + RAG + critic loop (current is template-based)
- **Asset Universe governance:** Approval workflows for instrument inclusion/exclusion
- **Fact-sheet generation:** Automated fund fact sheets from gold-layer data
- **Content production pipeline:** Investor letters, quarterly reports, commentary

### References

- Wealth Modularization: [`docs/plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md`](../plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md)
- Screener Suite: [`docs/plans/2026-03-16-feat-wealth-instrument-screener-suite-plan.md`](../plans/2026-03-16-feat-wealth-instrument-screener-suite-plan.md)
- Senior Analyst: [`docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md`](../plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md)

---

# 4. Instrument-Centric Architecture

### Shift

| From | To |
|------|----|
| Fund-only model | Polymorphic instrument model |
| `funds` table | `instruments_universe` (JSONB-based) |
| Single asset class | Multi-asset (equity, FI, alternatives, derivatives) |

### Core Component

- `instruments_universe` table with JSONB `attributes` column
- Type discriminator for asset-class-specific behavior
- Shared screening/filtering/comparison across all instrument types

### Impact

- Enables universal screening (not just funds)
- Enables multi-asset portfolios
- Simplifies portfolio construction (instruments are fungible)
- Unblocks watchlist, alerts, and cross-asset analytics

### Reference

- Screener Suite: [`docs/brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md`](../brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md)

---

# 5. Deterministic Pipeline + LLM Hybrid

### Direction

- LLM only where genuinely necessary (~10% of documents)
- Deterministic everywhere else (~90%)

### Architecture (Partially Complete)

| Layer | Method | Coverage | Status |
|-------|--------|----------|--------|
| 1 | Filename + keyword rules | ~60% | DONE |
| 2 | TF-IDF + cosine similarity | ~30% | DONE |
| 3 | LLM fallback | ~10% | DONE |
| Cross-encoder reranker | Local model (replaced Cohere) | IC evidence | DONE |
| Validation gates | Between each pipeline stage | All stages | DONE |

### Remaining (FUTURE)

- Confidence calibration (threshold tuning per document type)
- Feedback loop: user corrections feed back to rules layer
- A/B evaluation framework for classifier improvements

### Reference

- Pipeline Alignment: [`docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md`](../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md)

---

# 6. Senior Analyst Layer (Diagnostics)

### Gap

| Current | Missing |
|---------|---------|
| Explains **WHAT** (metrics, scores) | Explains **WHY** (attribution, causality) |

### New Engines

| Engine | Purpose | Dependency |
|--------|---------|------------|
| Attribution | Performance decomposition by factor | Benchmark ingestion |
| Strategy Drift Detection | Detect style drift from stated mandate | Historical holdings |
| Correlation Regime Monitor | Cross-asset regime shifts | `quant_engine/regime_service` |
| Liquidity Stress Analysis | Redemption capacity under stress | NAV + flow data |

### Role

Support **IC-level decisions**, not just data processing. The system should help analysts understand causality, not just present numbers.

### Reference

- Senior Analyst Engines: [`docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md`](../plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md)

---

# 7. Macro Intelligence Layer

### Gap

- No top-down allocation logic
- No systematic macro regime integration into portfolio decisions

### Target

- FRED data ingestion (daily) into `macro_data` + ADLS gold layer
- Regime detection (expansion/contraction/crisis) via `regime_service`
- Committee-driven allocation proposals (not automatic execution)
- Macro overlay on fund-level analytics

### Governance

- **Committee-driven** (not automatic)
- System generates **proposals**, humans approve execution
- All proposals logged with rationale for audit trail

### Reference

- Macro Intelligence Suite: [`docs/plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md`](../plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md)

---

# 8. Frontend Admin Control Plane

### Role

- System configuration (verticals, tenants, feature flags)
- Tenant management (onboarding, RLS verification)
- Prompt control (view/edit Jinja2 templates, IP protection)
- Pipeline monitoring (ingestion status, error rates)

### Key Principle

> **Admin = control plane**
> **Not product UI**

Admin frontend is for Netz operators, not end-users. Different design language, different auth (super-admin only).

### Reference

- Admin Frontend: [`docs/plans/2026-03-17-feat-admin-frontend-plan.md`](../plans/2026-03-17-feat-admin-frontend-plan.md)

---

# 9. Credit Vertical Structural Alignment

### Goal

- Unify architecture via modular packages (same pattern as wealth)
- Enforce EDGAR pattern (`edgartools` integration)
- 12 modular packages (Wave 1 complete)
- Deep review modularization (Wave 2)

### Current State

Wave 1 (12 packages) is DONE. Wave 2 (deep review) is planned.

### Future

- Wave 3: Cross-vertical patterns (shared scoring, shared retrieval governance)
- IC memo generation v2 (multi-chapter with evidence packs)

### References

- Credit Modular Alignment Wave 1: [`docs/plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md`](../plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md)
- Credit Deep Review Wave 2: [`docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md`](../plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md)
- EDGAR Upgrade: [`docs/plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md`](../plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md)

---

# 10. Legacy Cleanup Inventory

Items that exist in code but should be replaced or removed:

| Legacy Pattern | Target | Priority |
|----------------|--------|----------|
| Direct Azure Blob SDK calls | StorageClient abstraction | HIGH |
| Cohere API references (if any remain) | Local cross-encoder reranker | MEDIUM |
| `cash_management/` references | Remove (out of scope) | LOW |
| `compliance/` references | Remove (out of scope) | LOW |
| `signatures/` references | Remove (out of scope) | LOW |
| `counterparties/` references | Remove (out of scope) | LOW |
| Inline f-string ADLS paths | `storage_routing.py` functions | HIGH |
| `profiles/` YAML direct reads | `ConfigService.get()` | MEDIUM |

---

# Summary

This roadmap defines:
- **Infrastructure evolution** (ADLS, DuckDB, StorageClient)
- **Analytical expansion** (senior analyst, macro intelligence, content production)
- **Architectural convergence** (instrument-centric, cross-vertical patterns)

> **This is NOT a commitment.**
> **It is a directional map** for decisions that haven't been scheduled yet.
> When an item moves to execution, it gets a brainstorm + plan in `docs/plans/` and a feature branch.
