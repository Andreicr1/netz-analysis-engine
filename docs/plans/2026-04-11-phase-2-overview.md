# Phase 2 — Data Plane Overview

**Date:** 2026-04-11
**Status:** Planning complete, briefs ready for execution
**Branch target:** `feat/terminal-unification-phase-2-session-{a,b,c}`
**Depends on:** Phase 1 foundations + Part C shell merged (main at `e26465b8` or later)
**Out of scope:** Tiingo migration — runs in a separate sprint (`docs/plans/2026-04-11-tiingo-migration-plan.md`)

## Why this file exists

This is the shared context document for the three Phase 2 execution sessions. Each session brief (`2026-04-11-phase-2-session-a-physical-schema.md`, `...-session-b-analytical-layer.md`, `...-session-c-api-surface.md`) references this overview as mandatory prerequisite reading. Reading this first saves every session from repeating the same context.

## Phase 2 mission

Close the data-plane gaps that the Terminal Unification master plan identified, **as derived from the verified audit** in `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` — NOT as originally proposed in the master plan, which the audit proved significantly stale.

Phase 2 ships 18 atomic commits across 3 sessions. Each session is one Opus-concentrated sprint. No session touches another session's files. Dependencies flow only forward (session A → B → C).

## Audit-derived scope (verified against live codebase)

The master plan proposed 13 migrations + new sanitize module + hypertable conversions. The audit proved many of those were wrong:

**Items the master plan was WRONG about (DO NOT include):**
- `sanitize_public_event` create-from-scratch — `backend/app/domains/wealth/schemas/sanitized.py` already exists with `METRIC_LABELS` (CVaR, GARCH, etc.) + `REGIME_LABELS` (RISK_ON → Expansion) + Pydantic mixins. Phase 2 RETROFITS through it, does not create.
- `mv_unified_funds` refresh CONCURRENTLY migration — `view_refresh.py` L29 already uses CONCURRENTLY with fallback.
- `wealth_vector_chunks.compress_segmentby` alter — the table is regular, not a hypertable. Phase 2 converts AND sets compression, but there's no existing segmentby to "fix".
- `portfolio_construction_runs` hypertable conversion — migration 0099 intentionally made it a regular table for event-sourced run history. DO NOT convert.
- RLS bare `current_setting()` fix — audit confirmed subselect pattern is consistently followed. Zero fixes needed.
- `fast_track` column on `instruments_org` — already exists in 5 files (screener route, eviction worker, registry). Skip.
- ELITE complex definition (top-decile multi-component) — see "ELITE definition" below.

**Items that are GENUINELY missing and Phase 2 creates:**

1. `fund_risk_metrics.compress_segmentby` fix — audit confirmed `organization_id` at `c3d4e5f6a7b8 L104`. Table is global with mostly-NULL org. Must change to `instrument_id`.
2. `portfolio_construction_runs.event_log JSONB` column — confirmed missing. Dependency of Phase 4 Builder SSE replay + mv_construction_run_diff.
3. `nav_timeseries.chunk_time_interval` tuning — audit confirmed DEFAULT 7 days (not 1mo as master plan claimed). Benchmark required before picking 3mo / 6mo / 1yr.
4. `nav_monthly_returns_agg` unique index — required for CONCURRENT refresh. Audit confirmed non-unique index at `0049 L60, 0069 L165`.
5. `wealth_vector_chunks` hypertable conversion with compression — audit confirmed regular table at `0059_wealth_vector_chunks`. No compression at all today.
6. `elite_flag` + `elite_rank_within_strategy` + `elite_target_count_per_strategy` columns on `fund_risk_metrics`.
7. `mv_fund_risk_latest` materialized view — pointer to latest `as_of` per instrument.
8. `v_screener_org_membership` security-barrier view — pre-joins `instruments_org` for screener "already in my universe" flag.
9. `mv_construction_run_diff` materialized view — run N vs N-1 weight + metrics delta. Depends on event_log from #2.
10. `mv_drift_heatmap_weekly` continuous aggregate — weekly drift buckets for dashboard.
11. `risk_calc` worker ELITE ranking logic — coordinated with global default allocation blocks (see "ELITE definition" below).
12. `construction_run_executor` sanitize retrofit — audit confirmed ZERO sanitization in event emission. Retrofit via `sanitized.py`.
13. `RiskTimeseriesOut` schema sanitize retrofit — audit confirmed `volatility_garch` + raw regime enums leaking. Retrofit via Pydantic mixin.
14. `DELETE /jobs/{id}` cancel endpoint — confirmed missing in `workers.py`, `tracker.py`.
15. `GET /model-portfolios/{id}/construction/runs/{runId}/diff` endpoint — confirmed missing, depends on mv_construction_run_diff.
16. `GET /dd-reports/queue` aggregator — confirmed missing in `dd_reports.py`, `long_form_reports.py`.
17. `make loadtest` target + screener scenario — new harness to prove p95 < 300ms at 50k rows with ELITE filter and verify partial-index usage via `EXPLAIN (ANALYZE, BUFFERS)`.

