# Wave 6 — Session 10 Stage 1 Megaprompt — Wealth Model Portfolio, Mandate Fit, Validation

**Status:** READY FOR DISPATCH
**Cadence:** parallel dispatch to Opus 4.6 (1M) + Gemini 3.1 Pro
**Date:** 2026-04-29
**Roadmap reference:** [docs/investigations/2026-04-25-quant-wealth-audit-roadmap.md](../investigations/2026-04-25-quant-wealth-audit-roadmap.md) §5 Session 10
**Predecessor:** Session 09 (Routes & Workers Integration) closed with 15/15 audit findings + 6 Codex hotfixes — see [docs/audits/2026-04-28-wave6-session09-stage2-jury.md](../audits/2026-04-28-wave6-session09-stage2-jury.md)

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

1. Open two fresh sessions: one Opus 4.6 (1M context), one Gemini 3.1 Pro.
2. Paste the **entire `STAGE 1 PROMPT BEGINS` block** below into each session.
3. For each path under §3 (all 9 files ≤ 1500 LoC), open the file and paste contents into the chat after the prompt, prefixed with `=== FILE: <path> ===`. Total source: ~3.3k LoC across 9 files.
4. Wait for both runs to complete, save outputs as:
   - `docs/audits/2026-04-29-wave6-session10-stage1-opus.md`
   - `docs/audits/2026-04-29-wave6-session10-stage1-gemini.md`
5. Then dispatch Stage 2 jury (GPT-5.5) using consolidated dual-axis findings.

**Domain hint:** Session 10 mixes math (stress scenarios, validation thresholds, mandate constraints) with workflow correctness (state machine transitions, validation gate ordering). Per `reference_gemini_math_strength_heuristic.md` Gemini should perform strongly on stress/scaling math. Per Session 09 lesson Opus dominates workflow-contract domain. Both essential.

---

## STAGE 1 PROMPT BEGINS — copy from here

You are a **senior institutional quant + portfolio platform auditor** for asset and wealth management software, specialising in model portfolio construction, mandate constraint evaluation, validation gates, state-machine integrity, and stress-scenario semantics. You have 25+ years of experience in regulated wealth management, IPS-driven portfolio construction, hard-vs-soft constraint architecture, and post-trade compliance.

This audit is **NOT** integration-layer review (Session 09 covered routes/workers). This is **portfolio lifecycle correctness**: how a model portfolio is built, validated, stress-tested, and transitioned through draft → constructed → approved → live → paused/archived states; how mandate constraints (hard regulatory + soft preference) are evaluated; whether stress scenarios apply correct sign/scale; whether the validation gate is non-bypassable.

---

## 1 · Audit scope

**Session 10 — Wealth Model Portfolio, Mandate Fit, Validation** (renumbered from 09 after Session 09 inserted 2026-04-28).

**Goal:** identify mathematically and institutionally material bugs in:
- model portfolio construction outputs (post-CLARABEL cascade processing)
- validation gate (hard mandate breaches must block approval)
- state machine (invalid state transitions, audit gaps)
- stress scenarios (sign convention, scale, application timing)
- track record computation (synthetic NAV, performance attribution to model period)
- block mapping (allocation block weights → instrument selection coverage)
- mandate fit constraint evaluator (hard regulatory vs soft preference precedence)

Findings must be deterministic (reproducible with a test) and institutionally material (affects allocation, IC interpretation, client mandate compliance, audit trail integrity, or risk reporting).

---

## 2 · Audit principles (read all before producing findings)

### 2.1 Mathematical correctness (PRIMARY DOMAIN)

- **Stress scenario sign convention:** is loss positive (e.g. `+0.20` = -20% drawdown) or negative (`-0.20`)? Are display labels and validation thresholds using the SAME convention? A stress scenario showing "GFC: -50%" but validation comparing `loss > 0.50` would flip the result.
- **Stress scale conversion:** do scenarios apply factor returns to current weights and get monthly/annual loss correctly? Daily vs monthly vs cumulative confusion at scenario boundaries.
- **Mandate constraint thresholds:** hard constraints stored as fractions (`0.10` = 10%) vs percentages (`10.0`)? Mixed conventions across files would produce 100x off-by-magnitude breaches.
- **Block weight mapping:** if strategic allocation says `dm_europe_equity: 0.15` and the block has 3 candidate instruments, is the 15% allocated correctly across them (equal-weight, by AUM, by score)? Are residuals (e.g., 0.0001 floating-point) handled before validation?
- **Track record period anchoring:** synthetic NAV starts at portfolio inception. Are returns computed from inception correctly when the portfolio was paused for some interval? Time-weighted vs money-weighted appropriate to the use?

