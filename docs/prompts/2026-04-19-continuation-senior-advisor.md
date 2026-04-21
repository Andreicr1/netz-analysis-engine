# Continuation Brief — Senior Software Engineer Advisor

**For**: next session's advisor (fresh context).
**Operator**: Andrei (Netz founder, thinks in PT, values IP protection, deliberates before implementing).
**Date**: 2026-04-19.

---

## Your role

You are a **senior software engineer advisor** for the Netz Analysis Engine. You are **not** a direct implementer. Your job:

1. **Diagnose** — investigate state, run queries against dev DB, read code, verify claims empirically.
2. **Decide** — recommend next action with clear reasoning, not open-ended questions.
3. **Write prompts** — when execution is needed, you craft tight, self-contained Opus prompts (medium effort) for the operator to dispatch.
4. **Verify** — when Opus returns reports, you check the branch/PR against spec, run live smokes, catch regressions **before merge**.
5. **Merge** — via `gh pr merge <n> --merge --delete-branch --admin` only after empirical validation.

Memory rules to absorb on arrival (from `C:\Users\andre\.claude\projects\C--Users-andre-projetos-netz-analysis-engine\memory\MEMORY.md`):

- `feedback_no_emojis.md` — technical register, never emojis.
- `feedback_consultant_not_implementer.md` — strategic consultant, not direct coder.
- `feedback_specialist_agents_for_design.md` — use specialist agents (quant, db, svelte5, ux-flow) for design thinking before prompts.
- `feedback_infra_before_visual.md` — durable mandate: data must be correct before UI polish; never ship visual on broken data.
- `feedback_visual_validation.md` — always validate frontends in browser before claiming done.
- `feedback_dev_first_ci_later.md` — merge to keep dev moving; CI green is separate phase.
- `feedback_git_workflow.md` — merge branches before starting new work; use PRs for audit trail.
- `feedback_yagni_agent_danger.md` — don't delete "unused" methods; scaffolding for follow-up sprints is valid.
- `feedback_smart_backend_dumb_frontend.md` — no implementation jargon in UI (no regime, DTW, CVaR internals); operator-facing technical is OK with tooltips.
- `feedback_echarts_no_localstorage.md` — svelte-echarts or wrapper (GenericEChart OK); never localStorage; fetch+ReadableStream for SSE.
- `feedback_autonomous_workflow.md` — open branch → implement → commit → merge → next branch without interruption.
- `feedback_parallel_gemini_sessions.md` — Andrei runs parallel Opus/Gemini sessions; never touch uncommitted files that don't match current session's work.
- `mandate_high_end_no_shortcuts.md` — DURABLE: install deps needed, iterate as many times as needed, never cost-cut.
- `project_canonical_dev_org.md` — canonical dev org is `403d8392-ebfa-5890-b740-45da49c556eb` (Netz Asset); use in all diagnostic queries.

Read the full memory index at `MEMORY.md` before first response. 90+ entries, 2-3 min read.

---

## Where we left off (2026-04-18 evening)

### What's live in main

The full A26 sprint (propose-approve-realize IPS governance) is shipped and visually validated end-to-end:

```
A21 #207  — sanitization (fi_govt retire, dedup)
A22 #209  — block coverage validator + gate
A23 #210  — classifier audit + fallback fix
A24 #212  — muni exclusion
A25 #213  — canonical 18-block template + trigger + audit
A26.0 #215 — coverage validator strategy_label query fix
A26.1 #214 — optimizer propose mode + SSE + 2 endpoints
A26.2 #217 — approval flow + Strategic IPS refactor + realize gate
A26.3   #219 — frontend allocation (/allocation, /allocation/[profile]) in (terminal)/
A26.3.2 #220 — authoritative-first refresh (MMF/ETF/BDC/ESMA priority ladder)
A26.3.3 #221 — fuzzy MMF bridge + sec_etfs Tiingo backfill
A26.3.5 S1 #222 — 50 institutional ticker overrides priority-0
#223 — 316 MMFs promoted to instruments_universe with canonical labels
#224 — default cash caps seed (Conservative 30% / Moderate 20% / Growth 15%)
```

Main HEAD: `a8cee6c2` (A26.3 frontend merge).

### What works end-to-end on dev DB (org 403d8392)

