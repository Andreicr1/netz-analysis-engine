# Wave 6 — Session 10 Stage 2 Jury Megaprompt — GPT-5.5

**Status:** READY FOR DISPATCH
**Model:** GPT-5.5 (default jury per `feedback_jury_model_5_4_default.md` 2026-04-27)
**Date:** 2026-04-29
**Inputs (paste alongside this prompt):**
- `docs/audits/2026-04-29-wave6-session10-stage1-opus.md` (8 findings, Opus 4.6)
- `docs/audits/2026-04-29-wave6-session10-stage1-gemini.md` (9 findings, Gemini 3.1 Pro)
- `docs/audits/2026-04-29-wave6-session10-consolidated.md` (14 canonical, dedup + cross-coverage map)

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

1. Open one fresh GPT-5.5 session with maximum reasoning depth.
2. Paste the **entire `STAGE 2 JURY PROMPT BEGINS` block** below.
3. Paste the three input files in order, prefixed `=== FILE: <path> ===`.
4. The jury produces one verdict per canonical finding (CONFIRMED / CONFIRMED-ESCALATED / CONFIRMED-DOWNGRADED / REFUTED / REFUTED-FP-MECHANISM / GRAY) plus appendix.
5. Save output as `docs/audits/2026-04-29-wave6-session10-stage2-jury.md`.
6. Stage 3 (Opus 4.7 orchestration — me) consumes the verdict and produces remediation PR prompts.

---

## STAGE 2 JURY PROMPT BEGINS — copy from here

You are the **Stage 2 jury** for a Wave 6 institutional audit of the Netz Analysis Engine, an asset/wealth management SaaS B2B platform. Two discovery agents (Opus 4.6 with 1M context, Gemini 3.1 Pro) ran Stage 1 in parallel against the model portfolio lifecycle, validation gate, mandate fit, and stress scenarios layer of `backend/vertical_engines/wealth/`. Your job is to **adjudicate** their findings.

You are **not** a third discovery agent — you do not produce new findings of your own. You **judge** the existing 14 canonical findings using line-level evidence, institutional convention, and the protocols cited below.

The default jury model in this project is GPT-5.5 (calibrated 2026-04-27). N=5 consecutive 100% accuracy sessions for GPT-5.5. **Your verdicts must be Crit-tier accurate.**

---

## 1 · Inputs

You have three files in your context (pasted by the dispatcher):

1. **Opus 4.6 Stage 1 output** — 8 findings with full template + extensive "Checked invariants" section (12 invariants verified).
2. **Gemini 3.1 Pro Stage 1 output** — 9 findings with full template + 3 verified invariants.
3. **Consolidation document** — 14 canonical findings (C-01 through C-14) deduplicated across the two discoveries, with cross-coverage map, severity escalation candidates, and 6 specific judgments highlighted.

The canonical IDs (C-01 through C-14) are **your output keys**. Use them.

---

## 2 · Verdict vocabulary

For each canonical finding produce **exactly one of**:

| Verdict | Meaning |
|---|---|
| **CONFIRMED** | Bug exists; severity and remediation as stated are correct. |
| **CONFIRMED-ESCALATED** | Bug exists; severity should be HIGHER than stated. |
| **CONFIRMED-DOWNGRADED** | Bug exists; severity should be LOWER than stated. |
| **REFUTED** | Bug does not exist as described, OR is already fixed in an in-flight PR. |
| **REFUTED-FP-MECHANISM** | Bug claim cites a function/library that does not behave as described. |
| **GRAY** | Insufficient evidence to confirm or refute. |

Produce a verdict for **all 14** canonical findings. Do not skip any.

---

## 3 · Institutional convention (use this for ESCALATED / DOWNGRADED decisions)

These are the institutional severity defaults for B2B wealth-management SaaS.

### 3.1 Always Crit
- **Approval bypass** of hard constraint validation (regulatory or mandate)
- **Math error producing wrong recommendation** (sign flip in scoring, ranking by inverted criteria)
- **Silent loss of audit trail** at the lifecycle level
- **Strategic asset allocation silently overridden** (e.g., 60/40 target executes as 100/0)
- **Production endpoint that crashes on every call** of a critical workflow
- **Missing data treated as zero in stress scenarios** (young funds = "GFC immune")

### 3.2 Always at least High
- **Validation gate runs blind** (no context for half its checks)
- **Stress / risk magnitude wrong by 10x+** (e.g., diluted by sample length)
- **Hard constraint discipline blurred with soft preference**
- **Lifecycle audit trail incomplete** (e.g., construction transition has no audit row)

### 3.3 At least Med
- **Idiosyncratic dispersion broken** (same RNG seed, identical residuals)
- **Track record visualization quirks** (paused interval display)

### 3.4 At most Low
- **Heuristic functions explicitly labeled** with degraded marker, advisory-only consumers

---

## 4 · Anti-patterns the jury must catch

| Pattern | Description | Jury action |
|---|---|---|
| **Claimed-mechanism-doesn't-exist** | Finding cites library function behavior from name alone. | Verify by reading implementation. If wrong, **REFUTED-FP-MECHANISM**. |
| **Subsumption-forward** | Finding F-N subsumed by adjacent higher-tier fix F-(N-1). | Prefer the higher-tier; mark subsumed **REFUTED — subsumed by C-X**. |
| **Subsumption-by-PR** | Finding addressed by an in-flight PR (Q91-Q109 from Session 09). | The consolidation §4 says no overlap — but verify yourself. If subsumed, **REFUTED — fixed in PR #N**. |
| **Severity inflation** | Float-precision drift rated Crit when no decision actually flips. | **CONFIRMED-DOWNGRADED**. |
| **Crash-on-paper but unreachable** | Code path guarded by an outer check the agent missed. | **REFUTED-FP-MECHANISM** if truly unreachable. |
| **Out-of-domain math objection** | Deep CLARABEL / Black-Litterman issues belong to Sessions 04/05. | Mark as Handoff in your reasoning. |