Total: 17 commits + 1 investigation step (chunk interval benchmark) folded into commit 3 body = 17 commits across 3 sessions.

## ELITE definition (locked)

The ELITE fund ranking has a specific semantics that Phase 2 MUST implement, NOT the simple threshold-based model the master plan proposed:

**Definition:** The 300 best-scored funds from the entire catalog, distributed across strategies proportionally to the percentages of a global default strategic allocation.

**Computation algorithm:**

1. Read the global default allocation blocks — the authoritative strategic allocation weights per strategy (e.g., 40% US Equities, 25% International Equities, 20% Fixed Income, 10% Alternatives, 5% Cash). Stored in `allocation_blocks` table or equivalent — session 2.B brief includes investigation step to confirm exact source and shape.
2. For each strategy `s` with weight `w_s`, compute `target_count_s = round(300 * w_s)`. These should sum to 300 (or very close, with rounding tolerance).
3. Within each strategy, rank all funds by their composite score (from `fund_risk_metrics.composite_score` or equivalent — session 2.B brief includes investigation step to confirm which column holds the score).
4. Set `elite_flag = true` for funds where `rank_within_strategy <= target_count_s`.
5. Also populate `elite_rank_within_strategy` (the ordinal rank) and `elite_target_count_per_strategy` (the computed target count for that strategy) for traceability.

**Dependencies:**
- Composite score computation already exists in `backend/quant_engine/scoring_service.py`. Phase 2 does NOT modify the score formulation.
- Score inputs (momentum, peer percentiles, etc.) are currently degraded due to Yahoo Finance ingestion issues. **The Tiingo Migration sprint will fix this.** Phase 2's ELITE ranking worker will produce correct results AFTER Tiingo migration completes, and partial results before. The schema and logic Phase 2 ships are independent of the data quality of inputs.
- Global default allocation blocks source — must be confirmed in session 2.B (see commit 11 in that session).

**Why not the simple managerScore >= 75 definition:** the frontend currently uses that threshold as a quick visual hack (`TerminalRiskKpis.svelte` L198), but Andrei has explicitly specified the correct definition is the 300-by-strategy quota. The frontend's simple hack will be replaced by consuming the real `elite_flag` when Phase 3 Screener lands.

## Project mandate (binding for all Phase 2 sessions)

> Usaremos os recursos mais avançados disponíveis para dar ao sistema o máximo de performance e percepção visual de um produto high-end e high-tech, não importa quantas vezes tenhamos que retornar ao mesmo item para corrigi-lo ou quantas novas dependências devam ser instaladas. Sem economia ou desvios para simplificações.

**Amplified for Phase 2:** Visual polish is only valid when infrastructure is correct and reporting real accurate data. Phase 2 IS the infrastructure correctness layer — no shortcuts, no half-measures, no "we'll fix it later" on compression, chunk intervals, index uniqueness, or sanitization wiring. Every migration must be rigorously benchmarked where applicable. Every retrofit must eliminate jargon leakage at the source, not patch it in consumers.

## Dependencies between sessions

```
Session 2.A (Physical Schema)
  ├── 0110 compress_segmentby fix      [no deps]
  ├── 0111 event_log column            [no deps — but unblocks mv_construction_run_diff in 2.B]
  ├── 0112 chunk_interval tune         [benchmark investigation, no code deps]
  ├── 0113 nav_monthly_returns_agg unique index  [no deps]
  └── 0114 wealth_vector_chunks hypertable       [no deps]

Session 2.B (Analytical Layer)
  ├── 0115 elite_flag schema            [no deps]
  ├── 0116 mv_fund_risk_latest          [no deps]
  ├── 0117 v_screener_org_membership    [no deps]
  ├── 0118 mv_construction_run_diff     [DEPENDS ON 2.A commit 0111 event_log]
  ├── 0119 mv_drift_heatmap_weekly      [no deps]
  ├── confirm global allocation blocks source    [investigation — determines commit 7 shape]
  └── risk_calc ELITE ranking logic      [depends on 0115 + allocation blocks source]

Session 2.C (API Surface)
  ├── construction_run_executor sanitize retrofit  [no deps — consumes existing sanitized.py]
  ├── RiskTimeseriesOut schema sanitize retrofit   [no deps — consumes existing sanitized.py]
  ├── DELETE /jobs/{id} cancel endpoint              [no deps in 2.A/2.B, but requires cooperative cancellation in executor]
  ├── GET /runs/{runId}/diff endpoint                [DEPENDS ON 2.B commit 0118 mv_construction_run_diff]
  ├── GET /dd-reports/queue aggregator               [no deps]
  └── make loadtest target + screener scenario      [DEPENDS ON 2.B commit 0115 elite_flag columns]
```

