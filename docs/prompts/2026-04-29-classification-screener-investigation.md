# Investigation: Classification Quality + Screener/Filter Reachability

**Created:** 2026-04-29
**Repo:** `Andreicr1/netz-analysis-engine` (branch: `main`)
**Mode:** Research-only. **Do NOT modify code.** Produce a written report.

---

## Background

Users report ongoing fund-classification problems (`strategy_label` and asset-class assignments behaving incorrectly in the Wealth screener, DD reports, and portfolio construction). PR #170 (`fix/local-reclassification-refresh`) is still open but is read-only (writes to `strategy_reclassification_stage` only) and is not the cause. PR #169 (round-1 classifier patches) is presumed merged — confirm this is the case as Step 1.

Separately, we need to confirm the user-facing path from log-in to the Wealth screener terminal and to each filter the screener exposes (mandate fit, quant filters, eliminatory rules, peer group, drift) so we can validate that what users see actually consumes the (possibly broken) `strategy_label` data.

You will run two investigations in parallel and produce a single consolidated report.

---

## Repository orientation (from CLAUDE.md, do not re-derive)

- **Classification engine (universal, domain-agnostic):**
  `backend/ai_engine/classification/hybrid_classifier.py`
  Three-layer cascade: keyword rules → cosine similarity (TF-IDF) → LLM fallback.
- **Wealth strategy classifier (3-layer keyword classifier for `strategy_label`):**
  `backend/scripts/backfill_strategy_label.py` (idempotent backfill)
  Plus the worker `app/domains/wealth/workers/strategy_reclassification.py`
- **Wealth screener (3-layer deterministic):**
  `backend/vertical_engines/wealth/screener/` (eliminatory → mandate fit → quant)
- **Fund import enrichment:**
  `import_sec_security()` in the wealth domain — enriches `instrument.attributes` with
  N-CEN flags, XBRL fees, `strategy_label`, `is_index`, etc.
- **Fund-centric catalog (read path for the screener):**
  Materialised view `mv_unified_funds` (migration 0078). Query helper at
  `backend/app/domains/wealth/queries/catalog_sql.py`.
- **Frontend:** `frontends/wealth/` (SvelteKit app, served at `wealth.investintell.com`).
- **Auth:** Clerk JWT. Roles: `ADMIN`, `INVESTMENT_TEAM`, `investor`.
- **DB:** PostgreSQL 16 + TimescaleDB + pgvector. Local Docker DB is the source of truth
  for dev (`netz-analysis-engine-db-1`).

---

## Part A — Classification quality root-cause

Goal: localise where wrong `strategy_label` / asset-class values are being produced or
preserved, and identify the smallest set of files that need attention.

### A.1 — Confirm PR #169 status

- Use the GitHub MCP (`mcp__github__pull_request_read`) to fetch PR #169 metadata.
- If merged, find the merge SHA and confirm the patch files are present on `main`.
- If still open or closed-without-merge, that alone explains regressions.

### A.2 — Audit the classifier cascade end-to-end

Read these in order and note each branch where a label could be silently lost or
misassigned:

1. `backend/ai_engine/classification/hybrid_classifier.py`
   - Confirm the layer-1 keyword rules, layer-2 cosine threshold, layer-3 LLM fallback.
   - Check what happens when all three layers miss (does it return `None`, `"unknown"`,
     or raise?).
2. `backend/app/domains/wealth/workers/strategy_reclassification.py`
   - What `run_id` lifecycle does it follow? Does it overwrite `strategy_label` on
     source tables or only stage?
   - Is the apply gate (`severity` filter) actually wired up?
3. `backend/scripts/backfill_strategy_label.py`
   - Three-layer keyword classifier: fund-name regex → hedge sub-strategy → brochure
     content enrichment. Is each layer reached? Are there short-circuits?
4. `backend/vertical_engines/wealth/...` for the import path
   (`import_sec_security`) — confirm what attributes get written and whether the
   classifier is invoked synchronously at import time or asynchronously by the worker.

### A.3 — Inspect the staging table for the latest run

Run these queries against the local Docker DB
(`docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "..."` or via
the appropriate session). Capture row counts and a small sample of each:

```sql
-- Latest run per source
SELECT source_table, run_id, MAX(classified_at) AS latest, COUNT(*) AS n
  FROM strategy_reclassification_stage
 GROUP BY source_table, run_id
 ORDER BY latest DESC
 LIMIT 20;

-- Severity distribution for the latest run_id
SELECT source_table,
       COUNT(*) FILTER (WHERE current_strategy_label IS NOT DISTINCT FROM proposed_strategy_label) AS unchanged,
       COUNT(*) FILTER (WHERE current_strategy_label IS NULL AND proposed_strategy_label IS NOT NULL) AS new_class,
       COUNT(*) FILTER (WHERE current_strategy_label IS NOT NULL AND proposed_strategy_label IS NULL) AS lost_class,
       COUNT(*) FILTER (WHERE current_strategy_label <> proposed_strategy_label) AS changed,
       COUNT(*) AS total
  FROM strategy_reclassification_stage
 WHERE run_id = (SELECT run_id FROM strategy_reclassification_stage
                  ORDER BY classified_at DESC LIMIT 1)
 GROUP BY source_table;

-- Top fallback patterns (where the cascade gave up)
SELECT classification_source, COUNT(*) AS n
  FROM strategy_reclassification_stage
 WHERE run_id = (SELECT run_id FROM strategy_reclassification_stage
                  ORDER BY classified_at DESC LIMIT 1)
 GROUP BY classification_source
 ORDER BY n DESC;

-- Production vs proposed mismatch on actual source tables
SELECT 'sec_manager_funds' AS src,
       COUNT(*) FILTER (WHERE strategy_label IS NULL) AS null_label,
       COUNT(*) FILTER (WHERE strategy_label = 'Other') AS other,
       COUNT(*) AS total
  FROM sec_manager_funds
UNION ALL
SELECT 'sec_registered_funds', COUNT(*) FILTER (WHERE strategy_label IS NULL),
       COUNT(*) FILTER (WHERE strategy_label = 'Other'), COUNT(*)
  FROM sec_registered_funds
UNION ALL
SELECT 'sec_etfs', COUNT(*) FILTER (WHERE strategy_label IS NULL),
       COUNT(*) FILTER (WHERE strategy_label = 'Other'), COUNT(*)
  FROM sec_etfs;
```

