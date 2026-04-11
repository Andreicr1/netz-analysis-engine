# Phase 2 Scope Audit — Investigation Brief

**Date:** 2026-04-11
**Mission:** Pure investigation. NO code changes. NO commits. Produce a structured markdown report so the primary Opus planner can write an accurate Phase 2 execution brief against the real current state of the backend.
**Branch:** any — this audit does not modify files

## Why this audit exists

The primary planner's Terminal Unification master plan (`docs/plans/2026-04-11-terminal-unification-master-plan.md`) lists a Phase 2 "Data Plane" scope with 13 Alembic migrations + sanitization module + new endpoints + worker changes. Preliminary investigation revealed the master plan is significantly stale — several items it lists as "gaps" may already exist, have different shapes, or be intentionally structured the way they are. Writing a Phase 2 execution brief on stale assumptions would violate the project's data-plane-correctness-first principle.

This audit verifies the CURRENT state of each Phase 2 scope item against the live codebase so the real gap list can be derived cleanly.

## How to execute

1. This is READ-ONLY investigation. Do not write, edit, or commit any file. Do not run migrations. Do not modify state.
2. Use Read, Grep, Glob, and Bash (read-only commands only) tools.
3. For each item in the Audit Checklist below, run the specified queries, read the specified files, and record findings.
4. Output ONE structured markdown report via the Report Format at the end.
5. If any item is ambiguous or requires judgment, report both the finding AND the ambiguity — do NOT resolve ambiguity yourself, that is the planner's decision.

## Audit Checklist

Work through all items in order. For each item, produce a verdict: `MISSING`, `EXISTS`, `EXISTS_WITH_DIVERGENT_SHAPE`, `PARTIAL`, `NOT_APPLICABLE`, or `NEEDS_HUMAN_DECISION`.

---

### A. Schema / Migrations

#### A.1 — `fund_risk_metrics.compress_segmentby` current value

Master plan claim: currently set to `'organization_id'`, which is wrong because the table is global with nullable org (NULL for almost all rows), breaking compression efficiency. Proposed fix: change to `'instrument_id'`.

**Investigate:**
- Read `backend/app/core/db/migrations/versions/0087_enable_timescale_compression.py` if it exists.
- Read `backend/app/core/db/migrations/versions/c3d4e5f6a7b8_timescaledb_hypertables_compression.py`.
- Grep `fund_risk_metrics` in all files under `backend/app/core/db/migrations/versions/` with `-C 3` context for any `compress_segmentby` or `ALTER TABLE ... SET` DDL.
- Check `backend/app/domains/wealth/models.py` or wherever `FundRiskMetrics` model is defined for `__table_args__` compression hints.
- If you can connect to the dev DB via `psql` (read the `DATABASE_URL` from env), run `SELECT hypertable_name, segmentby_column_name FROM timescaledb_information.compression_settings WHERE hypertable_name = 'fund_risk_metrics';` — but DO NOT modify state.

**Report:** current value, which migration set it, and whether master plan's proposed fix is still needed.

#### A.2 — `nav_timeseries.chunk_time_interval` current value

Master plan claim: currently 1mo, should be 3mo for the size of hot-chunk under 50k symbols.

**Investigate:**
- Grep `nav_timeseries` in migrations/versions for `create_hypertable` or `set_chunk_time_interval` calls.
- Read `backend/app/core/db/migrations/versions/0069_globalize_instruments_nav.py` (likely suspect from prior grep).
- Read `backend/app/core/db/migrations/versions/0027_nav_portfolio_hypertables.py` if it exists.

**Report:** current chunk interval, which migration set it, whether any later migration altered it.

#### A.3 — `wealth_vector_chunks.compress_segmentby` current value

Master plan claim: currently `'organization_id'`, should be `'source_type'` since org is mostly NULL for global embeddings.

**Investigate:**
- Grep `wealth_vector_chunks` in migrations/versions with `-C 3`.
- Read the migration that creates `wealth_vector_chunks` (likely around 0040-0080 range).

**Report:** current value, creation migration, alter history.

#### A.4 — `mv_unified_funds` refresh mode

Master plan claim: currently uses `REFRESH MATERIALIZED VIEW` (blocks reads), should use `REFRESH MATERIALIZED VIEW CONCURRENTLY` for non-blocking refresh. Requires a unique index on the MV.

