# Wave 6 — Session 10 Stage 1 Consolidation

**Date:** 2026-04-29
**Inputs:**
- [docs/audits/2026-04-29-wave6-session10-stage1-opus.md](2026-04-29-wave6-session10-stage1-opus.md) — Opus 4.6 (1M), 8 findings
- [docs/audits/2026-04-29-wave6-session10-stage1-gemini.md](2026-04-29-wave6-session10-stage1-gemini.md) — Gemini 3.1 Pro, 9 findings
**Output destination:** Stage 2 jury (GPT-5.5)

---

## 1 · Cross-model coverage map

14 canonical findings after deduplication.

- **3 cross-confirmed exact match:** C-05, C-12, C-13
- **5 Opus-only:** C-01, C-04, C-09, C-10, C-14
- **6 Gemini-only:** C-02, C-03, C-06, C-07, C-08, C-11

Coverage: Opus 8/14 = 57%, Gemini 9/14 = 64%. Roughly balanced — confirms the Session 10 prediction (math + workflow mix; both models essential). **Gemini outpaced Opus in raw count** (9 vs 8) — consistent with `reference_gemini_math_strength_heuristic.md`: Session 10 has high math density (CVaR sign, stress scaling, dispersion seed, block weight invariants).

Two pairs of findings span the same architectural defect from different angles:
- **C-01 + C-02:** state machine — Opus catches missing gate on live path (validate→approve), Gemini catches missing edge (constructed→approved when OD-5 override active). Both real, both need fix.
- **C-10 + C-11:** audit trail gap — Opus catches executor bypassing state_machine.transition(), Gemini catches state_machine.transition() bypassing write_audit_event(). Layered defect; both fixes needed.

## 2 · Master findings table

| Canonical | Title | Opus ID/Sev | Gemini ID/Sev | Domain | Status |
|---|---|---|---|---|---|
| **C-01** | Validation gate bypass via validated→approved (no gate check) | F-S10-01 / **Crit** | — | Workflow | Opus-only |
| **C-02** | TRANSITIONS missing constructed→approved edge breaks OD-5 override | — | F-S10-3 / **Crit** | Workflow | Gemini-only (related to C-01 — different angle) |
| **C-03** | CVaR improvement sign flip — advisor recommends WORST funds | — | F-S10-1 / **Math Crit / Inst High** | Math | Gemini-only |
| **C-04** | Empty ValidationDbContext disables 6 of 16 checks (banned/approved/blocks/NAV/TAA) | F-S10-02 / **Crit** | — | Workflow | Opus-only |
| **C-05** | Stressed CVaR shift / T renders it negligible | F-S10-04 / **Math Crit / Inst High** | F-S10-5 / **Math Crit / Inst High** | Math | Cross-confirmed exact |
| **C-06** | Historical stress imputes 0% for missing fund history (young funds = "GFC immune") | — | F-S10-2 / **Math Crit / Inst High** | Math | Gemini-only |
| **C-07** | Silent dropping of empty allocation block breaks strategic targets (60/40 → 100/0) | — | F-S10-6 / **Math High / Inst Crit** | Math + Workflow | Gemini-only |
| **C-08** | Mandate fit treats all client preferences as hard constraints | — | F-S10-9 / **Inst High** | Workflow | Gemini-only |
| **C-09** | Block-severity check exception silently demoted to warn (fail-open) | F-S10-03 / **Inst High** | — | Workflow | Opus-only |
| **C-10** | Construction executor mutates portfolio.state directly, bypasses state_machine.transition() | F-S10-06 / **Inst High** | — | Workflow / Audit | Opus-only |
| **C-11** | state_machine.transition() bypasses write_audit_event (Q92 invariant violation) | — | F-S10-4 / **Inst Crit** | Audit | Gemini-only (related to C-10 — different layer) |
| **C-12** | NAV staleness check verifies presence only — threshold_days unused | F-S10-07 / **Inst High** | F-S10-7 / **Inst High** | Workflow | Cross-confirmed exact |
| **C-13** | Same RNG seed for all funds defeats idiosyncratic dispersion | F-S10-05 / **Math High / Inst Med** | F-S10-8 / **Math High / Inst Med** | Math | Cross-confirmed exact |
| **C-14** | CVaR annualization uses sqrt(252) — heuristic but understates tail risk | F-S10-08 / **Math Med / Inst Low** | — | Math | Opus-only |

## 3 · Severity distribution

| Severity (worst-of) | Count | Findings |
|---|---|---|
| **Crit** | 8 | C-01, C-02, C-03, C-04, C-05, C-06, C-07, C-11 |
| **High** | 4 | C-08, C-09, C-10, C-12 |
| **Med** | 1 | C-13 |
| **Low** | 1 | C-14 |

**8 Crit findings** is the highest concentration in Wave 6 to date. Session 10 surface (model portfolio lifecycle + mandate fit + validation gate) is the bug-densest domain audited so far. Cross-cutting themes:

1. **Validation gate is structurally bypassable** (C-01, C-04, C-09): the gate exists conceptually but its enforcement has 3 independent escape paths.
2. **Stress / risk math has multiple correctness defects** (C-03, C-05, C-06, C-13): CVaR sign, scale, missing data handling, dispersion all wrong.
3. **Audit trail has layered gaps** (C-10, C-11): construction worker bypasses state machine; state machine bypasses centralized audit.
4. **Hard-vs-soft constraint discipline absent** (C-08, C-09): mandate fit treats preferences as hard; validation gate fails open on exceptions.