Report back the numbers verbatim.

### A.4 — Find unreasonable rows

Pull 20 random rows whose `strategy_label` is suspect (look for "Other", NULL, or
fund-name vs label obvious mismatches like `fund_name ILIKE '%treasury%'` →
`strategy_label != 'Government Bond'`). Cite source table + PK + name + label.

### A.5 — Determine whether the staged labels are actually being applied

Look for the apply path: the worker stages, but who promotes stage rows to the source
tables? Search for callers of `strategy_reclassification_stage` writes vs reads, and
for any `UPDATE ... SET strategy_label = ...` statements. If the stage is never
applied, that's the smoking gun.

---

## Part B — Screener terminal & filter reachability

Goal: produce a complete map of how a logged-in user reaches the Wealth screener and
which DB columns / pre-computed metrics each filter reads, so we can verify the broken
classification data flows there.

### B.1 — Frontend route map

In `frontends/wealth/src/`:
- Identify the SvelteKit route(s) that render the screener UI (likely `+page.svelte`
  under a `screener/` subtree).
- Trace the navigation path from login (`/sign-in`) to the screener: which menu items,
  which `<a href>` or programmatic navigations, and any role gates (Clerk role checks,
  layout-level redirects).
- List the file path of every component used by the screener page (table, filter
  drawer, pagination, exports).

### B.2 — Filter inventory

For each filter the user can interact with on the screener page, record:
- Filter name (as shown in UI).
- The Svelte component file + the prop / store that holds the filter state.
- The query parameter or POST body field it serialises into.
- The backend route that consumes it (file + line).
- The SQL column or pre-computed metric it filters on (in `mv_unified_funds`,
  `fund_risk_metrics`, `instruments_org`, etc.).

Pay particular attention to:
- **Strategy / asset-class filters** — these directly consume `strategy_label`.
- **Mandate-fit filter** — `vertical_engines/wealth/mandate_fit/` (constraint
  evaluator).
- **Quant filters** — Sharpe, CVaR, vol, momentum, fee — read from `fund_risk_metrics`.
- **Eliminatory filters** — minimum AUM, vintage, region, share-class restrictions
  (Layer 1 of the 3-layer screener).
- **Approval / universe filters** — `instruments_org.approval_status`.

### B.3 — Backend screener endpoints

Find the FastAPI routes under `backend/app/domains/wealth/routes/` (or a subpath) that
serve the screener. For each:
- Method + path + Pydantic request schema + response model.
- Auth role (`Role.INVESTMENT_TEAM`, `Role.ADMIN`, etc.).
- The exact query in `catalog_sql.py` (or wherever) that they call.
- Whether the response includes `strategy_label` directly or only the derived asset
  class.

### B.4 — Materialised-view refresh cadence

`mv_unified_funds` is refreshed by `view_refresh.py` after `universe_sync` and other
ingestion workers. Confirm:
- Where the refresh trigger is wired (which workers explicitly call refresh).
- Whether a stale view could mask classifier fixes from showing up in the screener.

---

## Deliverable

A single Markdown report written to
`docs/audits/2026-04-29-classification-screener-investigation.md` containing:

1. **Executive summary** (≤ 200 words). State the most likely root cause(s) of
   classification problems and whether the screener actually consumes the broken data.
2. **Part A findings:**
   - PR #169 status (merged SHA or "unmerged").
   - Classifier cascade audit notes (per file, per branch).
   - Verbatim SQL output (latest run severity, fallback distribution, NULL/Other
     counts on source tables).
   - 20 sample suspect rows with the label-vs-name mismatch reasoning.
   - Apply-gate verdict: are staged labels promoted to production columns? If not,
     which file should do it.
3. **Part B findings:**
   - Login → screener navigation path (frontend file paths).
   - Filter inventory table (one row per filter, columns as in B.2).
   - Backend route table (one row per endpoint).
   - Materialised-view refresh diagram (worker → refresh → screener visibility).
4. **Recommendations** (3-5 bullets). Concrete next actions, ranked by impact.
   Each must cite the file path where the fix would land. **Do not implement.**

---

## Out of scope

- Modifying any code, migrations, or data.
- Running ingestion workers (no SEC / ESMA / Tiingo fetches).
- Touching production `strategy_label` columns.
- PR #170 itself — already established it is read-only and not the cause.

---

## Tools you will use

- `Bash` for `git log`, `grep`, `psql`, `docker exec`.
- `Read` for source files (do not re-export, do not edit).
- `Agent` (`Explore` subagent) for breadth searches across the SvelteKit frontend if
  `grep` becomes impractical.
- `mcp__github__pull_request_read` for PR #169 status.

Run independent searches in parallel where possible. Time-box at 60 minutes; if you
hit a blocker, surface it in the report rather than spending more time.
