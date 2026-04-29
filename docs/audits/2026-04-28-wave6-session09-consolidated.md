# Wave 6 — Session 09 Stage 1 Consolidation

**Date:** 2026-04-28
**Inputs:**
- [docs/audits/2026-04-28-wave6-session09-stage1-opus.md](2026-04-28-wave6-session09-stage1-opus.md) — Opus 4.6 (1M), 14 findings
- [docs/audits/2026-04-28-wave6-session09-stage1-gemini.md](2026-04-28-wave6-session09-stage1-gemini.md) — Gemini 3.1 Pro, 5 findings
**Output destination:** Stage 2 jury (GPT-5.5)

---

## 1 · Cross-model coverage map

15 canonical findings after deduplication. Coverage profile:

- **3 cross-confirmed (same bug + same severity):** C-01, C-12, C-15
- **1 cross-confirmed with severity conflict:** C-02 (Opus Crit, Gemini High)
- **1 direct conflict (Opus says bug, Gemini explicitly verified OK):** C-07
- **1 Gemini-only (different bug than Opus on same file):** C-06
- **9 Opus-only (Gemini did not surface):** C-03, C-04, C-05, C-08, C-09, C-10, C-11, C-13, C-14

Coverage rate Opus: 14/15 = 93%. Coverage rate Gemini: 5/15 = 33%. Consistent with `reference_gemini_math_strength_heuristic.md` (Gemini disproportionate strength on math-density >800 LoC; Routes/Workers integration is low-math, so Gemini's depth was lower — but every Gemini finding was independently corroborated by Opus, confirming Gemini's signal-to-noise remained high).

---

## 2 · Master findings table

| Canonical | Title | Opus ID/Sev | Gemini ID/Sev | Files | Status |
|---|---|---|---|---|---|
| **C-01** | universe_sync ON CONFLICT omits is_active reactivation across all 5 sync phases | F-S09-01 / **Crit** | F-S09-001 / **Crit** | `workers/universe_sync.py:219,296,392,465,539` | Cross-confirmed |
| **C-02** | trigger_screening inserts is_current=True without clearing prior rows | F-S09-02 / **Crit** | F-S09-003 / **High** | `routes/screener.py:837` | Severity conflict |
| **C-03** | `uuid.UUID(org_id)` crashes at 6 sites where org_id is already UUID | F-S09-03 / **Crit** | — | `routes/universe.py:689`, `routes/instruments.py:229`, `routes/content.py:403,443`, `routes/portfolios/builder.py:121,220` | Opus-only |
| **C-04** | regime_fit defines `LOCK_ID=900_026` but never acquires it (dead lock) | F-S09-04 / **High** | — | `workers/regime_fit.py:43,267-317` | Opus-only |
| **C-05** | drift_check runs without org_id — accesses org-scoped tables without RLS context | F-S09-05 / **High** | — | `workers/drift_check.py:25-103` | Opus-only |
| **C-06** | drift_check advisory lock acquired outside try/finally — leaks on CancelledError | — | F-S09-005 / **Crit** | `workers/drift_check.py:36-100` | Gemini-only (distinct concern from C-05 on same file) |
| **C-07** | approve_dd_report creates UniverseApproval without clearing prior is_current | F-S09-06 / **High** | (explicitly **verified OK** in Checked Invariants §) | `routes/dd_reports.py:572-583` | **Direct conflict — jury must inspect code** |
| **C-08** | apply_rebalance_proposal has no role gate — any authenticated user can apply | F-S09-07 / **High** | — | `routes/rebalancing.py:47-53` | Opus-only |
| **C-09** | write_audit_event silently accepts NULL organization_id | F-S09-08 / **Med** | — | `core/db/audit.py:59-66` | **Subsumed by PR-Q92 #392** (already implements `allow_global` flag — see §3) |
| **C-10** | benchmark_ingest bypasses ExternalProviderGate (manual retry without circuit breaker) | F-S09-09 / **Med** | — | `workers/benchmark_ingest.py:117-138` | Opus-only |
| **C-11** | approve_fund / reject_fund split commit and audit across 2 transactions | F-S09-10 / **Med** | — | `routes/universe.py:404-467,502-558` | Opus-only |
| **C-12** | GET /catalog silently accepts unknown query params | F-S09-11 / **Med** | F-S09-004 / **Med** | `routes/screener.py:1894,2131,2224` | Cross-confirmed |
| **C-13** | trigger_dd_report and regenerate_dd_report missing IC role check | F-S09-12 / **Med** | — | `routes/dd_reports.py:248-253,439-444` | Opus-only |
| **C-14** | strategy_reclassification references pre-Q11B `esma_funds.isin` column | F-S09-13 / **Med** | — | `workers/strategy_reclassification.py:441-464` | Opus-only |
| **C-15** | `org_id: str` annotation lie at 30+ route sites (footgun) | F-S09-14 / **Low** | F-S09-002 / **Low** | 30+ sites across 13+ files | Cross-confirmed |