---

## 5 · Output format

Produce a single markdown document with the structure below.

```markdown
# Wave 6 — Session 10 Stage 2 Jury Output

**Model:** GPT-5.5
**Date:** 2026-04-29
**Findings adjudicated:** 14

## Summary table

| Canonical | Title (truncated) | Verdict | Final severity | Notes |
|---|---|---|---|---|
| C-01 | Validation gate bypass... | CONFIRMED | Crit | ... |

## Per-finding adjudication

### C-01 — Validation gate bypass via validated→approved (no gate check)

**Verdict:** CONFIRMED | CONFIRMED-ESCALATED | CONFIRMED-DOWNGRADED | REFUTED | REFUTED-FP-MECHANISM | GRAY
**Final severity:** Crit | High | Med | Low | N/A
**Reasoning:** [3-6 sentences. Cite actual code, institutional convention applied, FP pattern check.]
**Override of Stage 1?** [No, OR specifically what changed and why.]
**Test still required?** [Yes, OR No because subsumed/already-tested.]
**Confidence:** High | Medium | Low

[... repeat for C-02 through C-14 ...]

## Cross-cutting observations

[1-3 paragraphs only if patterns emerge across multiple findings.]

## Appendix — unsolicited hypotheses

[Optional. Maximum 3 items. Direct evidence required (line numbers + code snippets). The jury's role is adjudication, not discovery.]
```

---

## 6 · Specific judgments the jury must make

### 6.1 C-01 + C-02 — state machine: 1 defect or 2?

The consolidation §5.1 frames the question. Brief: are these the same architectural bug needing one fix, or two separate bugs each needing its own fix?

- C-01 fix: add gate check on `validated` state's `compute_allowed_actions`
- C-02 fix: add `"approved"` to `TRANSITIONS["constructed"]`

If only one fix lands, the OTHER bypass remains. **Both fixes needed**. Mark both CONFIRMED separately, but note the architectural relationship in your reasoning.

### 6.2 C-09 — fail-open block-severity: feature or bug?

Opus's note: code comment calls fail-open a feature. Institutional convention §3.2 says hard constraints fail closed.

Decide:
- **CONFIRMED** if institutional convention applies (hard checks fail closed; data-quality issues should not produce silent activation)
- **CONFIRMED-DOWNGRADED** if the documented fail-soft is acceptable when paired with upstream data-quality guarantees
- **REFUTED** if you find an explicit upstream data-quality guard that makes block-check failures impossible

Cite the §3 reasoning explicitly in your verdict.

### 6.3 C-11 — write_audit_event vs PortfolioStateTransition

Gemini argues state_machine should call write_audit_event for Q92 compliance. Opus argues PortfolioStateTransition is the canonical domain audit table.

Re-read both stage outputs. Decide:
- **CONFIRMED** if institutional convention requires single unified audit feed (`audit_events` is canonical for ALL mutations)
- **REFUTED** if PortfolioStateTransition is a valid domain-specific audit table replacing the unified feed for state changes
- Reference CLAUDE.md and Session 09 Q92 verdict (which created the `allow_global=False` flag for write_audit_event). Q92 was about WHEN write_audit_event is required, not whether all mutations need it.

### 6.4 C-07 severity — block dropping

Gemini rated Math High + Inst Crit. Take worst-of → Crit. Verify the institutional impact: if a 60/40 portfolio silently runs 100/0, that is a Crit institutional defect. Mark **CONFIRMED** at Crit unless you find a counter-argument.

### 6.5 C-08 severity — mandate fit hard/soft

Gemini rated Inst High. Per institutional convention §3.2, "hard constraint discipline blurred with soft preference" is at least High. **CONFIRMED** at High likely correct, but consider escalation if the impact in practice (clients receiving incorrect mandate-fit decisions) is severe.

### 6.6 C-14 — heuristic CVaR

Already labeled Low by Opus due to `projected_cvar_is_heuristic=True` flag. Consumers are warned. **CONFIRMED at Low** is likely correct unless you find a consumer that ignores the heuristic flag.

---

## 7 · What you MUST NOT do

- Do not produce new findings as "main findings" — restrict to appendix with direct evidence only.
- Do not adjudicate findings without citing line numbers in your reasoning.
- Do not refute with "I don't see the bug" — refute with positive evidence.
- Do not skip findings — produce a verdict for all 14.
- Do not invent verdict categories.
- Do not propose architectural rewrites; confine to bug-level adjudication.

---

## 8 · Final reminder

Session 10 surfaces 8 Crit findings (vs Session 09's 5). The model portfolio lifecycle / validation gate / mandate fit layer has higher bug density than any prior Wave 6 session. Three findings (C-03 + C-05 + C-06) describe wrong risk math reaching IC; two findings (C-01 + C-02) describe simultaneously permissive AND restrictive state machine; two (C-10 + C-11) describe layered audit gaps. Your verdicts determine which Crit findings ship to remediation PRs and which get downgraded.

When in doubt, prefer reporting an investigation question (with `Confidence: Low`) over silence. The orchestrator will adjudicate Stage 3.

When you finish, save your output to `docs/audits/2026-04-29-wave6-session10-stage2-jury.md`.

## STAGE 2 JURY PROMPT ENDS — copy until here
