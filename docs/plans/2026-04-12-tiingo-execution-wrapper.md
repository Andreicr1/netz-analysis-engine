# Tiingo Migration — Execution Wrapper

**Date:** 2026-04-12
**Specification:** `docs/plans/2026-04-11-tiingo-migration-plan.md` (1210 lines, the AUTHORITATIVE spec)
**Status:** Ready for execution in 3 sessions
**Priority:** DATA INTEGRITY GATE — per wealth-platform-architect recommendation 2026-04-12

## Why this wrapper exists

The Tiingo migration plan was written on 2026-04-11 before Phase 2 shipped. Since then:

1. **Alembic head advanced from 0109 to 0119** — Phase 2 shipped 10 migrations (0110-0119). The plan's migration `0110_tiingo_default_source` must be renumbered to `0120_tiingo_default_source`.

2. **PR-A already implemented** in worktree `C:/Users/andre/projetos/netz-tiingo-migration` at commit `3ab773c1`. But this commit is based on `b10649e8` (PR #103 merge, ~60+ commits behind current main). It may or may not cherry-pick cleanly.

3. **Session discipline** needs to be applied — the plan defines 3 PRs but lacks our standard verification/self-check/escape-hatch format.

This wrapper adds the missing context. **The plan itself is the spec.** Read it in full before starting.

## Critical context updates

### Alembic renumbering

| Plan says | Actual (renumber to) |
|---|---|
| `0110_tiingo_default_source` | `0120_tiingo_default_source` |
| `down_revision = "0109_risk_metrics_audit_trail"` | `down_revision = "0119_mv_drift_heatmap_weekly"` |

Verify via `alembic heads` before writing any migration. If another sprint shipped between now and session start, adjust accordingly.

### Worktree PR-A code

The worktree at `C:/Users/andre/projetos/netz-tiingo-migration` has commit `3ab773c1` with 5 files implementing PR-A. Two options:

**Option A (recommended):** Create a fresh branch from current main, cherry-pick `3ab773c1`, resolve conflicts if any (likely in `providers/__init__.py` which Phase 2 may have touched). If conflicts are trivial, this saves re-implementation time.

**Option B:** Ignore the worktree entirely, re-implement PR-A from the plan spec on a fresh branch. More work but cleaner — no conflict resolution, no stale code risk.

Pick whichever produces a cleaner result. Under the mandate, correctness > speed.

### Files the plan references that may have changed

| File | Plan assumes | Current state |
|---|---|---|
| `providers/__init__.py` | Pre-Phase-2 state | May have additional imports from Phase 2 sanitize work |
| `benchmark_ingest.py` | Pre-Phase-2 state | Phase 2 Session A may have touched chunk settings |
| `schemas/catalog.py` | `nav_source: Literal["yfinance"]` | Phase 3 Session A added `elite_flag`, `in_universe`, keyset pagination fields |
| `routes/screener.py` | Pre-Phase-3 state | Phase 3 heavily modified (catalog joins, sparklines, fast-approve) |
| `models/benchmark_nav.py` | `server_default="yfinance"` | May be unchanged |

**Rule:** when the plan says "modify line N", verify the current state of the file first. Line numbers have shifted. Use grep to find the correct location.

## 3-session execution

### Session 1 — PR-A: Provider layer

**Branch:** `feat/tiingo-pr-a` (fresh from main, NOT the worktree branch)

**Read:** `docs/plans/2026-04-11-tiingo-migration-plan.md` §4 (Work package PR-A)

**Deliverable:** 5 files per the plan:
1. Modified: `tiingo_provider.py` — async batch helper
2. New: `tiingo_instrument_provider.py` — sync worker-facing provider
3. Modified: `providers/__init__.py` — factory default swap
4. New: `test_tiingo_provider_layer.py` — 17 tests
5. Modified: `test_fefundinfo_provider.py` — factory test update

**Gate:** plan §4.6 commands (ruff, mypy, pytest, lint-imports)

**Cherry-pick option:** if using Option A (cherry-pick from worktree), run:
```bash
git checkout -b feat/tiingo-pr-a main
git cherry-pick 3ab773c1
# Resolve conflicts if any
# Run gate commands
```

**Instruction for Opus:**
```
Read docs/plans/2026-04-11-tiingo-migration-plan.md sections 1-4 fully and docs/plans/2026-04-12-tiingo-execution-wrapper.md fully. You are implementing PR-A (provider layer). Either cherry-pick commit 3ab773c1 from feat/tiingo-migration-pr-a and resolve conflicts, OR re-implement from the spec in §4 — whichever is cleaner. Run the gate commands from §4.6. Report files changed, test results, and any deviations from the plan.
```

### Session 2 — PR-B: Worker cutover + migration

**Branch:** `feat/tiingo-pr-b` (from main AFTER PR-A merged)

**Read:** `docs/plans/2026-04-11-tiingo-migration-plan.md` §5 (Work package PR-B)

**Deliverable:**
1. Migration `0120_tiingo_default_source.py` (renumbered from plan's 0110)
2. Worker cutover: `instrument_ingestion.py` (docstring + source label updates)
3. Worker rewrite: `benchmark_ingest.py` (the hard one — replace yfinance direct import with TiingoInstrumentProvider)
4. Delete deprecated `ingestion.py` worker
5. Schema/route updates: `catalog.py`, `screener.py`, `benchmark_nav.py`
6. Test fixture updates (Option 1 per plan: update fixtures in same PR)

**Gate:** plan §5.6 commands + `alembic upgrade head` + `alembic downgrade -1`

**Critical:** migration `down_revision` must point to `0119_mv_drift_heatmap_weekly` (or whatever `alembic heads` returns at session start). NOT `0109`.

**Instruction for Opus:**
```
Read docs/plans/2026-04-11-tiingo-migration-plan.md sections 5 fully and docs/plans/2026-04-12-tiingo-execution-wrapper.md fully. Verify PR-A merged (TiingoInstrumentProvider importable). Migration must be numbered 0120, not 0110 (Phase 2 used 0110-0119). Run alembic heads before writing the migration. Use Option 1 for test fixtures (update in same PR). Run gate commands from §5.6. Report.
```

### Session 3 — PR-C: Cleanup + full gate

**Branch:** `feat/tiingo-pr-c` (from main AFTER PR-B merged AND verified in at least one worker cycle)

**Read:** `docs/plans/2026-04-11-tiingo-migration-plan.md` §6 (Work package PR-C)

**Deliverable:**
1. Delete `yahoo_finance_provider.py`
2. Remove `yfinance` from `pyproject.toml` dependencies
3. Drop sector fallback in `data_providers/sec/shared.py`
4. Update backfill + seed scripts
5. Rewrite test mocks (7 files per plan §6.5)

**Gate:** `make check` MUST pass — this is the final sign-off. Full lint + architecture + typecheck + test.

**Instruction for Opus:**
```
Read docs/plans/2026-04-11-tiingo-migration-plan.md section 6 fully and docs/plans/2026-04-12-tiingo-execution-wrapper.md fully. Verify PR-B merged and workers ran at least once (check nav_timeseries for source='tiingo' rows). Delete yahoo provider, remove yfinance dep, drop sector fallback, rewrite 7 test mock files per §6.5. Gate: make check must pass completely. Report.
```

## Post-merge operations (Session 4 — operational, not code)

After PR-C merged, per plan §7:

1. **Re-ingest NAV:** `python scripts/run_global_worker.py instrument_ingestion`
2. **Re-run risk_calc:** `python scripts/run_global_risk_metrics.py`
3. **Validate coverage:** SQL queries from plan §7.3

These are OPERATIONAL commands, not code commits. Run them against the local dev DB first, then against prod after the migration catch-up.

**Expected outcome:** `blended_momentum_score` and `peer_sharpe_pctl` repopulate from 0% to ~90%+ coverage. ELITE ranking recalculates with correct inputs. Composite scores shift (median likely moves from 52 to something different because momentum + peer components are no longer zero).

## Verification gates per session

### PR-A gate
- [ ] `ruff check` on provider files → clean
- [ ] `mypy` on provider files → clean (ignoring pre-existing)
- [ ] `pytest test_tiingo_provider_layer.py test_fefundinfo_provider.py test_instrument_ingestion.py test_market_data_ws.py` → green
- [ ] `lint-imports` → 31 contracts kept, 0 broken
- [ ] Factory returns `TiingoInstrumentProvider` by default

### PR-B gate
- [ ] `alembic upgrade head` → clean (migration 0120 applied)
- [ ] `alembic downgrade -1` → clean
- [ ] `ruff check` on worker files → clean
- [ ] `pytest test_benchmark_ingest.py test_instrument_ingestion.py` → green (fixtures updated)
- [ ] `ingestion.py` deleted, zero references remaining
- [ ] `grep -rn "yfinance\|yf\.download\|YahooFinanceProvider" backend/app/domains/wealth/workers/` → zero matches

### PR-C gate
- [ ] `make check` → FULL GREEN (lint + architecture + typecheck + test)
- [ ] `yahoo_finance_provider.py` deleted
- [ ] `yfinance` removed from `pyproject.toml`
- [ ] `grep -rn "yfinance\|yf\." backend/` → zero matches outside of test fixtures and historical comments
- [ ] `pip install -e .` → no import errors

## Valid escape hatches

1. Cherry-pick from worktree has unresolvable conflicts → re-implement from spec (Option B)
2. `benchmark_ingest.py` structure changed significantly since the plan was written → read the current file, adapt the rewrite pattern, preserve the same outcome
3. Migration 0120 conflicts with another sprint that shipped between now and execution → renumber to next available
4. `make check` in PR-C fails on pre-existing issues (mypy, typecheck) → isolate: verify the failures exist on main before PR-C, document as pre-existing, do NOT mask
5. Test fixtures need more than just mock-target renaming (DataFrame shape changed) → read the test, understand what it asserts, rewrite the fixture to match Tiingo's output shape while preserving the assertion's intent

## Not valid escape hatches

- "yfinance still works, we can keep it as fallback" → NO, the plan says "retirar Yahoo de uma vez por todas" (Andrei's words). Clean cutover, no fallback.
- "I'll skip the sector fallback removal in PR-C" → NO, every yfinance reference must be eliminated
- "Test mocks are too many to rewrite" → NO, 7 files per the plan. Each is a mock-target rename + fixture shape adjustment.
