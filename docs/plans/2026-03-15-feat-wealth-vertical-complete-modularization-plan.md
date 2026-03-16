---
title: "feat: Wealth Vertical Complete Modularization"
type: feat
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-wealth-vertical-complete-modularization-brainstorm.md
---

# feat: Wealth Vertical Complete Modularization

## Enhancement Summary

**Deepened on:** 2026-03-15 (round 1), 2026-03-16 (round 2 — 12 parallel agents)
**Round 2 agents:** Architecture Strategist, Performance Oracle, Security Sentinel, Data Integrity Guardian, Code Simplicity Reviewer, Deployment Verification Agent, Credit Pattern Explorer, Learnings Researcher, Best Practices (ReportLab PDF, Async DAG, Brinson-Fachler Attribution, Fund Scoring & Portfolio Construction)

### Round 1 Fixes (2026-03-15)

1. **Migration numbering collision** — renamed from `0006` to `0007` to `0008` (see fix #25). (Data Integrity)
2. **DDChapter missing `organization_id`** — added direct column + RLS policy for independent tenant isolation. (Architecture + Security)
3. **Chapters reduced from 11 to 8** — removed ESG, Peer Comparison, Liquidity Risk (folded into Risk Framework). (Simplicity)
4. **Parallel chapter generation** — DAG pattern: chapters 1-7 in parallel, chapter 8 sequential. (Performance)
5. **Critic extracted as sibling package** — `wealth/critic/` mirrors `credit/critic/`. (Pattern Recognition)
6. **UniverseApproval: separate nullable FKs** — ~~`fund_id FK` + `bond_id FK` + CHECK~~ → simplified in fix #30. (Data Integrity)
7. **Partial unique indexes on `is_current`** — prevents multiple "current" records. (Data Integrity)
8. **Security prerequisites** — (a) PromptRegistry SandboxedEnvironment fix, (b) 5 wealth routes → get_db_with_rls. (Security — CRITICAL)
9. **SSE tenant scoping** — `wealth:dd:{org_id}:{report_id}`, verify ownership before subscription. (Security)
10. **Self-approval prevention** — enforce `decided_by != created_by` on governance endpoints. (Security)
11. **Phases compressed from 7 to 5** — merged DD Report phases, collapsed content+monitoring into Polish. (Simplicity)
12. **Bond analysis deferred** — ~~Bond model kept in migration~~ → removed entirely in fix #30. (Simplicity)
13. **Content production dissolved** — 3 standalone files, not a package. (Simplicity)
14. **Feature flags for phased rollout** — ~~5 flags~~ → consolidated to 3 in fix #36. (Deployment)
15. **Brinson-Fachler with Carino linking** — correct formulas. Deferred to when benchmark data available. (Best Practices)
16. **Incremental live NAV** — ~~incremental + drift sentinel~~ → simplified in fix #35. (Performance)
17. **Per-chapter token budgets** — ANALYTICAL: 4000, DESCRIPTIVE: 2500, 30s timeout. (Performance)
18. **Survivorship bias prevention** — `include_inactive` parameter for bias-free backtests. (Best Practices)
19. **Chart rendering parallelism** — ThreadPoolExecutor(4) + chart caching between formats. (Performance)
20. **structlog migration** — scaffolds migrated from logging to structlog. (Architecture)
21. **Critic circuit breaker** — 3-minute wall-clock, abort remaining critic loops, escalate. (Performance)
22. **fund_selection_schema versioning** — ~~schema_version column~~ → removed in fix #34. (YAGNI)
23. **Prereq 0.2 is FIRST COMMIT** — RLS bypass is an active production vulnerability. (Security — CRITICAL)
24. **LiveNAV drift sentinel** — ~~incremental + spot-check~~ → simplified in fix #35. (Performance)

### Round 2 Fixes (2026-03-16) — 12-Agent Deep Review

**CRITICAL — New Vulnerabilities Discovered:**

25. **[CRITICAL] Existing wealth tables have ZERO RLS policies** — Migration 0002 created 9 tenant-scoped tables (`funds_universe`, `nav_timeseries`, `fund_risk_metrics`, `portfolio_snapshots`, `strategic_allocation`, `tactical_positions`, `rebalance_events`, `lipper_ratings`, `backtest_runs`) but NEVER enabled RLS or created policies. Even after Prereq 0.2 (route fix), the DB itself has no enforcement. **Migration 0008 must add RLS to all 9 existing wealth tables as its first operation.** (Data Integrity + Security — confirmed by code audit of `0002_wealth_domain.py`)
26. **[CRITICAL] Fund.isin unique constraint is cross-tenant** — `funds_universe.isin` has global `unique=True`. Two tenants cannot track the same fund by ISIN (e.g., both tracking BlackRock iShares). Migration 0008 must drop global unique and replace with `UNIQUE(organization_id, isin) WHERE isin IS NOT NULL`. (Data Integrity — confirmed at `0002_wealth_domain.py` line 36)
27. **[HIGH] SSE risk stream has no tenant scoping** — Existing `risk.py` SSE subscribes to `wealth:alerts:{profile}` with NO `organization_id`. Any authenticated user receives CVaR/regime alerts for ALL organizations. Fix: change channel to `wealth:alerts:{org_id}:{profile}`, verify actor's org before subscription. (Security — confirmed at `risk.py` lines 197-250)
28. **[HIGH] Worker trigger endpoints lack role authorization** — `workers.py` endpoints (`run-ingestion`, `run-risk-calc`, `run-portfolio-eval`, `run-macro-ingestion`) require only basic auth. Any user (including read-only INVESTOR/AUDITOR roles) can trigger computations. Fix: add `require_role(Role.ADMIN, Role.INVESTMENT_TEAM)`. (Security — confirmed)
29. **[HIGH] Pre-existing self-approval vulnerabilities** — `macro.py` approve_review and `portfolios.py` approve_rebalance don't check `created_by != approver`. Fix: add self-approval prevention to both (same pattern as new governance endpoints). (Security — confirmed)

**Architecture Fixes:**

30. **[HIGH] Remove Bond table from migration 0008 entirely** — Bond table is NOT zero cost: it adds RLS policies, CHECK constraints on UniverseApproval, and the polymorphic nullable FK pattern. Without Bond, `UniverseApproval.fund_id` becomes a simple non-nullable FK. `dd_report_id` becomes non-nullable. Eliminates `CHECK((fund_id IS NOT NULL AND bond_id IS NULL) OR ...)`. Add Bond in a future migration 0009 when bond data provider exists. Saves ~55 lines in migration, ~15 lines in model. (Simplicity — Code Simplicity Reviewer)
31. **[HIGH] Add import-linter contracts for wealth packages** — Current contracts only cover `vertical_engines.credit.*`. Add parallel contracts: `vertical_engines.wealth.*.models` must not import `vertical_engines.wealth.*.service`, helpers must not import from sibling `service.py`. Without this, import architecture is unenforced. (Architecture — Architecture Strategist)
32. **[HIGH] Move `CallOpenAiFn` Protocol to shared location** — If critic must have "no dd_report/ imports" (fix #5), but imports `CallOpenAiFn` from `dd_report/models.py`, that IS a dd_report import. Move Protocol to `wealth/shared_protocols.py`. (Architecture — Architecture Strategist)
33. **[HIGH] Specify sync Session creation for asyncio.to_thread** — Plan doesn't clarify how sync `Session` is obtained inside the thread. Must explicitly state: create a sync session factory inside the thread (not share AsyncSession across boundary). ORM objects must be converted to frozen dataclasses before crossing back to async context. (Architecture — Architecture Strategist)
34. **[MEDIUM] Remove schema_version from ModelPortfolio** — YAGNI. Schema v1 is the only version that will exist. When schema changes, add version column + migration then. Saves ~20 LOC of version dispatch logic. (Simplicity — Code Simplicity Reviewer)
35. **[MEDIUM] Simplify LiveNAV: full daily recompute, no drift sentinel** — At launch scale (<50 funds, <5 years), full recompute is milliseconds of math + 1 DB query. The incremental + sentinel adds ~50 LOC of branching logic for a performance problem that doesn't exist yet. When it becomes slow, add incremental. If periodic validation is desired, use a fixed weekly full recompute (Sunday) instead of random spot-checks. (Simplicity — Code Simplicity Reviewer)
36. **[MEDIUM] Consolidate feature flags from 5 to 3** — (1) `FEATURE_WEALTH_DD_REPORTS` covers DD Reports + Universe Approval (Phases 1-2, one logical feature), (2) `FEATURE_WEALTH_MODEL_PORTFOLIOS` covers Portfolios + Fact Sheets + Monitoring (Phases 3-4 + 5.3), (3) `FEATURE_WEALTH_CONTENT` covers Content Production (Phase 5.1-5.2). Reduces 64 potential states to 8. (Simplicity)
37. **[MEDIUM] Flatten asset_universe/ to single module** — Only 3 files (`universe_service.py`, `fund_approval.py`, `models.py`). Fund approval is a single function. Create `asset_universe.py` instead of a package. Promote to package only if it grows. Saves 3 files. (Simplicity)
38. **[MEDIUM] Dissolve monitoring/ to standalone files** — Only 2 files (`alert_engine.py`, `drift_monitor.py`). Same rationale as content production dissolution. (Simplicity)
39. **[MEDIUM] Defer manager_spotlight** — Reformats DD Report data that clients can already read. Build when a client asks. Saves 1 engine file + 1 prompt template (~150 LOC). (Simplicity — YAGNI)
40. **[MEDIUM] Remove attribution_service.py skeleton entirely** — Writing production-grade Brinson-Fachler formulas with no benchmark data to validate against is YAGNI. Institutional fact-sheet shows "Attribution: requires benchmark data feed" as a string literal. Build when benchmark data arrives. (Simplicity — Code Simplicity Reviewer)
41. **[MEDIUM] Remove peer_comparison_service.py** — Peer comparison requires populated universe with multiple funds per block. At launch, universe is small. DD Report Peer Comparison chapter was already deferred for same reason. (Simplicity — YAGNI)
42. **[MEDIUM] Merge backtest/stress trigger endpoints into construct** — `POST /model-portfolios/{id}/backtest` and `POST /model-portfolios/{id}/stress` fold into `POST /model-portfolios/{id}/construct`. Construction auto-triggers backtest and stress. Separate trigger endpoints imply a UI workflow that doesn't exist. Saves 2 endpoints. (Simplicity)

**Performance Optimizations:**

43. **[P1] Vectorize returns matrix construction** — Replace O(T×N) dict-loop in `backtest_service.py` (lines 198-201) with pandas pivot. For 200 funds × 5 years = 252K dict lookups → vectorized C. 10-50x faster. (Performance Oracle — confirmed in codebase)
44. **[P1] Add global LLM concurrency semaphore** — Per-report Semaphore(5) is good, but 10 concurrent reports = 50 simultaneous LLM calls. Add a global `asyncio.Semaphore(15-20)` (lazily created) shared across all DD Report generations to prevent OpenAI rate limit errors. (Performance Oracle)
45. **[P1] Per-chapter critic time budgeting** — Current: 3-minute total wall-clock. Problem: critic flags 4 chapters × 3 iterations × 20s = 240s for critic alone. Fix: after chapter generation, compute `remaining_budget / num_flagged_chapters` per-chapter budget. If a single critic iteration exceeds 30s, skip further iterations for that chapter. Reduces wasted LLM spend by 40-60% in circuit-breaker scenarios. (Performance Oracle)
46. **[P2] Parallelize evidence pack build** — RAG retrieval + quant metrics are independent. Use `asyncio.gather(asyncio.to_thread(fetch_documents), asyncio.to_thread(fetch_quant))`. Saves 5-15s per DD Report. (Performance Oracle)
47. **[P2] Batch daily NAV worker** — Fetch ALL fund returns for yesterday in single query, ALL portfolio compositions in single query, compute all NAVs vectorized, batch-upsert. Reduces DB round-trips from O(P×B) to O(1). (Performance Oracle)
48. **[P2] Batch chapter persistence** — Persist all 8 chapters in single transaction: one UPDATE (flip is_current) + one `db.add_all()`. 16 round-trips → 2. (Performance Oracle)
49. **[P2] Partial index for peer comparison** — `CREATE INDEX ... ON funds_universe(block_id, is_active, approval_status, aum_usd) WHERE is_active = true AND approval_status = 'approved'`. Index size reduced ~60%, 2-5x faster peer lookups. Include in migration 0008 alongside approval_status column. (Performance Oracle)
50. **[P3] Include data hash in chart cache key** — Cache key: `{portfolio_id}:{chart_type}:{as_of_date}:{md5(data)[:8]}`. Prevents stale charts after intraday rebalances. (Performance Oracle)
51. **[P3] Cache returns matrix across backtest + stress** — Fetch widest window once (2007-present), slice per use case. Eliminates 1-2 redundant queries fetching 50+ MB. (Performance Oracle)

**Data Integrity Additions:**

52. **[MEDIUM] Add composite FK on dd_chapters** — Enforce `dd_chapters(dd_report_id, organization_id)` references `dd_reports(id, organization_id)` via composite FK. Prevents cross-tenant FK references in privileged transactions. Requires composite unique index on `dd_reports(id, organization_id)`. (Data Integrity Guardian)
53. **[MEDIUM] Add partial unique index for bond approvals** — `UNIQUE(organization_id, bond_id) WHERE is_current = true AND bond_id IS NOT NULL`. Even though bonds are deferred, the migration should be future-proof. NOTE: if fix #30 is applied (remove Bond table), this is deferred to migration 0009. (Data Integrity Guardian)
54. **[MEDIUM] Add schema_version to dd_reports** — `schema_version: int, server_default=1` on `dd_reports` (not on individual chapters). Governs structure of config_snapshot, evidence_refs, quant_data JSONB fields. (Data Integrity Guardian)
55. **[MEDIUM] Add nullable model_portfolio_id FK to portfolio_snapshots** — Enables proper referential integrity between snapshots and model portfolios. Nullable for backward compat with existing snapshots. New snapshots always populate FK. (Data Integrity Guardian)
56. **[LOW] Document is_current transition ordering** — UPDATE old to false BEFORE INSERT new, within same transaction. Partial unique index rejects INSERT-before-UPDATE ordering. Explicitly document in service layer. (Data Integrity Guardian)

**Async/DAG Pattern Refinements:**

57. **Prefer asyncio.TaskGroup over gather for chapter parallelism** — TaskGroup (Python 3.11+) provides structured concurrency: if any task raises, siblings are cancelled. Per-task try/except inside TaskGroup allows partial results. Use `gather(return_exceptions=True)` only for mixed-criticality stages (like credit's EDGAR/KYC pattern). (Async DAG Research)
58. **Layered timeout architecture** — Layer 1: OpenAI SDK `timeout=60` (per-call HTTP). Layer 2: `asyncio.timeout(45)` per-chapter. Layer 3: `asyncio.timeout(180)` composite operation. Layer 4: critic `max_iterations=3`. (Async DAG Research)
59. **Chapter 8 minimum threshold** — Only generate Recommendation chapter if ≥5/7 prerequisite chapters succeeded. Prevents synthesizing from insufficient evidence. (Async DAG Research)
60. **Resume safety: version-tagged idempotency key** — Use `(report_id, chapter_tag, evidence_pack_hash)` as cache key. If evidence changes, chapters regenerate. (Async DAG Research — matches credit's `load_cached_chapter()` pattern)

**PDF Generation Improvements:**

61. **Migrate to NetzDocTemplate (BaseDocTemplate)** — Enables auto-generated Table of Contents with real page numbers, clickable bookmarks, distinct page templates (cover vs body). Uses `multiBuild()` (two-pass rendering). (ReportLab Research)
62. **"Page N of M" footer** — Standard institutional expectation. Use `NumberedCanvas` subclass with `canvasmaker` parameter. (ReportLab Research)
63. **KPI row builder for fact-sheets** — Grid of large-font value boxes (AUM, Sharpe, Vol, CVaR) with delta indicators. Standard institutional fact-sheet hero section pattern. (ReportLab Research)
64. **Add structural PDF tests (P0)** — Currently ZERO test coverage on 4 PDF generators. Add smoke tests: valid PDF header, correct page count, text content assertions via `pikepdf`. Add chart renderer unit tests. (ReportLab Research)
65. **Vector SVG option for fact-sheet charts** — svglib (already a dependency) can convert matplotlib SVG to ReportLab Drawing. Better zoom/print quality. Fallback to PNG for unsupported features (radar charts with polar projections). (ReportLab Research)

**Security Hardening:**

66. **Sanitize ALL LLM output before persistence** — Call `sanitize_llm_text()` from `ai_engine/governance/output_safety.py` on all DD chapter content, critic verdicts, and content production output. 6-stage pipeline: NFC normalization → control char strip → nh3 HTML sanitize → injection marker strip → entity encoding → JSONB null byte cleanup. (Learnings: `llm-output-sanitization-nh3-persist-boundary-PipelineStorage-20260315.md`)
67. **Register wealth prompt search path** — Call `prompt_registry.add_search_path(Path(__file__).parent / "prompts")` in `wealth/__init__.py`. Without this, PromptRegistry only searches `ai_engine/prompts/`. (Learnings: `prompt-registry-distributed-search-paths-PromptRelocation-20260315.md`)
68. **Rate limiting on LLM-intensive endpoints** — Per-organization max 5 DD Reports/hour. Use Redis-based rate limiting. (Security Sentinel)
69. **Feature flags as router-level dependency** — `Depends(require_feature("WEALTH_DD_REPORTS"))` applied at router level, not individual endpoints. Ensures consistent gating. (Security Sentinel)
70. **Content-Type + X-Content-Type-Options on downloads** — All PDF download endpoints must set `Content-Type: application/pdf`, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`. (Security Sentinel)
71. **Fix module-level asyncio.Lock in risk.py** — `_sse_redis_lock = asyncio.Lock()` at module scope violates CLAUDE.md rule. Move to lazy creation inside async function. (Security Sentinel)

**Deployment Preparation:**

72. **Migration 0008 lock analysis** — ALTER `funds_universe` ADD `approval_status` with `server_default='pending_dd'` + `nullable=True` avoids full table rewrite. Lock held for milliseconds. All CREATE TABLE and CREATE INDEX operations on empty new tables hold no locks on existing tables. (Deployment Verification Agent)
73. **Pre-deploy baseline SQL** — Record fund counts per org, verify alembic version = 0007, verify no approval_status column exists yet, verify no new tables exist. Save for post-deploy comparison. (Deployment Verification Agent)
74. **Post-deploy verification SQL** — 14 verification queries: alembic head, table existence, RLS enablement, policy subselect pattern, partial unique indexes, CHECK constraints, FK relationships, fund count comparison with baseline. (Deployment Verification Agent)
75. **Rollback procedure** — Feature flags are first response (disable flag → 503). Migration rollback: `alembic downgrade 0007`. Drop order: dd_chapters → universe_approvals → dd_reports → model_portfolios → ALTER funds_universe. **Do NOT revert Prereq 0.2** (restores active vulnerability). (Deployment Verification Agent)
76. **24-hour monitoring plan** — Watch HTTP 500 rate on `/api/wealth/*`, RLS errors, DD Report wall-clock > 3min, advisory lock contention, Redis pub/sub backlog. Hourly: check orphaned dd_chapters (org_id mismatch), is_current uniqueness, approval_status validity. (Deployment Verification Agent)

### Simplification Decisions (Updated)

| Original | Changed To | Reason |
|---|---|---|
| 11 DD chapters | 8 chapters | ESG (no data), Peer Comparison (empty universe), Liquidity Risk (folded into Risk Framework) |
| 7 phases | 5 phases | Merge DD Report phases, collapse content+monitoring into Polish |
| `bond_analysis/` package | Deferred | No bond data provider, vertical is `liquid_funds` |
| `Bond` table in migration 0008 | **Removed entirely** (fix #30) | Not zero cost: adds RLS, CHECK constraints, polymorphic FK pattern. Simplifies UniverseApproval to non-nullable fund_id. Add in migration 0009 when bond data arrives. |
| `content_production/` package (6 files) | 3 standalone files → **2 standalone files** (fix #39) | Manager Spotlight deferred — reformats DD Report data |
| `quant/` package (3 files) | Single `quant_analyzer.py` + functions in `quant_engine/` | Thin bridge doesn't justify a package |
| `attribution_service.py` skeleton | **Removed entirely** (fix #40) | YAGNI — no benchmark data to validate. Show placeholder text in fact-sheet. |
| `peer_comparison_service.py` | **Removed entirely** (fix #41) | YAGNI — universe too small for meaningful comparison |
| `client_report.py` scaffold | Removed | YAGNI — requires client data models that don't exist |
| `asset_universe/` package (3 files) | **Single module** `asset_universe.py` (fix #37) | Only 3 files, fund_approval is a single function |
| `monitoring/` package (2 files) | **2 standalone files** (fix #38) | Same rationale as content production dissolution |
| 5 feature flags | **3 feature flags** (fix #36) | DD_REPORTS+UNIVERSE, MODEL_PORTFOLIOS+FACT_SHEETS+MONITORING, CONTENT |
| `schema_version` on ModelPortfolio | **Removed** (fix #34) | YAGNI — schema v1 is only version. Add when schema changes. |
| Incremental NAV + drift sentinel | **Full daily recompute** (fix #35) | At launch scale, full recompute is fast. Add incremental when needed. |
| Separate backtest/stress endpoints | **Merged into construct** (fix #42) | Construction auto-triggers backtest + stress |
| `manager_spotlight.py` | **Deferred** (fix #39) | Low value, reformats DD Report data |

## Overview

Build the complete Wealth Management analytical intelligence layer — covering the full investment lifecycle from Fund DD Reports through Asset Universe management, Model Portfolio construction with track-record, monitoring, fact-sheet generation, and proprietary content production.

The WM vertical has a mature operational/quant layer (12 DB models, 7 workers, 14 quant services) but **zero AI-powered analysis intelligence**. The DD Report Engine, Quant Analyzer, and Prompts are empty scaffolds. This plan transforms those scaffolds into a production system mirroring the Credit vertical's architecture (91 files, 13 packages).

**Key architectural decisions (see brainstorm):**
- Mirrored architecture to Credit vertical — each capability is an independent package
- Asset Universe is multi-class: Funds (full DD Report) + Bonds (deferred until data provider exists)
- DD Reports with 8 chapters + RAG + adversarial critic (reduced from 11 per simplicity review)
- Track-record = backtest + live forward + stress scenarios
- Fact-sheets in 2 formats: executive (2pg) + institutional (6pg)
- Content production: Investment Outlook, Flash Reports, Manager Spotlight
- 3 governance approval points
- Public APIs only for data (Lipper/LSEG future)
- Client Reports deferred (requires operational client data layer not yet built)

**Implementation note (2026-03-16):** Phases have sequential dependencies — Phase 2 depends on Phase 1 (UniverseApproval references DDReport), Phase 3 depends on Phase 2, etc. Execute phases sequentially. Within each phase, tasks with non-overlapping files can be parallelized (e.g., Task 1.1 + Task 1.2 in parallel, then Task 1.3+ sequentially). Do NOT parallelize across phases.

**Prerequisite:** Security prerequisites (0.1, 0.2, 0.3) must be completed before Phase 1. Prereq 0.2 (get_db → get_db_with_rls) is the absolute first commit.

## Problem Statement / Motivation

The Credit vertical is production-complete with deep analytical capabilities (IC memos, RAG retrieval, adversarial critic, knowledge graph, PDF generation). The Wealth vertical has operational infrastructure but cannot perform its core analytical function — evaluating funds, constructing model portfolios, and producing the fact-sheets that commercial teams need to demonstrate management quality to clients.

The addressable market for WM is potentially larger than Credit. Without analytical parity, the platform cannot serve wealth management clients.

## Proposed Solution

7 packages in `vertical_engines/wealth/`, new database models, domain layer extensions, calibration seeds, and profile expansion — delivered as a cohesive system across 5 implementation phases.

## Technical Approach

### Architecture

**4-layer architecture (proven pattern from Wealth Macro Intelligence Suite):**

```
Layer 4: Routes (async)           — API surface, triggers, downloads
    ↓ asyncio.to_thread()
Layer 3: vertical_engines/wealth/ — DD engine, portfolio builder, fact-sheet (sync)
    ↓ function calls
Layer 2: quant_engine/            — CVaR, scoring, drift, backtest, attribution (sync, pure)
    ↓ resolved at entry
Layer 1: ConfigService            — config from DB (async → passed as param to sync layers)
```

**Critical constraints (from CLAUDE.md + institutional learnings):**
- `BaseAnalyzer` methods accept sync `Session` — async callers use `asyncio.to_thread()`
- Config via `ConfigService.get()` only — never read YAML at runtime
- Prompts are Netz IP — `jinja2.SandboxedEnvironment`, never expose in API responses
- `@dataclass(frozen=True, slots=True)` for all result types crossing async/thread boundaries
- `lazy="raise"` on all ORM relationships, `expire_on_commit=False` always
- `structlog` everywhere (not stdlib logging)
- Never-raises contract on engines — return `status: 'NOT_ASSESSED'` on failure
- StorageClient for all file I/O (PDFs, reports)
- RLS subselect pattern `(SELECT current_setting(...))` on all new tables

### Database Model Changes (Migration 0008)

> **CRITICAL:** Migration `0006_macro_reviews` already exists AND migration `0007_governance_policy_seed` was added by the ai_engine cleanup plan (refactor/policy-loader-configservice). This migration MUST be `0008` with `down_revision = "0007"`. (Data Integrity Guardian finding — updated 2026-03-16)

```mermaid
erDiagram
    DDReport ||--o{ DDChapter : contains
    DDReport }o--|| Fund : analyzes
    DDReport }o--o| UniverseApproval : triggers
    Bond ||--o| UniverseApproval : triggers
    UniverseApproval }o--|| ModelPortfolio : feeds
    ModelPortfolio ||--o{ PortfolioSnapshot : tracked_by
    Fund }o--|| AllocationBlock : classified_by
    Bond }o--|| AllocationBlock : classified_by

    DDReport {
        uuid id PK
        uuid organization_id FK
        uuid fund_id FK
        int version
        string status "draft|generating|critic_review|pending_approval|approved|rejected"
        jsonb config_snapshot
        float confidence_score
        string decision_anchor "APPROVE|CONDITIONAL|REJECT"
        boolean is_current
        timestamp created_at
        uuid created_by
    }

    DDChapter {
        uuid id PK
        uuid organization_id FK "direct column for independent RLS"
        uuid dd_report_id FK
        string chapter_tag
        int chapter_order
        text content_md
        jsonb evidence_refs
        jsonb quant_data
        int critic_iterations
        string critic_status "pending|accepted|revised|escalated"
        timestamp generated_at
    }

    Bond {
        uuid id PK
        uuid organization_id FK
        uuid block_id FK
        string isin
        string ticker
        string issuer_name
        string credit_rating
        float coupon_rate
        date maturity_date
        float yield_to_maturity
        float duration
        float spread_bps
        float face_value
        string currency
        string bond_type "government|corporate|municipal|agency"
        boolean is_active
        jsonb technical_sheet
        timestamp sheet_generated_at
        timestamp created_at
    }

    UniverseApproval {
        uuid id PK
        uuid organization_id FK
        uuid fund_id FK "nullable - CHECK exactly one of fund_id/bond_id is non-null"
        uuid bond_id FK "nullable"
        uuid dd_report_id FK "nullable - required when fund_id is set"
        string decision "approved|rejected|watchlist|pending"
        text rationale
        uuid created_by FK "for self-approval prevention"
        uuid decided_by FK
        timestamp decided_at
        boolean is_current
    }

    ModelPortfolio {
        uuid id PK
        uuid organization_id FK
        string profile "conservative|moderate|growth"
        string display_name
        text description
        string benchmark_composite
        date inception_date
        date backtest_start_date
        float inception_nav "default 1000.0"
        string status "draft|backtesting|live|archived"
        jsonb fund_selection_schema
        int schema_version "default 1 — for forward-compatible schema evolution"
        timestamp created_at
        uuid created_by
    }
```

**Additions to existing models:**
- `Fund`: add `approval_status` enum (`pending_dd`, `dd_complete`, `approved`, `rejected`, `watchlist`)
- `PortfolioSnapshot`: define `fund_selection` JSONB schema: `[{fund_id, block_id, weight, score}]`

### Security Prerequisites (before Phase 1)

> **CRITICAL pre-existing vulnerabilities** discovered by Security Sentinel. Must be fixed before any new wealth code ships.

##### Prereq 0.1: Fix PromptRegistry SandboxedEnvironment

**File:** MODIFY `backend/ai_engine/prompts/registry.py` (line 57)

The existing `PromptRegistry` uses `jinja2.Environment` (unsandboxed). All plan references to `SandboxedEnvironment` are aspirational — the actual code doesn't enforce it. Replace `Environment` with `SandboxedEnvironment` from `jinja2.sandbox`. Add unit test asserting the Environment type.

##### Prereq 0.2: Migrate Wealth Routes to get_db_with_rls — FIRST COMMIT

> **CRITICAL — ACTIVE PRODUCTION VULNERABILITY.** This is not a "nice to have" prerequisite. Any authenticated user can currently read any organization's funds, portfolios, allocations, and risk data. This must be the **first commit** of the project, before any Phase 1 work begins.

**Files:** MODIFY `backend/app/domains/wealth/routes/funds.py`, `portfolios.py`, `allocation.py`, `risk.py`, `analytics.py`

All 5 files import `get_db` instead of `get_db_with_rls`, completely bypassing tenant isolation. Replace all with `get_db_with_rls`. Only `macro.py` is correct.

##### Prereq 0.3: Migrate Scaffolds from logging to structlog

**Files:** MODIFY `backend/vertical_engines/wealth/fund_analyzer.py`, `dd_report_engine.py`, `quant_analyzer.py`

Replace `import logging` / `logging.getLogger(__name__)` with `structlog.get_logger()` to match Credit vertical conventions.

### Implementation Phases

---

#### Phase 1: DD Report Engine (merged original Phases 1+2)

**Goal:** Database models + DD Report engine producing real chapters with evidence injection + adversarial critic + confidence scoring + API routes. Ships a complete, usable feature.

**Depends on:** Security Prerequisites above. Pipeline LLM-Deterministic Alignment refactor Phase 1 (hybrid classifier) for document classification. DD Reports can start with manual document upload path while unified pipeline completes.

**Feature flag:** `FEATURE_WEALTH_DD_REPORTS` (routes return 503 when disabled)

##### Task 1.1: Database Migration (0007_wealth_analytical_models)

**Files:**
- CREATE `backend/app/core/db/migrations/versions/0008_wealth_analytical_models.py` (down_revision = "0007")

**Schema:**
- `dd_reports` table (DDReport model above)
- `dd_chapters` table (DDChapter model above)
- `bonds` table (Bond model above)
- `universe_approvals` table (UniverseApproval model above)
- `model_portfolios` table (ModelPortfolio model above)
- ALTER `funds_universe`: add `approval_status` column with CHECK constraint
- All tenant tables: RLS with `(SELECT current_setting('app.current_organization_id')::uuid)` subselect
- `dd_chapters` has direct `organization_id` column + own RLS policy (not join-based)
- `bonds` and `model_portfolios` have compound unique constraints
- `bonds` has `UNIQUE(organization_id, isin) WHERE isin IS NOT NULL`
- `dd_reports` has `UNIQUE(organization_id, fund_id) WHERE is_current = true` (partial unique index)
- `dd_reports` has `UNIQUE(organization_id, fund_id, version)` (version uniqueness)
- `universe_approvals` has `UNIQUE(organization_id, fund_id) WHERE is_current = true AND fund_id IS NOT NULL`
- `universe_approvals` has `CHECK((fund_id IS NOT NULL AND bond_id IS NULL) OR (fund_id IS NULL AND bond_id IS NOT NULL))`
- `universe_approvals` has `CHECK(fund_id IS NULL OR dd_report_id IS NOT NULL)` (fund approvals require DD Report)
- CHECK constraints on `dd_reports.status` and `universe_approvals.decision` enum values
- `Fund.approval_status` uses `server_default='pending_dd'` (avoids ACCESS EXCLUSIVE lock)
- Fix pre-existing bug: `PortfolioSnapshot` unique constraint must include `organization_id`

**Acceptance criteria:**
- [ ] `make migrate` succeeds
- [ ] Downgrade restores original state (drop order: dd_chapters → universe_approvals → dd_reports → bonds → model_portfolios → ALTER funds_universe)
- [ ] RLS uses subselect pattern on ALL new tables including `dd_chapters`
- [ ] `lazy="raise"` on all new relationships
- [ ] Partial unique indexes prevent multiple `is_current=true` records
- [ ] `alembic heads` returns exactly one head (0008)

##### Task 1.2: Domain Models + Schemas

**Files:**
- CREATE `backend/app/domains/wealth/models/dd_report.py` — DDReport, DDChapter SQLAlchemy models
- CREATE `backend/app/domains/wealth/models/bond.py` — Bond SQLAlchemy model
- CREATE `backend/app/domains/wealth/models/universe_approval.py` — UniverseApproval model
- CREATE `backend/app/domains/wealth/models/model_portfolio.py` — ModelPortfolio model
- MODIFY `backend/app/domains/wealth/models/fund.py` — add `approval_status` column
- MODIFY `backend/app/domains/wealth/models/__init__.py` — export new models
- CREATE `backend/app/domains/wealth/schemas/dd_report.py` — Pydantic schemas
- CREATE `backend/app/domains/wealth/schemas/bond.py` — Pydantic schemas
- CREATE `backend/app/domains/wealth/schemas/universe.py` — Pydantic schemas
- CREATE `backend/app/domains/wealth/schemas/model_portfolio.py` — Pydantic schemas

**Acceptance criteria:**
- [ ] All models use `OrganizationScopedMixin` (except global tables)
- [ ] All relationships have `lazy="raise"`
- [ ] All schemas use `model_validate()` pattern
- [ ] `make typecheck` passes

##### Task 1.3: DD Report Engine — Chapter Generation

**Files:**
- DELETE `backend/vertical_engines/wealth/dd_report_engine.py` (scaffold → replaced by package)
- CREATE `backend/vertical_engines/wealth/dd_report/__init__.py`
- CREATE `backend/vertical_engines/wealth/dd_report/dd_report_engine.py` — orchestrator
- CREATE `backend/vertical_engines/wealth/dd_report/chapters.py` — per-chapter LLM generation (named `chapters.py` per credit convention, not `chapter_engine.py`)
- CREATE `backend/vertical_engines/wealth/dd_report/evidence_pack.py` — frozen evidence surface (frozen dataclass, not dict like credit — intentional improvement)
- CREATE `backend/vertical_engines/wealth/dd_report/quant_injection.py` — bridge to quant_engine
- CREATE `backend/vertical_engines/wealth/dd_report/confidence_scoring.py` — deterministic scoring (merged from original Phase 2)
- CREATE `backend/vertical_engines/wealth/dd_report/models.py` — frozen dataclasses + `CallOpenAiFn` Protocol (shared with critic)

**Pattern (from credit `deep_review.py` 9-stage flow):**
1. Gather evidence corpus (fund documents via RAG + quant metrics via quant_engine)
2. Build frozen evidence pack (fund identity, strategy, performance, risk, fees, manager profile)
3. Quant injection: CVaR, Sharpe, Sortino, drawdown, scoring — from `quant_engine` services
4. **Parallel chapter generation (DAG pattern from Credit's `asyncio.gather()` + `Semaphore`):**
   - Phase A: chapters 1-7 in parallel (bounded by `_LLM_CONCURRENCY` semaphore, default 5)
   - Phase B: chapter 8 (Recommendation) sequential — synthesizes others, decision anchor is binding
   - Wall-clock: ~60-75s (3 concurrent batches) + ~20s (recommendation) = ~80-95s
5. Resume safety: skip cached chapters on re-run (check `DDChapter.content_md IS NOT NULL`)
6. Persist chapters atomically with `is_current` flag pattern + partial unique index
7. Compute confidence score (deterministic, no LLM)

**DD Report chapters (8 — reduced from 11 per simplicity review):**
1. Executive Summary (ANALYTICAL)
2. Investment Strategy & Process (DESCRIPTIVE)
3. Fund Manager Assessment (ANALYTICAL) — NEW: track record, team stability, AUM growth
4. Performance Analysis (ANALYTICAL)
5. Risk Management Framework (ANALYTICAL) — includes liquidity risk section for liquid funds
6. Fee Analysis (DESCRIPTIVE) — NEW: TER, performance fees, hidden costs
7. Operational Due Diligence (DESCRIPTIVE)
8. Recommendation (ANALYTICAL) — synthesis, decision anchor is binding

**Deferred chapters (add when data/universe exists):**
- Peer Comparison — requires populated universe with multiple funds per block
- ESG & Sustainability — requires commercial data provider (MSCI/Sustainalytics)

**Per-chapter token budgets (in `dd_report.yaml` calibration):**
- ANALYTICAL chapters: `max_tokens=4000`
- DESCRIPTIVE chapters: `max_tokens=2500`
- Executive Summary: `max_tokens=3000`
- Per-chapter timeout: 30 seconds

**Acceptance criteria:**
- [ ] DDReportEngine.generate() produces 8 chapters with real LLM content
- [ ] Chapters 1-7 generated in parallel (Semaphore-bounded), ch8 sequential
- [ ] Evidence pack is frozen dataclass before chapter generation
- [ ] Quant data injected from quant_engine services
- [ ] Resume safety: re-running skips completed chapters
- [ ] Per-chapter `max_tokens` passed to OpenAI API
- [ ] Never-raises contract: returns `status: 'NOT_ASSESSED'` on failure
- [ ] Confidence scoring produces 0-100 deterministic score
- [ ] Golden test captures output for one sample fund

##### Task 1.4: DD Report Prompts

**Files:**
- CREATE `backend/vertical_engines/wealth/prompts/__init__.py` — prompt registry
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/executive_summary.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/performance_analysis.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/risk_framework.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2`
- CREATE `backend/vertical_engines/wealth/prompts/dd_chapters/recommendation.j2`

**Pattern:** `jinja2.SandboxedEnvironment` (verified via Prereq 0.1), loaded via `prompt_registry.render("wealth/dd_chapters/{chapter_tag}.j2")`. Each template receives the filtered evidence pack + quant data for that chapter.

**Acceptance criteria:**
- [ ] All 8 templates render without error with sample evidence pack
- [ ] `SandboxedEnvironment` verified (unit test asserting type)
- [ ] Templates registered in prompt registry

##### Task 1.5: Calibration + Profile Seeds

**Files:**
- MODIFY `profiles/liquid_funds/profile.yaml` — expand from 7 to 8 chapters, add critic config
- CREATE `calibration/seeds/liquid_funds/calibration.yaml` — CVaR limits, portfolio profiles (externalize hardcoded defaults from `cvar_service.py`). **Schema-free: example seed only, all fields optional, any key/value can be added via VerticalConfigOverride without migrations.**
- CREATE `calibration/seeds/liquid_funds/scoring.yaml` — fund scoring weights (externalize from `scoring_service.py`). **Schema-free: example seed only.**
- CREATE `calibration/seeds/liquid_funds/dd_report.yaml` — chapter configs, critic thresholds, evidence requirements, per-chapter token budgets. **Schema-free: example seed only.**
- CREATE migration to seed these into `vertical_config_defaults` table

**Acceptance criteria:**
- [ ] `ConfigService.get("liquid_funds", "dd_report", org_id)` returns valid config
- [ ] Hardcoded fallbacks in `cvar_service.py` and `scoring_service.py` match seed values exactly
- [ ] Profile YAML has 8 chapter definitions with evidence requirements

##### Task 1.6: Critic Engine (sibling package — mirrors Credit's `credit/critic/`)

**Files:**
- CREATE `backend/vertical_engines/wealth/critic/__init__.py`
- CREATE `backend/vertical_engines/wealth/critic/service.py` — orchestrator (never-raises contract)
- CREATE `backend/vertical_engines/wealth/critic/models.py` — `CriticVerdict` frozen dataclass
- CREATE `backend/vertical_engines/wealth/critic/parser.py` — structured response parsing
- CREATE `backend/vertical_engines/wealth/critic/prompt_builder.py` — critic packet compression
- CREATE `backend/vertical_engines/wealth/prompts/critic/critic_prompt.j2`
- CREATE `backend/vertical_engines/wealth/prompts/critic/macro_consistency.j2`

> **Pattern note:** Extracted as sibling package (not nested in `dd_report/`) to mirror Credit's `credit/critic/` exactly and enable reuse by content production. (Pattern Recognition finding)

**Pattern (from credit `critic/service.py`):**
- `critique_dd_report()` — never-raises contract, returns `CriticVerdict`
- `CriticVerdict` frozen dataclass: `fatal_flaws`, `material_gaps`, `optimism_bias`, `data_quality_flags`, `confidence_score`, `overall_assessment`, `rewrite_required`
- Max 3 critic iterations per chapter (configurable via `dd_report.yaml`)
- Taxonomy: ACCEPT (passes) | REVISE (specific feedback, chapter regenerated) | ESCALATE (human review)
- **Circuit breaker:** if total DD Report wall-clock exceeds 3 minutes, abort remaining critic loops, mark chapters `critic_status: 'escalated'`, persist report as-is for human review. Publish `report_escalated` SSE event.
- Deterministic macro-consistency checks merged into verdict after LLM response
- `build_critic_packet()` compresses evidence for critic consumption
- LLM client injected via `CallOpenAiFn` Protocol (from `dd_report/models.py`)

**Acceptance criteria:**
- [ ] Critic produces structured verdict for sample DD Report
- [ ] Max iterations enforced (default 3)
- [ ] Circuit breaker triggers at 3-minute wall-clock and escalates remaining chapters
- [ ] ESCALATE status flags report for human review
- [ ] Never-raises contract respected
- [ ] Reusable by content production (no `dd_report/` imports in critic)

##### Task 1.7: DD Report API Routes

**Files:**
- CREATE `backend/app/domains/wealth/routes/dd_reports.py`
- MODIFY `backend/app/domains/wealth/routes/__init__.py` — register router

**Endpoints:**
- `POST /api/wealth/funds/{fund_id}/dd-reports` — trigger DD Report generation (async via `asyncio.to_thread`)
- `GET /api/wealth/funds/{fund_id}/dd-reports` — list reports for fund (with version history)
- `GET /api/wealth/dd-reports/{report_id}` — get full report with chapters
- `POST /api/wealth/dd-reports/{report_id}/regenerate` — force re-run with critic feedback
- `GET /api/wealth/dd-reports/{report_id}/stream` — SSE progress (chapter-by-chapter via Redis pub/sub)

**SSE pattern:** Publish to `wealth:dd:{organization_id}:{report_id}` channel (tenant-scoped). Verify actor's `organization_id` matches report's `organization_id` BEFORE subscribing. Events: `chapter_started`, `chapter_completed`, `critic_started`, `critic_verdict`, `report_completed`, `report_failed`.

**Acceptance criteria:**
- [ ] All endpoints use `response_model=` and `model_validate()`
- [ ] All routes use `get_db_with_rls` (NOT `get_db`)
- [ ] Generation runs via `asyncio.to_thread()` with `expire_on_commit=False` on sync session
- [ ] SSE stream provides real-time progress with tenant-scoped channels
- [ ] SSE endpoint verifies report ownership before subscription
- [ ] RLS enforced on all queries
- [ ] `make check` passes

---

#### Phase 2: Asset Universe (fund-only, bonds deferred)

**Goal:** Fund approval workflow with governance controls. Bond analysis deferred until data provider exists.

**Feature flag:** `FEATURE_WEALTH_UNIVERSE`

> **Simplification:** `bond_analysis/` package deferred. The `Bond` model exists in the migration (zero cost) but no engine, auto-approval flow, or bond API routes are built. Model portfolios start as fund-only. (Simplicity review)

##### Task 2.1: Asset Universe Service

**Files:**
- CREATE `backend/vertical_engines/wealth/asset_universe/__init__.py`
- CREATE `backend/vertical_engines/wealth/asset_universe/universe_service.py`
- CREATE `backend/vertical_engines/wealth/asset_universe/fund_approval.py`
- CREATE `backend/vertical_engines/wealth/asset_universe/models.py`

**Behavior:**
- `UniverseService.add_fund(fund_id, dd_report_id)` — creates pending UniverseApproval
- `UniverseService.approve_fund(approval_id, decision, rationale, decided_by)` — approves/rejects, updates Fund.approval_status. **Enforces `decided_by != created_by`** (self-approval prevention per Security finding). Uses `SELECT FOR UPDATE` on fund row.
- `UniverseService.list_universe(filters)` — approved funds classified by AllocationBlock (bonds added when data provider exists)
- `UniverseService.deactivate_asset(asset_type, asset_id)` — removes from universe, triggers rebalance evaluation

**Acceptance criteria:**
- [x] Fund approval flow: DD Report → pending → approved/rejected
- [x] Self-approval prevention enforced (`decided_by != created_by`)
- [x] `SELECT FOR UPDATE` on fund row during approval (prevents concurrent state corruption)
- [x] Deactivation triggers rebalance evaluation event
- [x] Audit trail via UniverseApproval records with partial unique index on `is_current`

##### Task 2.2: Asset Universe API Routes

**Files:**
- CREATE `backend/app/domains/wealth/routes/universe.py`
- MODIFY `backend/app/domains/wealth/routes/__init__.py`

**Endpoints:**
- `GET /api/wealth/universe` — list all approved funds, filterable by block/geography/asset_class
- `POST /api/wealth/universe/funds/{fund_id}/approve` — approve fund for universe (requires IC role, self-approval blocked)
- `POST /api/wealth/universe/funds/{fund_id}/reject` — reject fund (requires IC role)
- `GET /api/wealth/universe/pending` — list pending approvals

**Acceptance criteria:**
- [x] All endpoints use `response_model=`, `model_validate()`, and `get_db_with_rls`
- [x] IC role required for approval/rejection
- [x] Self-approval prevention: 403 if `decided_by == created_by`

---

#### Phase 3: Model Portfolio + Track-Record

**Goal:** Portfolio construction from universe assets, track-record computation (backtest + live + stress).

**Feature flag:** `FEATURE_WEALTH_MODEL_PORTFOLIOS`

##### Task 3.1: Model Portfolio Package

**Files:**
- CREATE `backend/vertical_engines/wealth/model_portfolio/__init__.py`
- CREATE `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py`
- CREATE `backend/vertical_engines/wealth/model_portfolio/track_record.py`
- CREATE `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py`
- CREATE `backend/vertical_engines/wealth/model_portfolio/models.py`

**Portfolio construction — fund selection algorithm:**
- Strategic allocation defines weights per AllocationBlock
- Within each block, select top N funds by `manager_score` (configurable, default 3)
- Funds weighted proportionally to score within block allocation
- `portfolio_builder.construct(db, profile, universe_assets, strategic_allocation, config) -> PortfolioComposition`
- Returns frozen `PortfolioComposition` with per-fund weights that sum to 1.0

**Track-record computation:**
- `track_record.compute_backtest(db, composition, lookback_days, config) -> BacktestResult` — uses `quant_engine/backtest_service.py` walk-forward CV
- `track_record.compute_live_nav(db, portfolio_id, as_of) -> LiveNAV` — **incremental**: daily worker stores previous NAV and fetches only latest day's returns. Full recomputation on-demand with `?recompute=true`. Formula: `NAV_t = NAV_{t-1} * (1 + sum(w_i * r_i_t))`. **Drift sentinel:** daily worker also spot-checks incremental NAV against full recompute for a random day. If delta exceeds 0.1%, triggers automatic full recompute + structlog alert. Catches retroactive NAV corrections in UCITS funds.
- `track_record.compute_stress(db, composition, scenarios, config) -> StressResult` — replays through historical crises. **Optimization**: fetch full returns matrix once (widest window 2007-10 to present), slice in memory per scenario (avoids 3 redundant DB round-trips)
- Minimum NAV history: 252 trading days (1 year). Funds with less history excluded from backtest period prior to their inception. Backtest inception capped at youngest fund's start date.

**Stress scenarios (from brainstorm):**
- 2008 GFC: 2007-10-01 to 2009-03-31
- 2020 COVID: 2020-02-15 to 2020-04-30
- 2022 Rate Hike: 2022-01-01 to 2022-12-31

**Acceptance criteria:**
- [ ] Portfolio construction produces valid weights summing to 1.0
- [ ] Score-weighted fund selection within blocks
- [ ] Backtest uses walk-forward CV from quant_engine
- [ ] Live NAV computes correctly from constituent returns
- [ ] Stress scenarios replay through historical windows
- [ ] Minimum history enforced
- [ ] All result types are frozen dataclasses

##### Task 3.2: Quant Analyzer Rewiring (single file, not package)

**Files:**
- MODIFY `backend/vertical_engines/wealth/quant_analyzer.py` — rewire scaffold to real quant_engine calls
- CREATE `backend/quant_engine/portfolio_metrics_service.py` — portfolio-level aggregation (generic, in quant_engine)
- CREATE `backend/quant_engine/peer_comparison_service.py` — fund peer group analysis (generic, in quant_engine)

> **Simplification:** Keep `quant_analyzer.py` as a single file bridge. Move `portfolio_metrics` and `peer_comparison` to `quant_engine/` where they are domain-agnostic and reusable across verticals. (Simplicity review)

**Quant analyzer wiring:**
- `QuantAnalyzer.analyze_portfolio()` calls: `cvar_service.compute_cvar_from_returns()`, `scoring_service.compute_fund_score()`, `drift_service.compute_drift()`, `regime_service.detect_regime()`
- `portfolio_metrics_service.aggregate()` computes portfolio-level Sharpe, Sortino, max drawdown, IR from constituent data
- `peer_comparison_service.compare()` ranks fund against peers — **batch query**: single `WHERE fund_id IN (...)` with `BETWEEN` for AUM filter. Add composite index on `funds_universe(block_id, is_active, approval_status)` in migration.

**Acceptance criteria:**
- [ ] QuantAnalyzer returns real metrics from quant_engine (not scaffold stubs)
- [ ] Portfolio metrics aggregate correctly
- [ ] Peer comparison uses batch query (no N+1)
- [ ] All results are frozen dataclasses

##### Task 3.3: Attribution Service (deferred — builds skeleton only)

> **Deferred implementation:** Brinson-Fachler with Carino multi-period linking requires benchmark constituent data that does not exist (no Bloomberg/Morningstar). Build the service skeleton with correct formulas but gate behind benchmark data availability. Institutional fact-sheet shows "Attribution requires benchmark data feed" placeholder until then. (Simplicity + Best Practices)

**Files:**
- CREATE `backend/quant_engine/attribution_service.py`

**Brinson-Fachler model (when data available):**
- `compute_attribution(portfolio_weights, benchmark_weights, portfolio_returns, benchmark_returns) -> AttributionResult`
- Allocation effect: `sum((w_p_i - w_b_i) * (r_b_i - R_b))` (Fachler adjustment using relative benchmark)
- Selection effect: `sum(w_b_i * (r_p_i - r_b_i))`
- Interaction effect: `sum((w_p_i - w_b_i) * (r_p_i - r_b_i))`
- Multi-period linking: Carino (1999) smoothing factors for correct compounding
- Numerical stability: `numpy.float64`, threshold `abs(w_diff) < 1e-6` → zero effect
- Pure sync, config as parameter

**Acceptance criteria:**
- [ ] Single-period attribution effects sum to total excess return (within 1e-4 tolerance)
- [ ] Carino linking preserves additivity across periods
- [ ] Pure function, no I/O
- [ ] Gracefully returns empty result when benchmark data unavailable

##### Task 3.4: Rebalance Execution Flow

**Files:**
- MODIFY `backend/app/domains/wealth/routes/portfolios.py` — add execution endpoint
- MODIFY `backend/app/domains/wealth/workers/drift_check.py` — trigger execution after approval

**Behavior:** After rebalance approval:
1. Re-run optimizer with current strategic + tactical weights
2. Apply fund selection algorithm from universe
3. Create new `PortfolioSnapshot` with updated `fund_selection` and weights
4. Record `RebalanceEvent` transition to `executed` status
5. Publish SSE alert: `rebalance_executed`

**Endpoint:** `POST /api/wealth/portfolios/{profile}/rebalance/{event_id}/execute`

**Acceptance criteria:**
- [ ] Execution only possible after approval status
- [ ] New snapshot created with optimizer output
- [ ] RebalanceEvent status transitions: proposed → approved → executed
- [ ] SSE notification on execution

##### Task 3.5: Model Portfolio API Routes

**Files:**
- CREATE `backend/app/domains/wealth/routes/model_portfolios.py`
- MODIFY `backend/app/domains/wealth/routes/__init__.py`

**Endpoints:**
- `POST /api/wealth/model-portfolios` — create model portfolio (IC role)
- `GET /api/wealth/model-portfolios` — list model portfolios
- `GET /api/wealth/model-portfolios/{id}` — get portfolio with composition
- `POST /api/wealth/model-portfolios/{id}/construct` — run fund selection from universe
- `GET /api/wealth/model-portfolios/{id}/track-record` — backtest + live + stress data
- `POST /api/wealth/model-portfolios/{id}/backtest` — trigger backtest computation
- `POST /api/wealth/model-portfolios/{id}/stress` — trigger stress scenarios

**Acceptance criteria:**
- [ ] All endpoints use `response_model=` and `model_validate()`
- [ ] IC role required for creation and construction
- [ ] Track-record endpoint returns all three components with clear delineation

---

#### Phase 4: Fact-Sheet PDF Generation

**Goal:** Two PDF formats for model portfolios — executive summary and institutional complete.

**Feature flag:** `FEATURE_WEALTH_FACT_SHEETS`

##### Task 4.1: Fact-Sheet Engine Package

**Files:**
- CREATE `backend/vertical_engines/wealth/fact_sheet/__init__.py`
- CREATE `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` — orchestrator
- CREATE `backend/vertical_engines/wealth/fact_sheet/executive_renderer.py` — 1-2 page PDF
- CREATE `backend/vertical_engines/wealth/fact_sheet/institutional_renderer.py` — 4-6 page PDF
- CREATE `backend/vertical_engines/wealth/fact_sheet/chart_builder.py` — chart generation
- CREATE `backend/vertical_engines/wealth/fact_sheet/models.py` — FactSheetData dataclass

**PDF stack:** ReportLab (already used by credit PDFs via `ai_engine/pdf/pdf_base.py`). Reuse `pdf_base` building blocks: `create_netz_document()`, `build_netz_styles()`, `netz_header_footer()`, `build_institutional_table()`, `safe_text()`. Charts via matplotlib embedded as PNG at 150 DPI (300 DPI option for print).

**Chart rendering (Performance):** Render all charts in parallel using `ThreadPoolExecutor(max_workers=4)`. Cache shared charts between executive and institutional formats (NAV chart and regime overlay are identical). Use `constrained_layout=True` instead of `tight_layout()`. Use `rasterized=True` for dense time series (>1000 points).

**Executive Summary (1-2 pages):**
- Cover: portfolio name, profile, as-of date, Netz branding
- NAV chart vs composite benchmark (matplotlib line chart)
- Returns table: MTD, QTD, YTD, 1Y, 3Y, Since Inception (backtest marked with *)
- Allocation pie chart by AllocationBlock
- Top 10 holdings table
- Key risk metrics: Annualized Vol, Sharpe, MaxDD, CVaR 95%
- LLM-generated manager commentary (2-3 paragraphs)

**Institutional Complete (4-6 pages):**
- Everything from Executive plus:
- Attribution analysis table (Brinson decomposition by block)
- Regime overlay chart (current regime + historical)
- Stress scenario table (2008, COVID, 2022 drawdowns)
- Rebalance history timeline
- ESG placeholder section (populated when data available)
- Regulatory disclaimer footer

**Acceptance criteria:**
- [ ] Executive PDF renders correctly with all sections
- [ ] Institutional PDF renders correctly with all sections
- [ ] Backtest periods marked with asterisk (*) in returns table
- [ ] Charts render as high-quality embedded images
- [ ] Netz branding consistent with credit PDFs
- [ ] PDFs stored via StorageClient
- [ ] `make check` passes

##### Task 4.2: DD Report PDF Generation

**Files:**
- CREATE `backend/ai_engine/pdf/generate_dd_report_pdf.py`

**Pattern:** Same as `generate_deep_review_pdf.py` — loads DDReport + DDChapter from DB, renders markdown chapters via `memo_md_to_pdf`, uses `pdf_base` building blocks.

**Acceptance criteria:**
- [ ] DD Report PDF renders all 8 chapters
- [ ] Cover page with fund name, decision anchor badge, confidence score
- [ ] Netz institutional branding
- [ ] Stored via StorageClient

##### Task 4.3: Fact-Sheet Prompts

**Files:**
- CREATE `backend/vertical_engines/wealth/prompts/fact_sheet/manager_commentary.j2`
- CREATE `backend/vertical_engines/wealth/prompts/fact_sheet/outlook_snippet.j2`

**Acceptance criteria:**
- [ ] Commentary prompt receives portfolio metrics + regime context
- [ ] `SandboxedEnvironment` used

##### Task 4.4: Fact-Sheet API Routes + Worker

**Files:**
- CREATE `backend/app/domains/wealth/routes/fact_sheets.py`
- CREATE `backend/app/domains/wealth/workers/fact_sheet_gen.py`
- MODIFY `backend/app/domains/wealth/routes/__init__.py`

**Endpoints:**
- `POST /api/wealth/model-portfolios/{id}/fact-sheets` — trigger on-demand generation (exec or institutional)
- `GET /api/wealth/model-portfolios/{id}/fact-sheets` — list generated fact-sheets
- `GET /api/wealth/fact-sheets/{id}/download` — download PDF

**Worker:** Monthly scheduled generation for all active model portfolios. Uses PostgreSQL advisory lock to prevent concurrent runs.

**Acceptance criteria:**
- [ ] On-demand generation via API
- [ ] Scheduled monthly generation via worker
- [ ] PDF download endpoint serves correct content-type
- [ ] StorageClient for all PDF storage

---

#### Phase 5: Polish — Content Production + Monitoring + FundAnalyzer Rewiring

**Goal:** Proprietary content files (standalone, not package), monitoring hooks, FundAnalyzer rewiring. Cleanup phase.

**Feature flags:** `FEATURE_WEALTH_CONTENT`, `FEATURE_WEALTH_MONITORING`

##### Task 5.1: Content Production (standalone files, not package)

> **Simplification:** Dissolved `content_production/` package into standalone files. Each content type is independent with different triggers, cadences, and data sources. No `client_report.py` scaffold (YAGNI). (Simplicity review)

**Files:**
- CREATE `backend/vertical_engines/wealth/investment_outlook.py` — extends `macro_committee_engine.py` with LLM narrative
- CREATE `backend/vertical_engines/wealth/flash_report.py` — event-driven market flash reports
- CREATE `backend/vertical_engines/wealth/manager_spotlight.py` — deep-dive on single fund manager
- CREATE `backend/vertical_engines/wealth/prompts/content/investment_outlook.j2`
- CREATE `backend/vertical_engines/wealth/prompts/content/flash_report.j2`
- CREATE `backend/vertical_engines/wealth/prompts/content/manager_spotlight.j2`

**Investment Outlook (quarterly):** Extends `macro_committee_engine.py` structured data (WeeklyReportData) with LLM narrative. Sections: Global Macro Summary, Regional Outlook, Asset Class Views, Portfolio Positioning, Key Risks.

**Flash Report (event-driven):** Triggered manually or by regime change. 48h cooldown (reuse `check_emergency_cooldown`). **Must require human review before distribution** — download endpoint checks `status == 'approved'` before serving.

**Manager Spotlight:** Deep-dive using DD Report data + quant metrics + peer comparison.

**Content governance:** All content has `status` field (`draft` → `review` → `approved` → `published`). No auto-publish. IC approval required. Self-approval blocked.

##### Task 5.2: Content API Routes

**Files:**
- CREATE `backend/app/domains/wealth/routes/content.py`
- MODIFY `backend/app/domains/wealth/routes/__init__.py`

**Endpoints:**
- `POST /api/wealth/content/outlooks` — trigger Investment Outlook
- `POST /api/wealth/content/flash-reports` — trigger Flash Report
- `POST /api/wealth/content/spotlights` — trigger Manager Spotlight
- `GET /api/wealth/content` — list content with status
- `POST /api/wealth/content/{id}/approve` — approve (IC role, self-approval blocked)
- `GET /api/wealth/content/{id}/download` — download PDF (**checks `status >= approved` before serving**)

**Acceptance criteria:**
- [ ] All content types generate structured output + PDF
- [ ] Download endpoint returns 403 for draft/review content
- [ ] Approval workflow enforced
- [ ] Flash report cooldown enforced

##### Task 5.3: Monitoring Hooks

**Files:**
- CREATE `backend/vertical_engines/wealth/monitoring/__init__.py`
- CREATE `backend/vertical_engines/wealth/monitoring/alert_engine.py`
- CREATE `backend/vertical_engines/wealth/monitoring/drift_monitor.py`

**Alert engine:** Consumes existing worker events + adds DD Report expiry (>12 months since last DD), fund watchlist triggers, rebalance overdue. Publishes via Redis pub/sub.

**Drift monitor:** Bridge to existing `quant_engine/drift_service.py`. Adds universe-aware drift (deactivated fund → flag affected portfolios).

##### Task 5.4: FundAnalyzer Rewiring

**Files:**
- MODIFY `backend/vertical_engines/wealth/fund_analyzer.py` — rewire + structlog migration
- DELETE `backend/vertical_engines/wealth/dd_report_engine.py` (old scaffold, if not deleted in Phase 1)
- MODIFY `backend/vertical_engines/wealth/__init__.py` — update exports

**Rewire:**
- `run_deal_analysis()` → delegates to `dd_report.DDReportEngine.generate()`
- `run_portfolio_analysis()` → delegates to `quant_analyzer.analyze_portfolio()`
- Document `fund_id`/`deal_id` semantic mapping: `fund_id = org fund context`, `deal_id = target fund being evaluated`

**Acceptance criteria:**
- [ ] FundAnalyzer delegates to real implementations
- [ ] `ProfileLoader.get_engine_module("liquid_funds")` returns functional engine
- [ ] `make check` passes
- [ ] Integration test: full DD Report generation via FundAnalyzer interface

---

## System-Wide Impact

### Interaction Graph

```
Route handler (async)
  → asyncio.to_thread(FundAnalyzer.run_deal_analysis)
    → DDReportEngine.generate()
      → evidence_pack.build() → RAG retrieval (ai_engine) + quant_engine services
      → chapters.generate_chapter() × 8 (parallel DAG: 1-7 concurrent, 8 sequential)
      → critic.service.critique() → LLM call, max 3 iterations per flagged chapter
      → persist DDReport + DDChapter (sync Session)
    → Redis pub/sub → SSE stream to client
  → UniverseService.add_fund() → creates UniverseApproval (pending)

Worker (async, scheduled)
  → portfolio_eval.py → quant_engine services → PortfolioSnapshot
  → drift_check.py → quant_engine services → RebalanceEvent
  → fact_sheet_gen.py → fact_sheet_engine → PDF → StorageClient
```

### Error Propagation

- DDReportEngine: never-raises → returns `status: 'NOT_ASSESSED'`, logged via structlog
- Chapter failure: individual chapter marked `critic_status: 'escalated'`, report continues
- Quant engine failure: quant injection returns empty dict, chapter generated without quant data (degraded)
- PDF generation failure: logged, fact-sheet marked as failed, retry available
- Worker failure: PostgreSQL advisory lock prevents concurrent re-runs, next scheduled run retries

### State Lifecycle Risks

- **DDReport partial failure:** Resume safety via `DDChapter.content_md IS NOT NULL` check. Orphaned chapters cleaned up if report is regenerated.
- **PortfolioSnapshot → ModelPortfolio:** Snapshot references profile string, not ModelPortfolio FK. Renaming a profile would orphan snapshots. Mitigated by using CHECK constraint on profile values.
- **UniverseApproval `is_current` flag:** Multiple approvals for same asset. Only latest `is_current=True`. Concurrent approval race: use `SELECT FOR UPDATE` on fund row.

### API Surface Parity

New routes follow existing patterns in `routes/funds.py`, `routes/portfolios.py`. All use:
- `response_model=` on every endpoint
- `get_db_with_rls` for session
- `require_ic_member` decorator for governance endpoints
- Pydantic schemas with `model_validate()`

## Acceptance Criteria

### Functional Requirements

- [ ] DD Reports generate 8 chapters with real LLM content and evidence injection (parallel DAG)
- [ ] Adversarial critic challenges conclusions with max 3 iterations
- [ ] Asset Universe contains approved funds + auto-approved bonds
- [ ] Model Portfolios construct from universe with score-weighted fund selection
- [ ] Track-record shows backtest (marked), live NAV, and stress scenarios
- [ ] Fact-sheets render in 2 PDF formats (executive 2pg, institutional 6pg)
- [ ] Content production generates Investment Outlook, Flash Report, Manager Spotlight
- [ ] 3 governance approval points enforced
- [ ] All existing workers continue to function (no regression)

### Non-Functional Requirements

- [ ] DD Report generation completes in <3 minutes (8 chapters parallel + critic)
- [ ] Fact-sheet PDF generation completes in <30 seconds
- [ ] All new tables have RLS with subselect pattern
- [ ] All prompts use `SandboxedEnvironment`
- [ ] `make check` passes (lint + typecheck + test)

### Quality Gates

- [ ] Golden tests for DD Report output (one sample fund)
- [ ] Golden tests for fact-sheet data assembly
- [ ] Migration round-trip tested (upgrade + downgrade)
- [ ] Multi-agent code review (architecture, performance, security, data integrity)

## Dependencies & Prerequisites

1. **Security Prerequisites (Prereqs 0.1-0.3)** — Fix PromptRegistry SandboxedEnvironment, migrate wealth routes to `get_db_with_rls`, migrate scaffolds to structlog. **Must complete before Phase 1.**
2. **Pipeline LLM-Deterministic Alignment refactor** (separate branch) — Phase 1 (hybrid classifier) should complete before DD Report document ingestion is fully wired. DD Reports can start with manual document context while pipeline completes.
3. **Current migration head: `0007_governance_policy_seed`** — new migration is `0008` with `down_revision = "0007"`. (Fixed in round 2 — was stale)
4. **Existing quant_engine services** — all implemented and tested. New additions: `attribution_service.py`, `portfolio_metrics_service.py`, `peer_comparison_service.py`.
5. **ReportLab + matplotlib** — already in dependencies (used by credit PDF generation).

## Risk Analysis & Mitigation

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| DD Report quality insufficient for institutional clients | Medium | High | Iterative prompt refinement + golden tests + critic engine |
| LLM token costs exceed budget (8 chapters × critic iterations) | Medium | Medium | Per-chapter `max_tokens` in calibration, 30s timeout, configurable model tier |
| Backtest with insufficient fund history | High | Medium | Minimum 252-day requirement, clear "simulated" marking |
| ESG data unavailable from public APIs | High | Low | Placeholder chapter, populated when commercial data available |
| Pipeline refactor not complete when DD ingestion needed | Medium | Medium | Manual document context path as fallback |
| PDF rendering performance on large portfolios | Low | Medium | Chart caching, async generation via worker |

## Future Considerations

- **Client Reports** — requires operational client data models (client entity, portfolio-client mapping, cash flows). No scaffold created (YAGNI) — implement when data layer exists.
- **Bond Analysis** — `Bond` model exists in migration. Build `bond_analysis/` package when bond data provider is available. Auto-approval flow designed but not implemented.
- **Peer Comparison DD Chapter** — add when Asset Universe has enough funds per AllocationBlock for meaningful comparison.
- **ESG DD Chapter** — add when commercial ESG data provider contracted (MSCI/Sustainalytics).
- **Lipper/LSEG integration** — fund ratings data feed. `LipperRating` model already exists (empty). `lipper_service.py` in quant_engine ready.
- **Bloomberg/Morningstar** — commercial data enrichment. Engine architected for drop-in feeds.
- **Private markets expansion** — DevOps roadmap Phase 5. Would require new vertical engine or wealth sub-vertical.

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-wealth-vertical-complete-modularization-brainstorm.md](docs/brainstorms/2026-03-15-wealth-vertical-complete-modularization-brainstorm.md)
  - Key decisions: mirrored architecture, multi-class universe, expanded DD chapters, dual fact-sheet formats, backtest+live+stress track-record, 3 governance points, public APIs only, content production scope
  - Azure DevOps roadmap alignment validated (Phases 1, 2, 4 covered)

### Internal References

- Credit vertical reference: `backend/vertical_engines/credit/` (91 files, 13 packages)
- Credit deep review orchestrator: `backend/vertical_engines/credit/deep_review.py`
- Credit critic pattern: `backend/vertical_engines/credit/critic/service.py`
- Credit evidence pack: `backend/vertical_engines/credit/memo/evidence.py`
- Credit chapter generation: `backend/vertical_engines/credit/memo/chapters.py`
- BaseAnalyzer interface: `backend/vertical_engines/base/base_analyzer.py`
- PDF base module: `backend/ai_engine/pdf/pdf_base.py`
- ProfileLoader: `backend/ai_engine/profile_loader.py`
- Quant engine: `backend/quant_engine/` (14 services)
- Wealth domain: `backend/app/domains/wealth/` (models, routes, schemas, workers)

### Institutional Learnings Applied

- Wave 1 credit modularization: serial PR strategy, edgar-style DAG, golden tests
- Wealth Macro Intelligence Suite: 4-layer architecture, frozen dataclasses, 18-agent review bugs
- RLS subselect pattern: 1000x slowdown prevention
- Thread-safe rate limiting: threading.Lock on concurrent fetches
- Hybrid classifier: 3-layer (deterministic → TF-IDF → LLM) for document classification

### DevOps Roadmap Alignment

- Phase 1 > Manager DD Framework (ID:131) → `dd_report/` + `asset_universe/`
- Phase 1 > Strategic Model Portfolios Design (ID:132) → `model_portfolio/` + `quant/`
- Phase 2 > Data Infrastructure Setup (ID:135) → Global pipeline + quant_engine feeds
- Phase 2 > Analytical Toolkit (ID:136) → `monitoring/` + `dd_report/`
- Phase 2 > Proprietary Content Production (ID:137) → standalone content files (`investment_outlook.py`, `flash_report.py`, `manager_spotlight.py`)
- Phase 4 > Institutional Track Record (ID:143) → `model_portfolio/track_record.py`
- Phase 4 > Professional Client Reporting (ID:144) → `fact_sheet/`

---

## Research Insights (Round 2 Deep Dive)

### Credit Vertical Patterns to Mirror

Based on thorough exploration of `vertical_engines/credit/` (91 files, 13 packages):

**Package hierarchy (enforced by import-linter):**
- `models.py` (LEAF): zero sibling imports, only dataclasses/enums/protocols
- Helpers/parsers (LEAF): only model imports
- `service.py` (ORCHESTRATOR): imports all sibling modules + external engines
- `__init__.py`: PEP 562 lazy imports via `__getattr__()` — avoids circular deps, keeps boot time O(1)

**Key patterns from credit `deep_review/service.py` (13-stage pipeline):**
- Token ceilings by mode (`full_mode=True` unlocks higher limits)
- Cost governance via `TokenBudgetTracker` passed to all `_call_openai()` invocations
- Model routing via `get_model("structured")`, `get_model("critic")` — single source of truth
- Function-level imports for sibling engines (not module scope) — prevents circular deps
- `StageOutcome` frozen dataclass for named unpacking of `asyncio.gather()` results

**Key patterns from credit `memo/chapters.py`:**
- `CHAPTER_REGISTRY` authoritative table — single source of truth for all chapter metadata
- Per-chapter evidence filtering via `_SHARED_PACK_SECTIONS | _CHAPTER_EXTRA_SECTIONS[tag]` — reduces input ~60-70%
- Deterministic evidence summary at system_prompt top for OpenAI prompt caching activation
- Document diversity enforcement (min 4 unique sources per chapter)
- `prepare_only=True` mode returns prompts without calling LLM (useful for batch client)

**Key patterns from credit `critic/service.py`:**
- `CriticVerdict` frozen dataclass with 8 fields + `to_dict()` for serialization
- Pre-computed deterministic macro-consistency checks merged into LLM verdict via dataclass reconstruction
- Escalation to stronger model when confidence < 0.75 or fatal flaws exist
- `call_openai_fn` injected via Protocol — polymorphic LLM behavior

### Async DAG Best Practices

**Prefer `asyncio.TaskGroup` over `asyncio.gather` for chapter parallelism:**
- TaskGroup cancels siblings on first failure (structured concurrency)
- No `return_exceptions` ambiguity — per-task try/except allows partial results
- Reserve `gather(return_exceptions=True)` for mixed-criticality stages

**Layered timeout architecture for DD Report:**
```
Layer 1: OpenAI SDK timeout=60        — prevents single API call hang
Layer 2: asyncio.timeout(45)/chapter  — prevents retry storms
Layer 3: asyncio.timeout(180) total   — prevents entire report exceeding 3 min
Layer 4: critic max_iterations=3      — prevents infinite adversarial loops
```

**CRITICAL: `asyncio.timeout()` only fires at await points.** For true thread-level cancellation, the per-call timeout on the HTTP client (OpenAI SDK `timeout` param) is the defense.

**Error classification (from credit's `StageOutcome` pattern):**
- Fatal chapters: `executive_summary`, `recommendation` — failure aborts report
- Degradable chapters: all others — failure logs warning, report continues with partial results
- Minimum threshold: generate recommendation only if ≥5/7 chapters succeeded

### Fund Scoring Enhancements

**Current scoring (6 factors) — recommended additions:**

| Factor | Weight | Status |
|---|---|---|
| `risk_adjusted_return` (Sharpe) | 0.20 | Existing |
| `downside_risk` (Sortino) | 0.15 | **NEW** — Sharpe penalizes upside volatility equally |
| `drawdown_control` (Calmar + Max DD) | 0.15 | Enhanced (add Calmar ratio) |
| `information_ratio` | 0.10 | Existing |
| `return_consistency` (multi-horizon) | 0.15 | **Enhanced** — score across 6m/1y/3y/5y windows |
| `flows_momentum` | 0.10 | Existing |
| `fee_efficiency` (expense ratio rank) | 0.05 | **NEW** |
| `aum_stability` (AUM growth volatility) | 0.05 | **NEW** |
| `lipper_rating` | 0.05 | Existing (feature-flagged) |

**Score normalization: percentile rank within peer group** instead of hardcoded min/max bounds. Handles outliers naturally and is more interpretable ("85th percentile of peer group").

**Fund selection edge cases:**
- Ties: secondary sort by (1) lower expense ratio, (2) higher AUM, (3) longer track record
- Min weight threshold: positions below 2% eliminated (transaction costs > diversification benefit)
- Max concentration: existing `ProfileConstraints.max_single_fund_weight` from profiles.yaml
- Weight clipping: iterative clip-and-redistribute algorithm with max 10 iterations

### Brinson-Fachler Attribution (Reference for Future Implementation)

**Correct formulas (Brinson-Fachler, NOT BHB):**
```
Allocation_i  = (w_p_i - w_b_i) * (r_b_i - R_b)    ← relative benchmark adjustment
Selection_i   = w_b_i * (r_p_i - r_b_i)              ← uses w_b_i, not w_p_i
Interaction_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)
Identity:       R_p - R_b = sum(A) + sum(S) + sum(I)  ← must hold exactly
```

**Carino (1999) multi-period linking:**
- Period factor: `k_t = (ln(1+r_p_t) - ln(1+r_b_t)) / (r_p_t - r_b_t)` (L'Hopital when equal)
- Cumulative factor: `K = (ln(1+R_p) - ln(1+R_b)) / (R_p - R_b)`
- Scaled effects: `A'_t = A_t * (k_t / K)` — guarantees linked effects sum to compounded excess
- Numerical stability: weight epsilon `1e-10`, return equality epsilon `1e-12`, log clamp `1e-12`

**Testing: property-based with Hypothesis** — effects must sum to excess return (atol=1e-10).

### PDF Generation Best Practices

**P0: Add structural PDF tests** — currently zero coverage on 4 PDF generators:
- Smoke tests: valid PDF header (`%PDF-`), minimum page count, content assertions via `pikepdf`
- Chart renderer unit tests: valid PNG output, correct axis count
- Use `pikepdf` for structural assertions (CI-friendly, no poppler dependency)

**P1: BaseDocTemplate migration** — enables auto-TOC with real page numbers, clickable bookmarks, distinct cover/body page templates. Uses `multiBuild()` (two-pass rendering).

**P1: KPI row builder for fact-sheets** — grid of large-font value boxes (AUM, Sharpe, Vol, CVaR) with delta indicators (green/red). Standard institutional fact-sheet hero section.

**P2: Vector SVG for fact-sheet charts** — svglib (already a dependency) converts matplotlib SVG to ReportLab Drawing. Better zoom/print quality. Fallback to PNG 200 DPI for unsupported features.

### Institutional Learnings Applied (14 of 21 docs/solutions/ files relevant)

| Learning | Applies To | Key Insight |
|---|---|---|
| `rls-subselect-1000x-slowdown` | Migration 0008 | Bare `current_setting()` evaluates per-row. Use `(SELECT current_setting(...))` |
| `alembic-monorepo-migration-fk-rls-ordering` | Migration 0008 | Phased table creation (leaf→parent→edge), bulk RLS generation after all tables |
| `thread-unsafe-rate-limiter-FredService` | asyncio.to_thread calls | Any sync object shared across threads MUST use `threading.Lock()` |
| `llm-output-sanitization-nh3-persist-boundary` | DD chapter persistence | Call `sanitize_llm_text()` on ALL LLM output before DB writes |
| `prompt-registry-distributed-search-paths` | Wealth prompts | Register search path via `add_search_path()` in `wealth/__init__.py` |
| `azure-search-tenant-isolation` | RAG queries in DD Reports | Every search query MUST include `$filter=organization_id eq '{org_id}'` |
| `wealth-macro-intelligence-suite` | 4-layer architecture | Proven pattern: routes→engines→quant→ConfigService. Session injection, frozen dataclasses |
| `wave1-credit-vertical-modularization` | Package structure | 6-8 module split per package, import-linter from day 1, golden tests |
| `wave2-deep-review-modularization` | DAG extraction | NTFS workaround (staging dir), async/sync dedup, `db.add_all()` batching |
| `vertical-engine-extraction-patterns` | BaseAnalyzer interface | ProfileLoader + ConfigService + StorageClient exclusively |
| `phase3-storageclient-adls-dualwrite` | PDF storage | StorageClient abstraction, dual-write ordering (ADLS first, search second) |
| `pydantic-migration-review-findings` | Config schemas | Use `extra="ignore"` or `extra="forbid"`, never `extra="allow"`, derive field lists from canonical source |
| `unified-pipeline-ingestion-path` | Content production | Design one canonical pipeline entry point, validation gates between stages |
| `dead-code-audit-ai-engine-legacy-cleanup` | Scaffold deletion | Clean delete of replaced scaffolds, update __init__.py exports |

### Deployment Checklist Summary

**Pre-deploy baseline (SQL):** Record fund counts per org, verify alembic=0007, verify no new tables/columns.

**Migration 0008 lock risk:** LOW. ALTER `funds_universe` uses `server_default` + `nullable` → no table rewrite, millisecond lock. CREATE TABLE/INDEX on empty tables → no locks on existing tables.

**Rollback ladder:**
1. Disable feature flag → routes return 503 (instant, no data impact)
2. Deploy previous code version (if code bugs)
3. `alembic downgrade 0007` (if migration issues — drops new tables, removes approval_status)
4. **Never revert Prereq 0.2** (restores active vulnerability)

**Post-deploy monitoring (24h):** HTTP 500 rate, RLS errors, DD Report wall-clock, advisory lock contention, Redis pub/sub backlog. Hourly integrity checks: orphaned chapters, is_current uniqueness, approval_status validity.

### Sources

- [Python 3.14 asyncio-task docs](https://docs.python.org/3/library/asyncio-task.html) — TaskGroup, timeout
- [ReportLab PDF Accessibility](https://docs.reportlab.com/pdf-accessibility/) — Tagged PDFs, bookmarks
- [ReportLab Platypus](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/) — BaseDocTemplate, multiBuild
- [Morningstar Medalist Rating Methodology (May 2024)](https://s21.q4cdn.com/198919461/files/doc_downloads/2024/05/Morningstar-Medalist-Rating-Methodology-Effective-28-May-2024.pdf) — Fund scoring
- [Vanguard: The Rebalancing Edge (Dec 2024)](https://corporate.vanguard.com/content/dam/corp/research/pdf/the_rebalancing_edge.pdf) — Threshold vs calendar rebalancing
- [Federal Reserve 2025 Stress Test Scenarios](https://www.federalreserve.gov/publications/2025-stress-test-scenarios.htm) — Stress testing
- [CFA Level III — Brinson-Fachler Attribution](https://analystprep.com/study-notes/cfa-level-iii/sources-of-portfolio-returns/) — Attribution formulas
- [R-Finance PortfolioAttribution — Carino.R](https://github.com/R-Finance/PortfolioAttribution/blob/master/R/Carino.R) — Multi-period linking
- Carl Bacon, *Practical Portfolio Performance Measurement and Attribution* (Wiley, 2nd ed.) — Industry standard reference