**Investigate:**
- Grep `mv_unified_funds` in `backend/app/domains/wealth/workers/view_refresh.py` (or wherever the refresh is triggered).
- Check if a unique index exists on the MV — grep for `CREATE UNIQUE INDEX` in migrations referencing `mv_unified_funds`.
- Read `backend/app/core/db/migrations/versions/0078*.py` and `0094*.py` (the migrations that touch `mv_unified_funds`).

**Report:** current refresh mode, whether unique index exists, what needs to change.

#### A.5 — `portfolio_construction_runs` structure and event_log column

Master plan claim: not a hypertable, should be converted. Preliminary audit found: intentionally a regular table per migration 0099 docstring, event-sourced with full run context.

**Confirm:** master plan is wrong on the hypertable conversion. Do NOT recommend converting.

**Also investigate:**
- Does `portfolio_construction_runs` have an `event_log JSONB` column for SSE replay per master plan's Phase 4 commit 7 assumption? Read `0099_portfolio_construction_runs.py` fully to see column list.
- If missing, Phase 2 may need to add it for future SSE late-subscriber support. Flag as `NEEDS_HUMAN_DECISION` — the planner decides whether to add it now or defer.

**Report:** full column list of `portfolio_construction_runs`, whether `event_log` exists, whether any later migration (0100+) added it.

#### A.6 — RLS policies using bare `current_setting()`

Master plan claim: all RLS should use `(SELECT current_setting(...))` subselect, not bare `current_setting()`. Bare causes 1000x slowdown via per-row re-evaluation.

**Investigate:**
- Grep `current_setting` in `backend/app/core/db/migrations/versions/` excluding subselect pattern: `grep -rn "current_setting" backend/app/core/db/migrations/versions/ | grep -v "SELECT current_setting"`.
- Report any matches with file + line.

**Report:** number of bare `current_setting()` call sites in migrations, specific files and lines.

#### A.7 — `nav_monthly_returns_agg` CAGG shape already verified (DO NOT re-investigate)

Preliminary audit confirmed: exists in migration 0049, richer shape than master plan's `mv_nav_monthly_agg` proposal, has `(instrument_id, month DESC)` index, has 1-day refresh policy. Phase 2 does NOT need to create a new CAGG.

**Only verify:** is there a `UNIQUE` index on `(instrument_id, month)` or similar? If not, refresh CONCURRENTLY won't work (postgres requirement). Check migration 0049 or subsequent index migrations.

**Report:** unique index status.

---

### B. Endpoints

#### B.1 — `DELETE /jobs/{id}` cancel endpoint

Master plan assumption: Phase 4 Builder needs a job cancellation endpoint. Missing.

**Investigate:**
- Grep `"DELETE"` or `@router.delete` in `backend/app/core/jobs/` and `backend/app/domains/wealth/routes/`.
- Grep `jobs/{id}` or similar path patterns.
- Check if `backend/app/core/jobs/manager.py` (or similar) has a `cancel_job` method.

**Report:** exists / missing / partial (e.g., cancel method on manager but no HTTP endpoint).

#### B.2 — `GET /model-portfolios/{id}/construction/runs/{runId}/diff` endpoint

Master plan assumption: Phase 4 Builder needs a diff endpoint comparing run N vs run N-1. Missing.

**Investigate:**
- Read `backend/app/domains/wealth/routes/model_portfolios.py`.
- Grep `diff` and `runs/` in wealth routes.
- Check if any `runs` sub-router exists in construction_runs context.

**Report:** exists / missing.

#### B.3 — `GET /dd-reports/queue` aggregator endpoint

Master plan assumption: Phase 6 DD Track needs an aggregator returning `{pending[], inProgress[], completedRecent[]}`. Missing.

**Investigate:**
- Read `backend/app/domains/wealth/routes/dd_reports.py`.
- Grep `queue` in dd_reports route.
- Check if there's a separate `backend/app/domains/wealth/routes/long_form_reports.py` with similar aggregator.

**Report:** exists / missing / partial (individual endpoints exist but no aggregator).

---

### C. Sanitization

#### C.1 — `sanitize_public_event` module state

Preliminary audit confirmed: function does not exist. But need to investigate WHERE sanitization should live and whether ANY existing sanitization layer is already in place that the new module would retrofit or replace.