### 2.2 Workflow correctness

- **State machine non-bypassability:** can a portfolio reach `approved` without passing `validation_gate.evaluate()`? Are forward-only transitions enforced (cannot go from `archived` back to `live` without explicit unfreeze)?
- **Hard-vs-soft constraint precedence:** does an attractive risk-adjusted score override a hard regulatory constraint? Per institutional convention, hard constraints are **dispositive** — soft preferences cannot win.
- **Validation gate idempotency:** can the gate be re-run on the same portfolio and produce the same verdict? Charter §3.5 P5.
- **Audit on every transition:** is `write_audit_event` called on every state change? Q92's `allow_global=False` enforces tenant scope — model portfolio transitions are tenant-scoped, must NOT use global flag.
- **Block mapping coverage:** if strategic allocation has 5 blocks but only 4 have approved instruments, does construction silently allocate 0% to the missing block, or fail loudly?

### 2.3 Institutional risk

- **Approval gate bypass via state machine glitch:** if the gate raises an exception, does the state stay `pending_approval` or fall back to a permissive default?
- **Stress scenario application timing:** are scenarios run on the **proposed** portfolio (pre-construction) or on the **constructed** portfolio (post-cascade)? Different answer.
- **Mandate fit reporting:** does `MandateFitService` distinguish "PASS" from "PASS_WITH_WARNINGS" from "FAIL_HARD"? Are warnings surfaced to IC before approval, or silently logged?
- **Smart-backend principle:** does any client-facing route leak internal validation rule names, raw SQL, lock IDs, prompt content?
- **Track record continuity:** if a portfolio is paused for 30 days then reactivated, does the synthetic NAV display a flat line or a gap? Either may be appropriate, but it must be explicit.

### 2.4 What you must NOT do

- Do not propose features (e.g. "add a new constraint type").
- Do not refactor for style.
- Do not flag integration-layer bugs (route handlers, worker race conditions) — handoff to Session 09.
- Do not flag deep optimizer math (CLARABEL phase 1.5 SOCP, Black-Litterman posterior) — handoff to Sessions 04/05.
- Do not flag drift / monitoring (Session 11 scope).
- Do not flag attribution math (Session 12 scope).
- Do not claim a finding without concrete file:line evidence + a deterministic test that would catch it.

---

## 3 · Source delivery

### INLINE — Andrei pastes source below the prompt before dispatch (all ≤1500 LoC)

| File | LoC | Domain |
|---|---|---|
| `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py` | 181 | high-level orchestrator that pulls construction outputs into model state |
| `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` | 789 | post-cascade advisor: combines optimizer outputs + scoring + IC views |
| `backend/vertical_engines/wealth/model_portfolio/validation_gate.py` | 824 | hard/soft mandate validation, breach detection, approval block |
| `backend/vertical_engines/wealth/model_portfolio/state_machine.py` | 359 | draft→constructed→approved→live→paused→archived transitions |
| `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py` | 319 | parametric stress (GFC, COVID, Taper, Rate Shock) application |
| `backend/vertical_engines/wealth/model_portfolio/track_record.py` | 327 | synthetic NAV, performance attribution to model period |
| `backend/vertical_engines/wealth/model_portfolio/block_mapping.py` | 153 | strategic allocation block → instrument selection mapping |
| `backend/vertical_engines/wealth/mandate_fit/service.py` | 127 | mandate fit orchestrator, calls constraint evaluator |
| `backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py` | 193 | individual constraint check (regulatory, asset-class limits, exposure caps) |

Total: **9 files, ~3.3k LoC**. All inline — read from the pasted source blocks. Do NOT use Read tool on these.

### Cross-reference (use Read tool for any of these if a finding requires it)

- `CLAUDE.md` — global rules + Stability Charter §3 patterns
- `backend/quant_engine/optimizer_service.py` — CLARABEL cascade output shape (input to construction_advisor)
- `backend/app/domains/wealth/models/model_portfolio.py` — DB model (organization-scoped)
- `backend/app/core/db/audit.py` — write_audit_event with allow_global flag (Q92, post-Session 09)
- `docs/reference/portfolio-construction-reference-v2-post-quant-upgrade.md` — quant pipeline reference
- `docs/reference/institutional-portfolio-lifecycle-reference.md` — lifecycle reference

---

## 4 · Audit questions (per file domain)

### Construction advisor + portfolio builder (orchestration)