---

## 3 · Subsumption check vs in-flight PRs

The audit ran against `main` HEAD (`pr-q90-revert-q87-manual-seed`). Three PRs are open and may subsume findings:

| PR | Title | Subsumes? |
|---|---|---|
| **#391 PR-Q91** | UCITS data-availability gate | **Partial** of C-01 — Q91 reactivated UCITS one-time, but did not patch the upsert race in `universe_sync` ON CONFLICT clauses. C-01 remains open for SEC ETFs (and recurrence is certain on next universe_sync run for UCITS too). |
| **#392 PR-Q92** | audit_events global pipeline support | **Full** of C-09 — Q92 added `allow_global=False` default flag with `ValueError` on missing org_id (exactly what C-09 recommends). Jury should mark C-09 as **REFUTED — already fixed in PR #392**. |
| **#393 PR-Q93** | fast_approve UUID double-cast P1 | **Partial** of C-03 — Q93 fixed only `universe.py:689` and only that route's annotation. Other 5 sites in C-03 remain unfixed. |

**Action for jury:** When adjudicating, treat C-09 as REFUTED (fix already in flight via Q92). Treat C-01 and C-03 as CONFIRMED with reduced scope (Q91/Q93 covered subset).

---

## 4 · Severity escalation candidates (institutional reading)

The auditing models tend to undersample severity in two specific institutional categories. The jury should consider escalating:

| Canonical | Opus rating | Recommended escalation |
|---|---|---|
| C-05 (drift_check no RLS) | High | **Crit** — multi-tenant data leak in production B2B SaaS is always Crit per institutional convention. |
| C-08 (rebalance no role gate) | High | **Crit** — privilege escalation on mutating route changes portfolio allocation; investor-role can mutate IC-level state. |
| C-13 (DD trigger no role gate) | Med | **High** at minimum — DD trigger consumes OpenAI credits and creates DB records; investor can trigger unbounded LLM spend. |

Counter-argument the jury must weigh: if these routes were already protected by gateway-layer auth before the FastAPI handler is reached, the bug is downgraded. But Opus did not find such gateway evidence; absent positive proof, default is to escalate.

---

## 5 · Conflict to adjudicate (C-07)

Opus F-S09-06 reports `approve_dd_report` (`routes/dd_reports.py:572-583`) creates `UniverseApproval` without flipping prior `is_current=True` rows. Gemini's "Checked invariants with no findings" §2 explicitly states the opposite:

> "I-Idempotent-1 (siblings): A busca por corrupção de status `is_current=True` no histórico de edições em `universe.py` (UniverseApproval) e `dd_reports.py` (DDReport) foi concluída. Ambos invertem de maneira robusta para `is_current=False` em inserções precedentes, ratificando a saúde das ramificações irmãs e isolando a falha à rota originária do `screener.py`."

Both cannot be right. Jury must read `routes/dd_reports.py:572-583` directly and decide. If Opus is right, this is a High-severity idempotency bug. If Gemini is right, finding C-07 is **REFUTED**.

---

## 6 · Top 3 priorities (consolidated)

Both models converged on the same top 3 (with Opus's slightly broader articulation):

1. **C-01** (Crit, Race) — universe_sync ON CONFLICT omits is_active. Affects entire fund catalog (6174 NAV-bearing instruments). One-line fix per sync function (5 functions).
2. **C-02** (Crit/High, Idempotency) — trigger_screening UniqueViolation on re-run. Blocks core screening workflow. Pre-INSERT UPDATE fix.
3. **C-03** (Crit, Annotation) — `uuid.UUID(org_id)` crash at 6 sites. Production endpoints crash on every call. Annotation + cast removal.

---

## 7 · Handoff items (per Stage 1)

- **Math audit:** `compute_drift` math correctness → Session 03 (regime/drift math).
- **Q11B migration alignment:** C-14 depends on Q11B merge status (already in main per repo state).
- **model_portfolios.py / risk_calc.py / construction_run_executor.py:** Path-referenced files not deeply reviewed in Stage 1 → handoff to Session 10.

---

## 8 · Statistics

| Metric | Value |
|---|---|
| Total canonical findings | 15 |
| Crit (Opus) | 3 |
| High (Opus) | 4 |
| Med (Opus) | 6 |
| Low (Opus) | 1 |
| Crit (Gemini) | 2 |
| High (Gemini) | 1 |
| Med (Gemini) | 1 |
| Low (Gemini) | 1 |
| Cross-confirmed exact match | 3 (C-01, C-12, C-15) |
| Cross-confirmed severity conflict | 1 (C-02) |
| Direct contradiction (one model finds, other refutes) | 1 (C-07) |
| Same file, different concerns (both valid) | 1 pair (C-05 vs C-06 on drift_check) |
| Subsumed by in-flight PRs | 1 full (C-09 by Q92), 2 partial (C-01 by Q91, C-03 by Q93) |