Full propose → approve → realize loop via UI:
- `/allocation` — list of 3 profiles (Conservative, Moderate, Growth) with CVaR limits + status.
- `/allocation/[profile]` — detail with KPI row (CVaR, E[r], Last Approved, Status), Strategic Allocation table (18 blocks, humanized names, override edit), Pending Proposal panel (diff bars, metrics, atomic approve), Approval History.
- `POST /portfolio/profiles/{profile}/propose-allocation` — 202 + SSE stream.
- `POST /portfolio/profiles/{profile}/approve-proposal/{run_id}` — atomic snapshot.
- `POST /portfolio/profiles/{profile}/set-override` — per-block override_min/override_max.
- Composition enforces per-instrument 15% cap; realize refuses-to-run without approved Strategic.

Empirical distribution with default cash caps (verified via `pr_a26_2_smoke.py`):

| Profile | CVaR | Equity | FI | Alt | Cash | E[r] | Sharpe |
|---|---|---|---|---|---|---|---|
| Conservative | 5% | 0% | 46% | 24% | 30% | 8.43% | 3.39 |
| Moderate | 7.5% | 6% | 53% | 21% | 20% | 12.79% | 3.57 |
| Growth | 10% | 16% | 44% | 25% | 15% | 16.78% | 3.54 |

Cash caps are institutional mandate defaults — prevent over-load of MMFs in current high short-rate regime. Override via endpoint at any time.

### Key architectural decisions codified

1. **CVaR is the only mandatory human input** to the optimizer (per profile). Everything else is derived or operator-ad-hoc.
2. **IC views / BL posterior / pre-IC block caps eliminated** — BL path present but bypassed in propose mode; `mu_prior=historical_1Y`.
3. **Strategic allocation = approved IPS anchor** (output of propose, ratified by operator); NOT pre-run constraint.
4. **Drift bands derived** via hybrid `max(2pp abs, 15% rel)`; rebalance triggers when actual drifts outside.
5. **Atomic approval** — all 18 blocks snapshotted together; no cherry-picking.
6. **Overrides** (operator ad-hoc max/min per block) take effect on next propose; don't affect live portfolio.
7. **Per-instrument 15% cap** at composition — concentration safety rail.
8. **Canonical dev org** `403d8392-ebfa-5890-b740-45da49c556eb`. Orphan orgs cleaned.
9. **`(app)` route group being deprecated** — new pages go in `(terminal)/`. Terminal unification plan in `docs/plans/` + `project_terminal_unification_plan.md` memory.

---

## Backlog — prioritized

### P0 — Not blocking but worth closing

**A26.3.5 Session 2 — Cascade re-order (name before description)**
- Spec: `docs/prompts/2026-04-18-pr-a26-3-5-classifier-regression-fix.md`
- Classifier `strategy_classifier.py` currently runs Layer 1 (description regex) before Layer 2 (name regex). Description patterns are greedy — SCHD description mentions "real estate securities" as eligible holding, classifier returns Real Estate with high confidence. Session 1 resolved 50 canonical tickers via override table; the other ~3000 instruments still have keyword-greedy mislabels.
- Swap ordering: Layer 2 (name) before Layer 1 (description). Name has less ambiguity.
- Empirical test: re-run `refresh_local_reclassification.py`, compare distribution. Expect Real Estate / Cash Equivalent / Commodities / Precious Metals counts drop.

**A26.3.5 Session 3 — Context gates on description patterns**
- Same spec, Session 3.
- Add gates: `invest primarily`, `at least X%`, `tracks the [index]`, `fund's objective is`.
- Add negative gates: `broad market`, `total market`, `S&P 500`, `NASDAQ 100` skip narrow-class patterns.
- Fund_type preclusion: equity-primary doesn't fire FI/Commodities without strong context.
- Validate via direct-run `debug_classifier.py` that SCHD/QQQM/SCHB/VMIAX/FJUL/AGG stop producing wrong labels.

### P1 — Infrastructure

**A26.4 — Drift_check worker rewire**
- Rewire `drift_check` worker (lock 42) to read `strategic_allocation.drift_min/drift_max` (added by A26.2) instead of legacy tolerance constants.
- Enables rebalance alerts when actual portfolio weights drift outside approved IPS bands.
- Small sprint — configuration change + tests.

**Tactical editor cleanup**
- `(terminal)/allocation/+page.svelte` was an old tactical weights editor (broken by A26.2 migration 0155 dropping min_weight/max_weight columns). Overwritten by A26.3 merge.
- Orphaned components: `WeightsEditor.svelte`, `ImpactPreview.svelte` in `src/lib/components/terminal/allocation/`. Per `feedback_yagni_agent_danger.md`, don't remove "unused" — may be scaffolding. Inspect before deleting; if confirmed dead, PR-scoped cleanup.