**Investigate:**
- Read `backend/vertical_engines/wealth/shared_protocols.py` fully (preliminary audit showed it has `CallOpenAiFn` Protocol, not sanitize — confirm).
- Grep `sanitize` (case-insensitive) in `backend/vertical_engines/wealth/` and `backend/app/domains/wealth/`.
- Grep `translate_regime` or `translate_cvar` or similar naming patterns.
- Check if `backend/app/domains/wealth/workers/construction_run_executor.py` has any event emission with string translation.
- Check if `backend/app/domains/wealth/workers/alert_sweeper.py` or `portfolio_eval.py` translate status enums.

**Report:** any existing translation/sanitization patterns, their locations, what they cover, what they miss. This informs whether the new module consolidates or creates from scratch.

#### C.2 — Response schema jargon leakage in existing routes

Master plan claims: `routes/risk_timeseries.py`, `routes/exposure.py`, `routes/entity_analytics.py` currently emit raw `cvar_95`, `dtw_distance`, regime enums, etc. They must be retrofitted through `sanitize_public_event()`.

**Investigate:**
- Read `backend/app/domains/wealth/schemas/risk_timeseries.py` — list all field names that look like raw quant (CVaR, DTW, regime, Sharpe, etc.).
- Read `backend/app/domains/wealth/schemas/entity_analytics.py` — same.
- Read `backend/app/domains/wealth/schemas/exposure.py` if it exists.
- For each raw field, note whether the frontend would see the raw name or a mapped name.

**Report:** list of raw quant field names per file, whether they leak to the API response.

---

### D. Worker state

#### D.1 — `global_risk_metrics` worker — current output fields and ELITE fit

Investigate the worker that computes `fund_risk_metrics`. Where would `elite_flag` computation fit? What inputs does it already have?

**Investigate:**
- Read `backend/app/domains/wealth/workers/risk_calc.py` (the worker with lock 900_007 and 900_071 per master plan).
- Find the main compute function. Note: every field it currently writes to `fund_risk_metrics` (Sharpe, volatility, drawdown, CVaR, momentum, etc.).
- Check if it has access to peer-quantile functions for computing "top decile within asset class".

**Report:** fields written, compute flow, dependencies on peer quantiles (needed for ELITE), fit for adding `elite_flag` + `elite_tier` emission.

#### D.2 — `construction_run_executor` — existing sanitization layer

Investigate whether the executor already has a sanitization step before publishing SSE events.

**Investigate:**
- Read `backend/app/domains/wealth/workers/construction_run_executor.py` fully (likely the main file).
- Find event publish / emit / stream write functions.
- Note whether event payloads are raw dicts or already have translated strings.

**Report:** sanitization state — none / partial / full. If partial, what's covered.

---

### E. Frontend ELITE expectations

#### E.1 — Frontend code referencing `elite_flag` / `is_elite` / ELITE

Preliminary audit found zero matches in backend. Check frontend too — if frontend already references ELITE, there's a consistency gap to understand.

**Investigate:**
- Grep `elite` (case-insensitive, word boundary) in `frontends/wealth/src/`.
- Grep `ELITE` in `frontends/wealth/src/` for UI strings or filter constants.

**Report:** any matches with file and line, whether they're UI strings, filter constants, or dead code.

---

### F. Prior plan context

#### F.1 — Read and summarize `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`

Preliminary audit found this plan referenced in `0099_portfolio_construction_runs.py`. It has its own Phase 1/2/4/6 numbering that may overlap with the master plan. Understanding its scope is critical for deriving Phase 2's real gap.

**Investigate:**
- Read the entire file.
- Summarize:
  - What's the overall goal?
  - What phases does it define?
  - Which phases are already shipped (look for commit evidence via git log of migrations it references)?
  - Which phases are pending?
  - Does it overlap with the Terminal Unification master plan's Phase 2 scope (data plane, sanitization, endpoints)?

**Report:** structured summary (goal / phases / shipped status / overlap zones).

---

### G. Other Phase 2 items already investigated (do not re-run)

Preliminary audit already confirmed:
- `elite_flag` / `elite_tier` — GENUINELY MISSING (zero matches in backend)
- `fast_track` — FULLY IMPLEMENTED in screener route, eviction_service, worker, registry
- `mv_fund_risk_latest`, `v_screener_org_membership`, `mv_construction_run_diff`, `mv_drift_heatmap_weekly` — GENUINELY MISSING (zero matches in migrations)
- `portfolio_weight_snapshots` — ALREADY a hypertable (migration 0102)

