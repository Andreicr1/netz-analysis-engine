# Wave 6 — Session 09 Stage 2 Jury Megaprompt — GPT-5.5

**Status:** READY FOR DISPATCH
**Model:** GPT-5.5 (default jury per `feedback_jury_model_5_4_default.md` 2026-04-27)
**Date:** 2026-04-28
**Inputs (paste alongside this prompt):**
- `docs/audits/2026-04-28-wave6-session09-stage1-opus.md` (14 findings, Opus 4.6)
- `docs/audits/2026-04-28-wave6-session09-stage1-gemini.md` (5 findings, Gemini 3.1 Pro)
- `docs/audits/2026-04-28-wave6-session09-consolidated.md` (15 canonical, dedup + conflicts highlighted)

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

1. Open one fresh GPT-5.5 session with maximum reasoning depth.
2. Paste the **entire `STAGE 2 JURY PROMPT BEGINS` block** below.
3. Paste the three input files in order, prefixed `=== FILE: <path> ===`.
4. The jury will produce one verdict per canonical finding (REFUTED / DOWNGRADED / CONFIRMED) plus appendix.
5. Save output as `docs/audits/2026-04-28-wave6-session09-stage2-jury.md`.
6. Stage 3 (Opus 4.7 orchestration — me) consumes the jury verdict and produces remediation PR prompts.

---

## STAGE 2 JURY PROMPT BEGINS — copy from here

You are the **Stage 2 jury** for a Wave 6 institutional audit of the Netz Analysis Engine, an asset/wealth management SaaS B2B platform. Two discovery agents (Opus 4.6 with 1M context, Gemini 3.1 Pro) ran Stage 1 in parallel against the route + worker integration layer of `backend/app/domains/wealth/`. Your job is to **adjudicate** their findings.

You are **not** a third discovery agent — you do not produce new findings of your own. You **judge** the existing 15 canonical findings using line-level evidence, institutional convention, and the protocols cited below.

The default jury model in this project is GPT-5.5 (calibrated 2026-04-27 after Session 05 dual-jury run showed 5.5 = 100% Stage 3 alignment vs 5.4 = 78.6%). The cost premium is justified by Crit-tier accuracy. **Your verdicts must be Crit-tier accurate.**

---

## 1 · Inputs

You have three files in your context (pasted by the dispatcher):

1. **Opus 4.6 Stage 1 output** — 14 findings with full template (ID, title, files/lines, evidence, fix, test, breaking-change risk, confidence).
2. **Gemini 3.1 Pro Stage 1 output** — 5 findings with full template + "Checked invariants" section.
3. **Consolidation document** — 15 canonical findings (C-01 through C-15) deduplicated across the two discoveries, with cross-coverage map, subsumption-by-PR notes, and direct conflicts highlighted.

The canonical IDs (C-01 through C-15) are **your output keys**. Use them.

---

## 2 · Verdict vocabulary

For each canonical finding you must produce **exactly one of**:

| Verdict | Meaning | When to use |
|---|---|---|
| **CONFIRMED** | Bug exists; both severity and remediation as stated are correct. | Code/evidence supports the finding; institutional severity rating is appropriate. |
| **CONFIRMED-ESCALATED** | Bug exists; severity should be HIGHER than stated. | E.g. multi-tenant leak rated "High" should be "Crit" per institutional convention. |
| **CONFIRMED-DOWNGRADED** | Bug exists; severity should be LOWER than stated. | E.g. annotation lie rated "Crit" when no runtime crash actually occurs (footgun only). |
| **REFUTED** | Bug does not exist as described, OR is already fixed in an in-flight PR. | E.g. C-09 is REFUTED because PR-Q92 already implements `allow_global=True` flag. |
| **REFUTED-FP-MECHANISM** | Bug claim cites a function/library that does not behave as described. | The S04-F08 lesson: `cp.psd_wrap` does not project to PSD cone. Match this pattern carefully. |
| **GRAY** | Insufficient evidence to confirm or refute; needs deeper code reading or runtime test. | Only when both Stage 1 agents disagreed AND the source you can read does not settle it. |

You must produce a verdict for **all 15** canonical findings. Do not skip any.

---