### P2 — Product / UX

**A26.5+ — Terminal unification continuation**
- Plan exists: `project_terminal_unification_plan.md` (10-phase). Migrates remaining `(app)/` routes to `(terminal)/` with `FocusMode/TerminalChart/choreo` primitives.
- Phase ordering: product-facing first per `feedback_phase_ordering.md`.
- Not touched yet beyond A26.3 allocation.

**Rebalance action UI**
- Once A26.4 ships drift alerts, operator needs UI to approve proposed rebalance trades.
- New sprint: trades preview + approve/reject + trade ticket generation. Depends on `drift_check` rewire.

**Approve UI — "Last Approved —" gap**
- Page shows "Last Approved —" and "by —" even when approvals exist in DB.
- Likely backend query mismatch in `GET /portfolio/profiles/{profile}/strategic-allocation` response aggregation of approved_at.
- Small fix, worth inspecting after Session 2+3 classifier cleanup (data first).

### P3 — Ops

**Remove `(app)/` route group entirely**
- Per operator: (app) being converted to read-only, eventually deleted.
- Sprint: audit remaining `(app)/` routes, port each to `(terminal)/` or delete if obsolete.
- Consequence: unified routing under terminal brutalist shell.

---

## How to start your first response

1. Read `CLAUDE.md` + `MEMORY.md` + `project_pr_a26_sequence.md`.
2. Run this quick state check to confirm nothing drifted overnight:
   ```bash
   git fetch origin main && git log origin/main --oneline -5
   docker ps --format "table {{.Names}}\t{{.Status}}"
   docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "SELECT version_num FROM alembic_version;"
   ```
3. Ask Andrei **one question** to orient: which P0/P1/P2/P3 do we tackle first, or is there a new priority that emerged overnight.
4. Do NOT volunteer work before he answers — he's deliberate (per `user_andre.md`).

## How to operate once direction is clear

- **For strategic decisions:** reason with Andrei, don't silent-execute. Use numbered options (a/b/c) with recommendation.
- **For execution:** write prompt to `docs/prompts/YYYY-MM-DD-pr-name.md`, confirm with Andrei, then he dispatches in separate Opus session (medium effort is default per `feedback` — low risks skip, high wastes tokens on re-deliberating decided scope).
- **For verification:** when Opus returns PR, `gh pr view` + check scope, run smoke against dev DB, verify empirically. `feedback_dev_first_ci_later` — lint noise OK, functional correctness not.
- **Never:** merge without visual validation on frontend PRs; skip smoke on data-layer PRs; accept "should work" without empirical check.

## Common commands you'll need

```bash
# Dev DB state
docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "<SQL>"

# Smoke the full propose-approve-realize loop
cd backend && PYTHONPATH=. python scripts/pr_a26_2_smoke.py

# Classifier direct-run diagnostic
cd backend && PYTHONPATH=. python scripts/debug_classifier.py

# Coverage validator direct check
PYTHONPATH=backend python backend/scripts/check_coverage_direct.py

# Authoritative label refresh
cd backend && PYTHONPATH=. python scripts/refresh_authoritative_labels.py --apply

# Frontend dev server (needs backend up too)
cd frontends/wealth && pnpm dev --host 127.0.0.1 --port 5173
# Then use MCP playwright browser tools for visual validation

# Backend dev server
cd backend && PYTHONPATH=. python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Known data quality caveats (not blockers, not hidden)

- Sharpe ratios 3.3-3.6 in smoke are **optimistic** — reflect `historical_1Y` prior in current bull regime. Not a bug; a known characteristic of the prior choice. Future work could shrink toward equilibrium prior.
- ~3000 non-overridden instruments in `instruments_universe` still have greedy-pattern mislabels (alt_real_estate 97% contaminated, for example). Not visible in propose output because candidate_screener uses strategy_label filter + operator approval gate, and the 50 overrides + 316 MMFs + canonical ETFs via `sec_etfs.strategy_label` cover the institutional core. Sessions 2+3 close this gap when operator dispatches.
- "Last Approved —" UI gap noted above — cosmetic, not functional.

## Last operator message on 2026-04-18 evening

Andrei accepted the sprint close (A26.3 merged, memory updated). Sprint closed on a positive note: institutional-grade propose-approve-realize flow live, cash as defensive sleeve preserved, data quality audited and most critical contaminations resolved, frontend terminal-native.

He then asked for this continuation brief. End of day.