## 4 · Subsumption check vs Session 09 PRs

Q91-Q109 closed Session 09 covered: routes/workers integration, audit_events nullable org_id, fast_approve UUID cast, drift_check RLS+lock, screener idempotency, role gates, regime_fit pinned connection. **None of those overlap with Session 10's findings.** No subsumption-by-PR refutations expected.

## 5 · Specific judgments the jury must make

### 5.1 C-01 vs C-02 unification

Both relate to state machine. **Are they one architectural defect with two visible consequences, or two distinct bugs requiring separate fixes?**

The fixes are different:
- C-01 fix: add `validation.passed` check to `compute_allowed_actions` for `validated` state
- C-02 fix: add `"approved"` to `TRANSITIONS["constructed"]`

If C-02 is fixed alone, Gemini's OD-5 override workflow works but C-01's bypass remains. If C-01 is fixed alone, the live path is gated but OD-5 still crashes. **Both fixes are needed.** Jury should mark both CONFIRMED separately.

### 5.2 C-09 — fail-open: feature or bug?

Opus notes the code comment explicitly calls fail-open a feature ("never block on a check bug"). Institutional convention is fail-CLOSED for hard constraints. Jury must decide:
- **CONFIRMED** if fail-closed is correct for block-severity checks (institutional convention)
- **CONFIRMED-DOWNGRADED** if the documented fail-soft is acceptable as long as data quality is asserted upstream
- **REFUTED** if there's a separate guard that catches data quality issues before the gate runs

### 5.3 C-11 — audit_events vs PortfolioStateTransition

Gemini argues state_machine should call write_audit_event (Q92 invariant). Opus's "Checked invariants no finding" §I-Audit-Tenant-1 argues the absence of write_audit_event is OK because PortfolioStateTransition is the canonical audit table for state changes (RLS-scoped via OrganizationScopedMixin).

Jury must adjudicate the canonical audit policy:
- **CONFIRMED** if the institutional convention is that ALL mutations must go to audit_events (single unified feed)
- **REFUTED** if PortfolioStateTransition is a valid domain-specific audit table that doesn't need write_audit_event duplication
- The CLAUDE.md rules don't explicitly require write_audit_event for every mutation; the precedent across the codebase is mixed.

### 5.4 C-08 — mandate fit hard/soft separation

Gemini's proposed fix adds a `severity` field to `ConstraintResult`. This is a refactor, not a bug fix. Jury should:
- **CONFIRMED** if the current behavior (any miss → ineligible) is materially wrong by institutional convention
- **CONFIRMED-DOWNGRADED** if the issue is real but the fix scope is feature-development (separate ticket)
- Reference the institutional convention §3 in the original prompt: "hard constraints are dispositive — soft preferences cannot win"

### 5.5 C-14 — heuristic CVaR scaling

Opus already labels C-14 as Low because the function output carries `projected_cvar_is_heuristic=True`. Jury should likely:
- **CONFIRMED-DOWNGRADED** to confirm Low rating
- Document the constraint that any consumer reading `projected_cvar_is_heuristic=True` must treat the value as advisory only

### 5.6 Severity escalation candidates per institutional convention

The consolidation suggests the jury verify these severity ratings against §3 institutional convention:

| Canonical | Stage 1 rating | Possible escalation |
|---|---|---|
| C-01 (validation gate bypass live path) | Crit | Already Crit |
| C-02 (TRANSITIONS missing edge) | Crit | Already Crit |
| C-04 (empty context) | Crit | Already Crit |
| C-07 (block dropping breaks 60/40) | High Math + Crit Inst | Take worst-of: **Crit** |
| C-08 (mandate fit hard-soft fusion) | Inst High | Possibly **Crit** if institutional convention §3 applies (soft preference disqualifying = wrong direction) |
| C-09 (fail-open block-severity) | Inst High | Possibly **Crit** if data-quality guarantee not provided upstream |
| C-11 (audit gap) | Inst Crit (Gemini) | Already Crit per Gemini; Opus disagrees (sees as design choice) |

## 6 · Top 3 priorities (consolidated)

Both models agreed on the same architectural concern (state machine + validation gate); divergence is on which specific manifestation is the lead:

1. **C-01 + C-02** (jointly Crit) — validation gate bypassable via validate→approve AND OD-5 override crashes. Together they describe a state machine that is simultaneously too permissive (no gate check) and too restrictive (missing edge).
2. **C-04 + C-09** (jointly Crit + High) — when the gate runs, it runs blind (empty context) AND fails open on exceptions. Two compounding holes.
3. **C-03 + C-05 + C-06** (jointly Math Crit) — the risk metrics surfaced to IC are wrong in three distinct ways: CVaR sign flip on advisor recommendations, stressed CVaR diluted by T, historical stress treats young funds as 0%-volatility cash.

## 7 · Statistics

| Metric | Value |
|---|---|
| Total canonical findings | 14 |
| Crit | 8 |
| High | 4 |
| Med | 1 |
| Low | 1 |
| Cross-confirmed exact | 3 (C-05, C-12, C-13) |
| Cross-confirmed different angle | 2 pairs (C-01+C-02 state machine; C-10+C-11 audit) |
| Direct contradictions | 1 (C-11 — Gemini says Crit, Opus marked it OK in checked-invariants) |
| Opus-only | 5 |
| Gemini-only | 6 |
| Subsumed by in-flight PRs | 0 |

Session 10 has no Codex hotfix queue — Stage 4 will execute on remediation PRs after Stage 3.