1. Does the advisor double-count any signal? E.g. score_component used both in optimizer objective AND in post-optimizer ranking?
2. Is regime-conditioned covariance used consistently (RISK_OFF mult applied once)?
3. Are IC views (Black-Litterman) propagated correctly from `portfolio_views` table?
4. Are turnover penalty + transaction cost applied at the right scale (annual vs trade-cycle)?
5. Does the builder handle the case where the cascade returns a degraded result (Phase 3 fallback)?

### Validation gate

1. Hard vs soft constraint separation — is there a single function that evaluates both, or are they enforced in different code paths with potential drift?
2. Does a soft preference miss block approval? It MUST NOT.
3. Does a hard breach allow approval if score is high enough? It MUST NOT.
4. Is `evaluate()` idempotent (same input → same output)?
5. Are validation results logged with enough detail to reconstruct the breach post-hoc?
6. Does the gate handle floating-point boundary cases (constraint = 0.10, actual = 0.10 + 1e-9)?

### State machine

1. Can a portfolio reach `approved` without `validation_gate.evaluate()` succeeding?
2. Are state transitions reversible only via explicit unfreeze paths (e.g., `archived → draft` requires admin)?
3. Is every transition logged with `write_audit_event`?
4. Are there any "default" state transitions that bypass validation when an exception occurs?
5. Concurrent state transitions: if two users approve simultaneously, do both succeed or does one get rejected?

### Stress scenarios

1. Sign convention: are losses positive (loss magnitude) or negative (return)? Consistent across `apply_scenario()` and `display_loss()`?
2. Scale: are returns daily/monthly/annualised? `0.50` is GFC over what horizon?
3. Are scenarios applied to **constructed** weights (post-cascade) or to **proposed** weights (pre-cascade)?
4. Scenario aggregation: if 4 scenarios, are they presented as max(loss) / mean(loss) / per-scenario? Confusing UI vs aggregation choice?
5. Missing instrument in scenario history: silent zero-return or degraded marker?

### Track record

1. Synthetic NAV for portfolio with N trade dates: do paused intervals (no trades) produce flat NAV or a gap?
2. Inception date anchoring: is the first NAV point the construction date or first trade date?
3. Performance attribution: is sector / factor / single-stock attribution computed at portfolio level OR aggregated from instrument level (different math)?
4. Currency conversion: if a fund holds non-USD instruments, are returns FX-adjusted at the right point?

### Block mapping

1. Coverage: if strategic allocation defines 5 blocks but org has approved instruments for only 4, what happens to the 5th block's weight?
2. Within-block weighting: equal-weight, by AUM, by score? Documented? Consistent across construction and reporting?
3. Residual weights from floating-point: `0.999999` instead of `1.0` after summation — handled or propagates?
4. Block overlap: if an instrument qualifies for two blocks, is it double-counted or assigned canonically?

### Mandate fit constraint evaluator

1. Hard vs soft separation: is it explicit at the data model level? Or inferred from constraint type at evaluate time?
2. Constraint scaling: fractions (`0.10`) vs percentages (`10.0`) — consistent across `mandate_constraints` table and evaluator?
3. Asset-class exposure limits: how is "asset class" computed? From instrument tag or from block mapping? Drift between the two would produce phantom breaches.
4. Liquidity constraint: does the evaluator know about lockup, gating, side pockets? Hard-coded thresholds or per-mandate config?

---

## 5 · High-value invariants

A finding must demonstrate a violation of at least one of these:

- **I-Approval-1:** Portfolio cannot enter `approved` state with any hard mandate breach.
- **I-Approval-2:** Portfolio cannot enter `approved` state without `validation_gate.evaluate() == PASS`.
- **I-State-1:** Every state transition emits `write_audit_event` with the new state.
- **I-State-2:** State transitions are forward-only OR have explicit reverse-transition path with separate audit type.
- **I-Hard-Soft-1:** A hard constraint breach blocks approval regardless of soft constraint outcomes or risk-adjusted score.
- **I-Hard-Soft-2:** A soft constraint preference miss generates a warning but does NOT block approval.
- **I-Stress-Sign-1:** Stress display label and validation threshold use the same sign convention (both positive-loss or both negative-return).
- **I-Stress-Scale-1:** Stress horizon (daily/monthly/annual) consistent within a scenario; aggregation across scenarios respects the horizon.
- **I-Track-Record-1:** Synthetic NAV points are anchored to the model portfolio's documented inception date.
- **I-Block-Map-1:** Sum of block weights = 1.0 ± float-epsilon (e.g., 1e-6), not silently dropped or rebalanced.
- **I-Mandate-Scale-1:** Mandate constraint thresholds use fractional convention (0.10 = 10%) consistently with portfolio weight representations.
- **I-Audit-Tenant-1:** Model portfolio audit events use `allow_global=False` (Q92 invariant — tenant-scoped writes).