## 3 · Institutional convention (use this for ESCALATED / DOWNGRADED decisions)

These are the institutional severity defaults for B2B wealth-management SaaS. If a finding violates one of these, **CONFIRMED-ESCALATED** is the default unless the discovery agent provided a specific reason to discount.

### 3.1 Always Crit
- **Multi-tenant data leak** (RLS bypass, cross-org read/write) — even if hypothetical
- **Privilege escalation** on mutating routes (investor-role mutates IC-level state)
- **Production endpoint that crashes on every call** (not just edge cases)
- **Silent loss of audit trail** (mutation without audit row, or audit row visible to wrong tenant)
- **Permanent state corruption** (cannot be remediated without manual SQL)

### 3.2 Always at least High
- **Idempotency violation** that breaks a documented retry contract
- **Unbounded external API spend** by lower-privilege users
- **Worker race that can deadlock** the entire pipeline
- **Lock leak** that requires DB restart to clear

### 3.3 At least Med
- **Strict-params silent ignore** on user-facing GET routes (UX + observability)
- **Annotation lie** that has no current runtime impact (footgun, not bug today)

### 3.4 At most Low
- **Style nits with zero correctness impact**
- **Documentation drift on internal-only artifacts**

---

## 4 · Anti-patterns the jury must catch (Wave 6 false-positive heuristics)

These are FP patterns prior Wave 6 sessions surfaced. Mark findings matching them as **REFUTED-FP-MECHANISM** if applicable:

| Pattern | Description | Jury action |
|---|---|---|
| **Claimed-mechanism-doesn't-exist** (S04-F08) | Finding cites library function behavior from name alone, without reading implementation. | If you cannot verify the cited mechanism, mark **GRAY** with explicit ask for code read. If you can verify it doesn't exist, **REFUTED-FP-MECHANISM**. |
| **Subsumption-forward** (Q34) | Finding F-N is naturally subsumed by adjacent higher-tier fix F-(N-1). | Prefer the higher-tier finding; mark the subsumed one **REFUTED — subsumed by C-X**. |
| **Subsumption-by-PR** | Finding is already addressed by an in-flight PR (Q91/Q92/Q93). | **REFUTED — already fixed in PR #N**. The consolidation §3 calls these out explicitly. |
| **Subsumption-reverse-test-gap** (S04 Q41) | Finding adds a stricter check; existing tests for prior PRs need updating; flag as test-gap, not as new fix. | If applicable, mark CONFIRMED but add note about test gap. |
| **Severity inflation** | Annotation lie rated Crit when no actual crash occurs at any reachable site. | **CONFIRMED-DOWNGRADED**. |
| **Crash-on-paper but unreachable** | Finding cites a code path that is dead or guarded by an outer check the agent missed. | If the path is truly unreachable, **REFUTED-FP-MECHANISM**. Otherwise CONFIRMED. |

---

## 5 · Output format

Produce a single markdown document with the structure below. **Do not deviate.**

```markdown
# Wave 6 — Session 09 Stage 2 Jury Output

**Model:** GPT-5.5
**Date:** 2026-04-28
**Findings adjudicated:** 15

## Summary table

| Canonical | Title (truncated) | Verdict | Final severity | Notes |
|---|---|---|---|---|
| C-01 | universe_sync ... | CONFIRMED | Crit | ... |
| ... | ... | ... | ... | ... |

## Per-finding adjudication

### C-01 — universe_sync ON CONFLICT omits is_active

**Verdict:** CONFIRMED | CONFIRMED-ESCALATED | CONFIRMED-DOWNGRADED | REFUTED | REFUTED-FP-MECHANISM | GRAY
**Final severity:** Crit | High | Med | Low | N/A
**Reasoning:** [3-6 sentences. Cite the actual code, the institutional convention applied, and any FP pattern check.]
**Override of Stage 1?** [No, OR specifically what changed and why.]
**Test still required?** [Yes, OR No because subsumed/already-tested.]
**Confidence:** High | Medium | Low

[... repeat for C-02 through C-15 ...]

## Cross-cutting observations

[1-3 paragraphs, only if patterns emerge across multiple findings — e.g. "5 findings share the missing-RLS-context pattern", "3 findings are subsumed by Q91/Q92/Q93 but partial scope remains".]

## Appendix — unsolicited hypotheses

[**Optional. Maximum 3 items.** If you noticed a pattern in the consolidation that neither Stage 1 agent surfaced AND you have direct evidence (line numbers, code snippets), document it here. Each item must include:
- ID: A-S09-<n>
- Title
- Files/lines
- Severity (institutional convention)
- Evidence (verbatim or near-verbatim code)
- Why it was missed by Stage 1
- Required deliverable (test or fix sketch)

If you have less than direct evidence, do NOT include speculative items here. The jury's role is adjudication, not discovery — unsolicited hypotheses are a controlled extension, not a license to fish.]
```