**Critical:** Session 2.C cannot begin until Session 2.B lands. Session 2.B cannot begin until Session 2.A lands. Each session is a review gate — merge 2.A to main before starting 2.B, merge 2.B to main before starting 2.C.

## Mandatory READ FIRST list (applies to every session)

Every session brief will list session-specific files to read. These files are shared across all three:

1. `docs/plans/2026-04-11-terminal-unification-master-plan.md` — original scope (but treat as REFERENCE only, not as authoritative — audit superseded several items)
2. `docs/plans/2026-04-11-phase-2-overview.md` — THIS FILE
3. `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` — verified audit that drove the revised scope
4. `CLAUDE.md` or `GEMINI.md` — Critical Rules, Stability Guardrails, Data Ingestion Workers sections
5. `backend/app/core/db/migrations/versions/` — glob for recent migration style reference (0105-0109)
6. `backend/app/domains/wealth/schemas/sanitized.py` — the sanitization module sessions 2.C must retrofit through
7. Project memories:
   - `mandate_high_end_no_shortcuts.md`
   - `feedback_infra_before_visual.md`
   - `feedback_parallel_gemini_sessions.md`

## Alembic head

Current head as of Phase 2 start: `0109_fund_risk_audit_columns`. Phase 2 migrations start at `0110`. If main has advanced (parallel session shipped another migration), rebase Phase 2 onto the new head.

**Important:** the Tiingo Migration sprint may ship migration 0110 (`0110_tiingo_default_source.py`) in its own timeline. If that migration lands in main before Phase 2 session 2.A starts, Phase 2 migrations start at `0111` or later. First step of every Phase 2 session is `alembic heads` to confirm the current head and adjust numbering accordingly.

## Verification gates shared across all sessions

Every session must pass before ship:

1. `make check` green — lint + architecture + typecheck + test
2. `alembic upgrade head` clean on fresh docker-compose DB
3. `alembic downgrade -1` cleanly reverses every new migration (no `IF EXISTS` shortcuts)
4. `node scripts/check-terminal-tokens-sync.mjs` still green (Phase 2 does not touch tokens, but smoke check)
5. `packages/investintell-ui build` still clean (Phase 2 does not touch this package, but smoke check)
6. For routes: `pytest backend/tests/` passes with new route tests included
7. No regressions in pre-existing test baselines

## Session execution discipline

Each session brief follows this structure:

1. Mission + mandate prerequisite read
2. Session-specific READ FIRST
3. Commit specs (each with purpose, deliverable, verification, commit message template)
4. Final full-tree verification
5. Self-check checklist
6. Valid + invalid escape hatches
7. Report format

When an Opus agent executes a session, it reads the overview + session brief, executes the commits in order, and produces the Report per the format. Human reviews between sessions.

## Parallel session safety

If the Tiingo Migration sprint is running in parallel in `C:/Users/andre/projetos/netz-tiingo-migration` worktree, Phase 2 sessions MUST:
- Avoid touching files in `backend/app/services/providers/` (Tiingo owns this)
- Avoid touching worker files other than the ones explicitly in scope (e.g., Phase 2 touches `risk_calc.py` and `construction_run_executor.py`; Tiingo touches `benchmark_ingest.py`, `instrument_ingestion.py`, `ingestion.py`)
- Coordinate Alembic head numbering — first step of every session is `alembic heads` check
- Re-base onto main frequently

Memory file `feedback_parallel_gemini_sessions.md` applies: do not touch files modified in another session's working tree.

## Next steps

Execute sessions in strict order:

1. Open Opus session on `feat/terminal-unification-phase-2-session-a` branch
2. Point it at `docs/plans/2026-04-11-phase-2-session-a-physical-schema.md` + this overview
3. Ship 5 commits, review, merge to main
4. Open Opus session on `feat/terminal-unification-phase-2-session-b`
5. Point it at session B brief + this overview
6. Ship 7 commits, review, merge to main
7. Open Opus session on `feat/terminal-unification-phase-2-session-c`
8. Point it at session C brief + this overview
9. Ship 6 commits, review, merge to main
10. Phase 2 complete. Phase 3 Screener Fast Path unblocked.