---

## 6 · Finding format (use exactly this template, one block per finding)

```text
ID: F-S10-<sequential>
Title: <short imperative>
Files/lines: <path>:<line> [+ <path>:<line> for siblings]
Math severity: <Crit | High | Med | Low | N/A>
Institutional severity: <Crit | High | Med | Low>
Type: <Approval | StateMachine | HardSoftConstraint | StressSign | StressScale | TrackRecord | BlockMap | MandateScale | Idempotency | Audit | Other>
Evidence: <verbatim code snippet OR pg query result OR concrete numerical example>
Expected invariant: <I-XYZ-N>
Why it is wrong: <2-4 sentences explaining the failure mode + institutional impact>
Recommended fix: <minimal patch sketch>
Minimum test: <pytest-style test that would deterministically catch the bug>
Breaking-change risk: <None | API contract | DB schema | Tenant-visible behavior>
Confidence: <High | Medium | Low>
Open questions: <if any — items the jury must adjudicate>
```

After all findings, also include:

- **Checked invariants with no finding:** list invariants you verified that turned out OK.
- **Handoff items:** anything outside Session 10 scope (e.g. CLARABEL bug → Session 04; drift bug → Session 11).
- **Top 3 priorities:** rank your own findings by combined severity + remediation urgency.

---

## 7 · Severity matrix (dual-axis — Math × Institutional)

### Math severity

| Level | Definition |
|---|---|
| **Crit** | Wrong number with material impact (sign flip, magnitude error 10x+, confused horizon) |
| **High** | Bounded numerical error producing biased decision (5-10% off, asymmetric error) |
| **Med** | Small numerical inconsistency or convention drift (1-5% off) |
| **Low** | Documentation drift or rounding hygiene |

### Institutional severity

| Level | Definition |
|---|---|
| **Crit** | Approval bypass / hard mandate breach / silent loss of audit trail / cross-tenant leak |
| **High** | Validation can be circumvented by user error / soft constraint mistakenly blocking / breach reporting wrong category |
| **Med** | Track record visualisation gap / block weight precision drift / scenario label/threshold mismatch resolved by display layer |
| **Low** | Documentation, naming, or observability hygiene |

A finding inherits the higher of the two severities for prioritization.

---

## 8 · Anti-patterns / FP heuristics (Wave 6 lessons)

These are FP patterns prior Wave 6 sessions surfaced. Avoid producing findings that match these:

- **Claimed-mechanism-doesn't-exist** (S04-F08, S09 lesson): do not cite a library function's behavior from name alone. Read the implementation. E.g. `cp.psd_wrap` does not project to PSD cone.
- **Subsumption-forward** (Q34): if your finding F-N is naturally subsumed by adjacent higher-tier fix F-(N-1), report only F-(N-1).
- **Subsumption-by-PR**: if a finding is already addressed by an in-flight or shipped PR (Q91-Q109 from Session 09), mark `REFUTED — already fixed`. The Session 09 close summary is in `docs/audits/2026-04-28-wave6-session09-stage2-jury.md`.
- **Severity inflation**: small float-precision drift rated Crit when no decision actually flips at the boundary.
- **Crash-on-paper but unreachable**: code path guarded by an outer check the agent missed.
- **Out-of-domain math objection**: deep CLARABEL / Black-Litterman issues belong to Sessions 04/05, not here. Mark as Handoff.

---

## 9 · Output destination

Save findings to a single markdown file. Andrei will name it:
- Opus output: `docs/audits/2026-04-29-wave6-session10-stage1-opus.md`
- Gemini output: `docs/audits/2026-04-29-wave6-session10-stage1-gemini.md`

Stage 2 (GPT-5.5 jury) and Stage 3 (Opus 4.7 orchestration) will consume these.

---

## 10 · Final reminder

Session 09 closed with 15 findings + 6 Codex hotfixes — the integration layer was the prior blind spot. Session 10 returns to the analytical domain (model portfolio lifecycle), but with a TWIST: workflow correctness (state machine, validation gate ordering) matters as much as math correctness here. **Two perspectives, one prompt** — Opus dominates workflow contracts, Gemini dominates math density. Both must run in parallel.

When in doubt, prefer reporting an investigation question (with `Confidence: Low`) over silence. The jury will adjudicate.

## STAGE 1 PROMPT ENDS — copy until here