---

## 6 · Specific judgments the jury must make

### 6.1 C-02 severity tie-break

Opus rated Crit, Gemini rated High. The bug: `trigger_screening` raises `IntegrityError` on re-run for the same `(org, instrument)` pair. Apply §3.1 institutional convention: this is an idempotency violation that breaks the documented retry contract (Stability Charter §3.5 P5 Idempotent). Decide:

- **Crit** if you find the route is in the documented core wealth workflow with auto-retry expected from clients.
- **High** if the route is administrator-only and clients accept manual retry.

Cite which one in your reasoning.

### 6.2 C-07 direct contradiction

Opus says `approve_dd_report` creates `UniverseApproval` without flipping prior `is_current=True` (bug). Gemini explicitly verified the opposite ("ratificando a saúde das ramificações irmãs"). **Read `backend/app/domains/wealth/routes/dd_reports.py:572-583` line by line.** Either:

- **CONFIRMED** Opus's finding (Gemini's verification was wrong) — explain what Gemini missed.
- **REFUTED** Opus's finding (Gemini was right) — explain what code Opus missed.

This is the single most important judgment in this session — both Stage 1 agents cannot be right.

### 6.3 C-09 subsumption by PR-Q92

The consolidation §3 notes that PR-Q92 (#392) already implements the exact `allow_global=False` flag and `ValueError` raise that C-09 recommends. Mark **REFUTED — already fixed in PR #392** unless you find evidence the fix is incomplete.

### 6.4 C-01 / C-03 partial subsumption

PR-Q91 (#391) reactivated UCITS one-time but did NOT patch the upsert race. PR-Q93 (#393) fixed `universe.py:689` only. The findings remain CONFIRMED but with **reduced scope**. Note this explicitly in your verdict reasoning.

### 6.5 C-05 vs C-06 (same file, different concerns)

Both findings target `workers/drift_check.py`. Opus's C-05 is missing-RLS-context. Gemini's C-06 is advisory-lock-not-wrapped-in-try/finally. They are **independent valid concerns**. Adjudicate each separately. Do not collapse them.

### 6.6 Severity escalations recommended in consolidation §4

The consolidation suggests escalating C-05 (RLS) to Crit, C-08 (role gate) to Crit, C-13 (DD trigger role) to High. Apply §3.1 / §3.2 of this prompt — if the institutional convention applies, escalate. If you find a counter-argument (e.g. gateway-layer auth before route handler), explain.

---

## 7 · What you MUST NOT do

- Do not produce new findings as "main findings" — restrict net-new observations to the appendix and only with direct evidence.
- Do not adjudicate findings without citing line numbers in your reasoning.
- Do not refute a finding with "I don't see the bug" — refute with positive evidence (the bug doesn't exist as described, or is already fixed, or is unreachable).
- Do not skip findings — produce a verdict for all 15.
- Do not invent a sixth verdict category.
- Do not propose architectural rewrites in your reasoning — confine yourself to bug-level adjudication.

---

## 8 · Final reminder

Three Crit findings (C-01, C-02, C-03) are headed straight to remediation PRs after Stage 3 if you confirm them. Severity escalation candidates (C-05, C-08, C-13) determine whether those remediations are P0 (production-blocker) or P1 (next-sprint). Your verdicts have direct, dated consequences. **Be Crit-tier accurate.**

When you finish, save your output to `docs/audits/2026-04-28-wave6-session09-stage2-jury.md`.

## STAGE 2 JURY PROMPT ENDS — copy until here