Do not re-investigate these. Include them in the final report under "Already Audited" for completeness.

---

## Report Format

Produce ONE markdown file or chat response with this exact structure. Do NOT include code diffs. Do NOT propose changes. Do NOT write a Phase 2 brief. Only report current state findings.

```markdown
# Phase 2 Scope Audit — Findings

**Audit run at:** <UTC timestamp>
**Auditor:** <agent identity>

## Section A — Schema / Migrations

### A.1 fund_risk_metrics compress_segmentby
- **Verdict:** <MISSING | EXISTS | EXISTS_WITH_DIVERGENT_SHAPE | PARTIAL | NOT_APPLICABLE | NEEDS_HUMAN_DECISION>
- **Current state:** <one paragraph>
- **Source of truth:** <migration filename + line number, or model path + line>
- **Master plan claim accurate:** <yes/no + explanation>
- **Recommended action (factual, not opinionated):** <one sentence>

### A.2 nav_timeseries chunk_time_interval
<same structure>

### A.3 wealth_vector_chunks compress_segmentby
<same structure>

### A.4 mv_unified_funds refresh mode
<same structure>

### A.5 portfolio_construction_runs event_log column
<same structure>

### A.6 RLS bare current_setting call sites
<same structure, plus a list of file:line matches if any>

### A.7 nav_monthly_returns_agg unique index
<same structure>

## Section B — Endpoints

### B.1 DELETE /jobs/{id}
<same structure>

### B.2 GET /model-portfolios/{id}/construction/runs/{runId}/diff
<same structure>

### B.3 GET /dd-reports/queue aggregator
<same structure>

## Section C — Sanitization

### C.1 sanitize_public_event module and existing patterns
- **Verdict:** <MISSING | PARTIAL | EXISTS_WITH_DIVERGENT_SHAPE>
- **Current state:** <paragraph on what sanitization exists anywhere, even if scattered>
- **Existing call sites found:** <file:line list>
- **What consolidation would replace:** <if partial, what the new module would supersede>

### C.2 Response schema jargon leakage
- **Files inspected:** <list>
- **Raw quant fields emitted per file:** <table or list>
- **Total leakage count:** <number>

## Section D — Worker state

### D.1 global_risk_metrics / risk_calc worker
- **Current computed fields:** <list>
- **Peer-quantile function availability:** <yes/no + source>
- **Fit for elite_flag emission:** <one paragraph assessment>

### D.2 construction_run_executor sanitization
- **Verdict:** <none | partial | full>
- **Current emission pattern:** <one paragraph>
- **Event types with raw jargon:** <list>

## Section E — Frontend ELITE expectations

### E.1 Frontend ELITE references
- **Matches found:** <file:line list, with classification (UI string / filter constant / dead code / real consumer)>

## Section F — Prior plan context

### F.1 portfolio-enterprise-workbench.md summary
- **Goal:** <one sentence>
- **Phases:** <list with numbering and scope summary>
- **Shipped phases:** <list with commit evidence>
- **Pending phases:** <list>
- **Overlap with Terminal Unification master plan Phase 2:** <paragraph analyzing overlap zones>

## Section G — Already audited items (reference only)
<list from the checklist above, no new investigation needed>

## Aggregated scope matrix

| Item | Verdict | Phase 2 action |
|---|---|---|
| elite_flag / elite_tier columns | MISSING | Create migration + worker emission |
| fast_track | EXISTS | Skip |
| fund_risk_metrics compress_segmentby | <your verdict> | <factual action> |
| ... | ... | ... |

## Open questions for human decision

<list of items flagged NEEDS_HUMAN_DECISION with the specific ambiguity>
```

## Constraints

- Zero file modifications
- Zero commits
- Zero git state changes
- If unsure, report ambiguity — do NOT decide
- If a file is too large to read fully, read in chunks but cover the complete file
- If you find additional Phase 2-adjacent items not in this checklist, note them in a "Section H — Other findings" at the end
- Budget: investigation should take ~30-60 minutes of agent time. If it exceeds 90 minutes, stop and report what you have with a "partial audit" flag at the top.

Begin by reading the file paths specified in Section A.1. Proceed through each section in order.
