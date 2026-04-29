# Wave 6 — Per-model performance matrix

**Purpose:** track empirically whether the new 3-stage protocol (Opus + Gemini parallel discovery, GPT 5.5 jury) produces better triage signal than Wave 4-5's symmetric peer protocol. Update after each session.

**Definitions:**

- **TP rate** — TP findings / total findings raised by model
- **FP rate** — FP findings / total findings raised by model (excludes GRAYs)
- **GRAY rate** — GRAYs / total findings raised by model
- **Unique TP contribution** — TPs raised only by this model (not by any other Stage 1 model) / total TPs in session
- **Jury accuracy** (GPT 5.5 only) — verdicts that match Stage 3 final classification / total verdicts

---

## Session 01 (2026-04-26) — Returns / DD / Rolling / Backtest / Portfolio Metrics

### Stage 1 discovery models

| Model | Raised | TP | FP | GRAY | TP rate | FP rate | GRAY rate | Unique TP |
|---|---|---|---|---|---|---|---|---|
| **Gemini 3.1 Pro** | 9 | 7 | 1 | 1 | 78% | 11% | 11% | 4/7 = 57% |
| **Opus 4.6** | 3 | 3 | 0 | 0 | 100% | 0% | 0% | 0/7 = 0% |

**Observation:** Opus was perfectly conservative (zero FP, zero GRAY) but contributed zero unique TPs — every Opus finding was also raised by Gemini. Gemini was broader (4 unique TPs), with one FP (F06) and one GRAY (F04). For a single-session sample this matches the "depth + breadth" pairing the protocol intended; will need 3+ sessions to confirm pattern.

**Concrete unique-Gemini TPs that would have been missed by Opus alone:**
- F02 (Sterling denominator) — Math Critical / Inst High
- F03 (inline Sortino) — Math High / Inst High
- F05 (DD start at peak) — Math Med / Inst Low (Tier 4)
- F09 (truncation direction) — Math Med / Inst High

If only Opus had run, two Tier 1 institutional defects (F02, F03) would have shipped to remediation.

### Stage 2 jury (GPT 5.5)

| Verdicts | Aligned with Stage 3 | Partially aligned | Misaligned |
|---|---|---|---|
| 9 | 5 | 3 | 1 |

**Per-finding jury accuracy:**

| Finding | Jury verdict | Stage 3 final | Match? |
|---|---|---|---|
| F01 | CONFIRMED | TP Tier 2 | ✓ aligned |
| F02 | CONFIRMED | TP Tier 1 | ✓ aligned |
| F03 | CONFIRMED | TP Tier 1 | ✓ aligned |
| F04 | DOWNGRADED Low/Low | GRAY (api-contract issue) | partial — jury caught monthly-output question but framed as severity not contract |
| F05 | DOWNGRADED Med/Low | TP Tier 4 (Med/Low) | ✓ aligned |
| F06 | REFUTED | FP / handoff | ✓ aligned |
| F07 | DOWNGRADED High/Med | TP Tier 1 (High/High) | partial — Inst severity under-rated for our population |
| F08 | DOWNGRADED ?/High (incomplete output) | TP Tier 2 (High/High) | partial — output malformed (missing Math + Rationale) |
| F09 | DOWNGRADED Med/Med | TP Tier 2 (Med/High) | partial — Inst under-rated |

**Jury accuracy:** ~67% fully aligned + ~33% partial = effective accuracy ~78%.

**Unsolicited hypotheses:** 0 (protocol respected).

**Notable:** Jury's `REFUTED` on F06 was clean and correct — contract reading was tight. Jury's bias appears to be **Inst-severity conservatism** for findings that depend on institutional context (high-vol target population, fiduciary report use). Worth flagging in §4 jury heuristics for Session 02 prompts.

### Protocol verdict for Session 01

The 3-stage protocol delivered:
- **Net remediation surface:** 7 TPs + 1 GRAY (vs. 9 raw Stage 1 findings)
- **Filtered out:** 1 FP, 1 GRAY → 22% noise reduction
- **Severity disputes resolved:** 3 of 3, with jury contributing useful signal on 2 of 3
- **No unsolicited hypothesis pollution**

Comparison to hypothetical Wave 4-5 symmetric protocol (no jury): would have shipped F06 to triage (extra reviewer cycle), would have left F01/F07/F08 severity disputes unresolved.

**Recommendation:** Continue 3-stage for Sessions 02-13. After Session 03 (CVaR/tail/GARCH/EVT), revisit the matrix to confirm Opus-conservative / Gemini-broad / GPT-jury pattern is stable, not single-session noise.

---

## Construction Pipeline Runtime audit (post-PR-Q26, 2026-04-26)

Same 3-stage protocol applied to runtime degradation findings (not roadmap session). Hot-context Opus 4.6 (PR-Q26 implementer) + Gemini 3.1 Pro discovery + GPT 5.5 jury with **institutional-context calibration** added to §3.

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | FP rate | Unique TP |
|---|---|---|---|---|---|---|
| **Opus 4.6** | 6 | 5 | 1 | 83% | 17% | 2/5 = 40% (F05, F06) |
| **Gemini 3.1 Pro** | 6 | 3 | 3 | 50% | 50% | 0/5 = 0% (F07, F08 unique but FP) |

**Observation reverses Session 01 pattern.** Here:
- Opus contributed 2 unique TPs (F05 4-empty-blocks, F06 registry gap) — both DB-confirmed
- Gemini's 2 unique findings (F07, F08) were both **false positives** correctly refuted by jury
- Hot context (Opus had implemented PR-Q26 immediately before) gave Opus an edge

This is single-session noise OR validates that hot-context implementer audits surface unique TPs at higher rate. Need 2-3 more samples to discriminate.

### Stage 2 jury (GPT 5.5) — accuracy 100%

| Verdict | Count | Aligned with Stage 3 |
|---|---|---|
| CONFIRMED | 4 | 4/4 ✓ |
| DOWNGRADED | 1 | 1/1 ✓ |
| REFUTED | 3 | 3/3 ✓ |
| **Total** | 8 | **8/8 = 100%** |

**Jury accuracy jumped from 78% (Session 01) to 100%** with the institutional-context calibration in §3. Specifically:
- Caught both unique-Gemini FPs (F07, F08) cleanly
- Sustained F03 Critical Inst severity without soft-pedaling silent corruption
- Picked the correct angle on F02 dispute (observability defect, not threshold defect)
- Unsolicited hypotheses: 0 (protocol respected)

**Single-session sample, but the calibration update appears effective.** Maintain for Session 02 onwards.

---

## Wave 6 Session 02 (2026-04-26) — CVaR / Tail / EVT / GARCH

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | FP rate | Unique TP |
|---|---|---|---|---|---|---|
| **Opus 4.6** | 5 | 5 | 0 | **100%** | 0% | 3/6 = **50%** (F02, F03, F06) |
| **Gemini 3.1 Pro** | 3 | 3 | 0 | **100%** | 0% | 1/6 = **17%** (F05) |

**Pattern: hot context drives unique TP contribution.** Opus had fresh PR-Q26/27/28/29 context immediately preceding this session and dominated unique findings (3 of 6, including only Tier 1). Construction Pipeline audit showed the same pattern (Opus 2 unique TPs, Gemini 0 unique TPs). Session 01 was reversed (Gemini-dominant) because Opus had no recent quant_engine work.

**Concrete unique-Opus TPs that would have been missed by Gemini alone:**
- **F02 (L-moments silent swap)** — Tier 1 Critical/Critical, fiduciary risk for heavy-tail UCITS funds
- F03 (Inf filter inconsistency) — Tier 2 Med/High
- F06 (test gap on Critical pathway) — Tier 4 regression guard

### Stage 2 jury (GPT 5.5) — accuracy 100%

6 verdicts, all aligned exactly with Stage 3 final (severity included). 0 unsolicited hypotheses. Live source verification on 4 of 6 findings (cited specific line numbers in `optimizer_service.py`, `test_evt_pot_gpd.py`, `risk_calc.py`).

| Verdict | Count |
|---|---|
| CONFIRMED | 2 (F02, F03) |
| DOWNGRADED | 4 (F01, F04, F05, F06) |
| REFUTED | 0 |

### Protocol verdict for Session 02

- **Net remediation surface:** 6 TPs (zero filtering — all findings real)
- **Severity disputes:** 2 of 2 resolved with line-level evidence
- **Counterfactual:** without jury, F01 (Crit/High Gemini) and F04 (Low/Crit Gemini) would have shipped at inflated severity. Jury's middle adjudication (Med/Med, Low/High) is correct.

---

## Jury model decision — GPT-5.5 vs GPT-5.4 (2026-04-26)

**Decision status:** Tentative replacement — GPT-5.4 default jury replacing GPT-5.5.

**Cost driver:** 5.4 is ~50% cheaper than 5.5. If parity holds, decision is institutionally rational.

**Evidence status (Session 02 vs Construction Pipeline, both calibrated):**

| Dimension | 5.5 (CP audit, N=8 verdicts) | 5.4 (Session 02, N=6 verdicts) | Result |
|---|---|---|---|
| Verdict accuracy vs Stage 3 | 100% | 100% | parity |
| Severity adjudication on disputes | 1/1 correct | 2/2 correct | parity |
| Source verification (cited line numbers not inline in prompt) | Yes (`model_portfolios.py:2575-2631, :2048-2063`) | Yes (`optimizer_service.py:869, 1081`, `risk_calc.py:611`, `test_evt_pot_gpd.py:117`) | parity |
| Unsolicited hypotheses (protocol respect) | 0 | 0 | parity |
| Output discipline (no padding, clean format) | Clean | Clean | parity |
| Inconsistency-in-file detection | F03: route vs worker path | F04: 2-of-4 paths in garch | parity |

**No measurable degradation in Session 02.**

**Unvalidated capability — high-difficulty active refutation (prove-negative path):**

Not yet tested for 5.4. Session 02 had zero false-positive findings — all 6 Stage 1 findings were real, so jury had no opportunity to REFUTE. This means the following capabilities are unverified for 5.4:

- **Phantom-claim destruction** — refute a Stage 1 finding by showing the cited code path doesn't behave as claimed. Demonstrated strongly by 5.5 in Construction Pipeline F07: proved `_resolve_trace_instrument_ids` already has provenance via `reason="excluded_or_no_nav"` that Gemini missed.
- **Hidden-contract invalidation** — refute by citing existing contract that the finding overlooked. 5.5 in CP F08: refuted IPS-driven `max=0.0` as working-as-designed.
- **Source-grounded contradiction of plausible FP findings** — when a finding sounds reasonable but is subtly wrong, the jury must read enough source to invert it confidently.

These are the harder cognitive tasks in jury work. 5.4 has not been tested on them yet.

**Escalation trigger — re-evaluate if Sessions 03–04 produce:**

1. Costly false positives surviving jury (jury fails to REFUTE, orchestrator catches in Stage 3)
2. Failed refutation of plausible but wrong findings (jury CONFIRMs or DOWNGRADEs when REFUTE was correct)
3. Weak contradiction depth vs source-grounded adversarial claims (jury accepts surface argument without challenging implementation)

If any of the above appear in Sessions 03–04, switch escalation jury to 5.5 for high-stakes / high-FP-risk findings.

**Operational policy:**

- **5.4 = default jury** for all Wave 6 audit sessions.
- **5.5 = escalation-only** when Sessions 03–04 evidence shows 5.4 ceiling.

In effect until contrary evidence appears.

---

## Wave 6 Session 03 (2026-04-26) — Covariance / Correlation / Factor Models / IPCA-PCA

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | Unique TP |
|---|---|---|---|---|---|
| **Opus 4.6** | 4 | 4 | 0 | **100%** | 3/9 = **33%** (F02, F03, F04 — all Tier 4) |
| **Gemini 3.1 Pro** | 6 | 6 | 0 | **100%** | 5/9 = **56%** (F05, F06, F07, F08, F09) |

**Pattern reversal:** despite Opus having hot context (Q30-Q33 just shipped), Gemini dominated unique TPs (56% vs 33%). Gemini contributed the only Tier 1 (F07 residual variance unweighted SSE — verified via concrete 28x synthetic example by jury).

**Refined hypothesis** (see `memory/project_hot_context_opus_pattern.md` updated): hot context is correlation not law. `factor_model_service.py` 849 LoC + math-domain pattern matching favored Gemini.

### Stage 2 jury (GPT 5.4) — accuracy 100% AND prove-negative VALIDATED

9 verdicts: 1 CONFIRMED, 8 DOWNGRADED, 0 REFUTED, 0 unsolicited.

**Per-finding alignment with Stage 3 final:** 9/9 exact match (severity included).

**🎉 Prove-negative capability VALIDATED:** Three previously-untested capabilities from `feedback_jury_model_5_4_default.md` demonstrated this session:

1. **Phantom-claim destruction** (F06): refuted Gemini's "OAS_TICKERS oversight" theory by citing defensive label + existing test
2. **Hidden-contract invalidation** (F05): refuted "leakage urgency" by inspecting 3 caller files NOT in scope
3. **Source-grounded contradiction** (F07): ran 5-year synthetic example to compute 28x inflation factor, verified Gemini's math claim

**Operational policy update:** GPT-5.4 default jury for ALL future sessions. Escalation to 5.5 deferred indefinitely. N=2 calibrated sessions (02 + 03), both 100% accuracy.

---

## Wave 6 Session 04 (2026-04-26) — Optimizer / Risk Budgeting / Rebalance / Mandate Risk-Aversion

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | Unique TP |
|---|---|---|---|---|---|
| **Opus 4.6** | 8 | 7 | 1 | 88% | 4/12 = **33%** (F09, F10, F11, F12 — parity/structural) |
| **Gemini 3.1 Pro** | 9 | 8 | 1 | 89% | 5/12 = **42%** (F04, F05, F06, F07, F14 — all 4 Tier 1 math claims) |
| Both (overlap) | 3 | 3 | 0 | 100% | 3 (F01, F02, F03 — charter §3 violations) |

**Pattern reversal CONFIRMED N=2:** Despite Opus having hot context (Q26-Q36 all touched quant_engine), Gemini dominated unique TPs again (42% vs 33%) AND owned all 4 Tier 1 math claims. Opus actively dismissed the highest-stakes finding (F04 negative λ clamp) in its "Checked invariants #6" — labeling the unreachable branch as "still defensive" when it IS the bug.

**Hypothesis upgraded to empirical N=2:** for files with **high math density + length > 800 LoC**, Gemini holds comparative advantage even when Opus has hot context. Sessions 03 (factor_model_service 849 LoC) and 04 (optimizer_service 1515 LoC) both reproduced the pattern. Opus comparative advantage shifts to **cross-module parity** and **structural** defects.

### Stage 2 jury (GPT 5.4) — accuracy 100%

14 verdicts: 5 CONFIRMED (F03, F04, F05, F07, F09, F10, F11, F12 — wait, 8 confirmed actually), 4 DOWNGRADED (F01, F02, F06, F14), 2 REFUTED (F08, F13), 0 unsolicited.

**Per-finding alignment with Stage 3 final:** 14/14 exact match (severity included where reassigned).

**Two clean REFUTED verdicts on plausible-but-wrong findings:**
- F08 (Opus): cited `cp.psd_wrap` "silent projection to PSD cone" — jury verified the function does NOT project, only wraps for DCP. **New FP pattern: claimed-mechanism-doesn't-exist-as-described.**
- F13 (Gemini): MCETL finite-difference instability — jury ran ε sweep (1e-3 to 1e-7), output stable. Analytic formula preference, not bug.

### New FP pattern: claimed-mechanism-doesn't-exist-as-described

Add to FP heuristics for Sessions 05+ megaprompts: "auditor cites a *specific function behavior* (e.g., `cp.psd_wrap` projects to PSD cone) that does not exist as described. Distinct from missed-upstream-guard — here the alleged guard/mechanism is itself a mischaracterization. Verify by reading the function's actual implementation, not its name."

## Wave 6 Session 05 (2026-04-27) — Black-Litterman / Views / Expected Returns / Monte Carlo / Data Commons

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | Unique TP |
|---|---|---|---|---|---|
| **Opus 4.6** | 11 (F10-original self-withdrawn) | 5 | 3 | 62.5% | 5/10 = **50%** (F04, F06, F07, F08, F14) |
| **Gemini 3.1 Pro** | 6 | 5 | 1 | 83% | 2/10 = **20%** (F11, F12) |
| Both (overlap) | 3 | 3 | 0 | 100% | 3 |

**Pattern reasserted N=2 (Opus-strong on small files):** BL service main file is 439 LoC — below empirical 800 LoC threshold for Gemini-dominance. Opus contributed 5 unique TPs vs Gemini 2. **However, both Tier 1 math claims (F11 BL NaN/LinAlgError, F12 He-Litterman τ scaling — though F12 ultimately Low/Low) came from Gemini.** High-stakes math findings remain Gemini comparative advantage even on smaller files.

**Self-correction observed (positive Opus signal):** Opus self-withdrew F10-original "BL P_stack vstack 1-D arrays" after grep verification that validation runs before `vstack` at line 176. Sign of increased rigor post-Session 04 calibration. Add to "missed-upstream-guard" rejection heuristic — Opus is now executing the ±20-line grep discipline reliably.

### Stage 2 jury — DUAL RUN (5.4 + 5.5 corroboration)

This was the first Session with both juries dispatched. 5.4 produced initial verdicts; Andrei requested 5.5 corroboration "as one-time" because 5.4 had 5 medium-confidence verdicts. 5.5 results led to **D-jury-5.4 reversal**.

| Jury | Verdicts | Aligned with Stage 3 final | Accuracy |
|---|---|---|---|
| GPT-5.4 | 14 | 11 | **78.6%** |
| **GPT-5.5** | **14** | **14** | **100%** |

**5 verdict divergences, all favoring 5.5:**

| Finding | 5.4 verdict | 5.5 verdict | Stage 3 truth | Reason 5.5 won |
|---|---|---|---|---|
| F04 MC degeneracy | DOWN M/M | **CONFIRMED H/H** | TP H/H | Numerical reproduction discipline |
| F08 weight_sum unvalidated | DOWN L/L | **CONFIRMED M/M** | TP M/M | §3.4 contract violation explicit |
| F09 _block_bootstrap defensive | DOWN L/L | **REFUTED** | FP | Sharper "speculative-future" detection |
| F10 BL λ floor warning | DOWN L/L | **REFUTED** | FP | Dead-code recognition post-Q37 |
| F12 He-Litterman τ scaling | CONFIRMED M/M | **DOWN L/L** | TP L/L | Cross-finding consistency w/ F06 |

**Pattern observed:** 5.5 takes more decisive positions in BOTH directions — sharper CONFIRMs on real defects (with empirical reproduction), sharper REFUTEDs on dead/speculative code, more consistent treatment of deprecated paths. 5.4 defaulted to "DOWNGRADE to Low/Low" middle-ground when evidence was partial.

**Decision:** D-jury-5.4 REVERTED. GPT-5.5 = default jury for all Wave 6 sessions effective 2026-04-27. Cost premium (~$15/session) trivial vs missed-Tier-1 fiduciary risk. Andrei: "20% a mais de acurácia é muita coisa". See `feedback_jury_model_5_4_default.md`.

## Wave 6 Session 07 (2026-04-27) — Scoring / Normalization / Peer Comparison / Asset-Class Analytics

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | Unique TP |
|---|---|---|---|---|---|
| **Opus 4.6** | 6 | 6 | 0 | **100%** | 2/10 = 20% (F05, F06 — both architectural) |
| **Gemini 3.1 Pro** | 8 | 8 | 0 | **100%** | 4/10 = 40% (F07, F08, F09, F10 — all pure math) |
| Both (overlap) | 4 | 4 | 0 | 100% | 4 (F01, F02, F03, F04) |

**0 FPs in Session 07.** Both models 100% TP rate. Heterogeneous file (`scoring_service` 653 LoC + dispatch + analytics) split contribution by defect type:
- Gemini owns 4/4 unique pure-math defects (jackknife SE, OBV sign, percentile ties, normalize bounds)
- Opus owns 2/2 unique architectural defects (silent dispatch, opacity penalty)

### Direct Opus↔Gemini contradiction adjudication

**F10 (Gemini math) vs Opus Checked Invariant #13** — peer percentile tied-value handling.

**Jury verdict:** REFUTED Opus's "documented competition method" claim. Gemini's mid-rank for ties claim sustained.

Refutation rationale: "code doc only says 0-100 higher-is-better, with no explicit tie convention. Production corroboration exists: risk_calc.py:2400-2405 uses same arr <= value percentile formula for stored peer percentiles."

**Adjudication tally across Wave 6 contradictions:**

| Session | Topic | Winner |
|---|---|---|
| S04 | Hysteresis severity-rank | Gemini |
| S06 | Amplification weights unit-sum | Opus |
| **S07** | **Percentile rank ties handling** | **Gemini** |

**Score 2-1 Gemini.** Both models complementary; neither alone sufficient. Empirically validated N=3.

### Stage 2 jury (GPT-5.5) — accuracy 100% sustained N=3

10 verdicts: 6 CONFIRMED, 4 DOWNGRADED, 0 REFUTED, 0 unsolicited.

**10/10 alignment with Stage 3 final.** Jury demonstrated:
- Production caller verification on F02, F03, F05, F10 (all 4 cited specific risk_calc.py / universe_sync.py line numbers)
- Direct contradiction handling on F10 vs Opus #13
- Severity inflation calibration on F01, F07, F09 (all correctly downgraded)
- Phantom-caller pattern S06-F09 applied to F04 (DOWNGRADED to Low/Low after no-caller grep)

**D-jury-5.5 validated for third consecutive Wave 6 session (S05+S06+S07, all 100%).**

### Pattern hypothesis N=4 sustained

| Profile | Pattern | Evidence |
|---|---|---|
| Big + homogeneously math-dense | Gemini-dominant raw count | S03 factor_model 849; S04 optimizer 1515 |
| Big + heterogeneous (classifier + state machine + helpers) | Split by type — Gemini owns math, Opus owns structural | S06 regime 1256 + regional 898 |
| Medium + heterogeneous (scoring + dispatch + analytics) | **Split by type sustained** | **S07 scoring 653 + 8 modules** |
| Small (<500 LoC) | Opus-dominant raw count | S05 BL service 439 |

File complexity threshold is necessary but not sufficient for Gemini-dominance. Defect-type heterogeneity dilutes Gemini's math-pattern advantage.

### Charter §3 violation concentration

7 of 10 TPs (70%) are charter §3 silent-corruption violations. Sustained from S06 (73%). Reflects scoring/normalization role as institutional ranking layer — defaults wrong here propagate to every fund decision surface.

---

## Wave 6 Session 06 closure summary (2026-04-27 end-of-day)

6 PRs Q51-Q56 shipped all 11 in-engine TPs. Charter §3 violations 8 of 8 closed. 1 FP correctly refuted by jury (S06-F01 _amplify_weights phantom-caller pattern).

**Session 06 calibration observations (memory candidates):**

1. **Q52 no-production-callers (calibration data):** implementer discovered `apply_regime_hysteresis` has no production callers — workers implement hysteresis inline. Math severity High sustained (real bug); Inst severity Critical may have been overstated (no live blast radius). Pattern: jury Inst severity claims should account for caller-reachability, not just function correctness. Track if recurrent.

2. **Q53 INFLATION exemption (principled deviation):** prompt's F11 clamp would have overridden CPI structural classification. Implementer pre-flight test grep caught it; added `and regime != "INFLATION"` clause. Documented in commit. Reverse-subsumption pattern N=4.

3. **Q54 3-test update (largest reverse-subsumption catch):** implementer updated 3 pre-existing tests asserting RISK_ON fallback behavior. Reverse-subsumption pattern N=5 sustained.

4. **Q51 + Q56 broader-scope > narrow-scope pattern (N=3):** implementer agents now treat the prompt as a "bug class specification" and scan for all instances. Q51 found 2 additional non-stationary series; Q56 found 3 additional stale-percentage comments; Q53 added principled deviation. Positive emergent pattern.

5. **Cumulative jury accuracy GPT-5.5: N=2 sustained 100%** (S05 + S06). D-jury-5.5 default validated.

---

## Wave 6 Session 06 (2026-04-27) — Regime / Regional Macro / TAA / Stress Severity / FRED / Fiscal Data

### Stage 1 discovery models

| Model | Raised | TP | FP | TP rate | Unique TP |
|---|---|---|---|---|---|
| **Opus 4.6** | 8 | 7 | 0 | **100%** | 7/11 = **64%** (F02, F03, F04, F05, F06, F08, F12) |
| **Gemini 3.1 Pro** | 5 | 3 | 1 (F01) | 75% | 3/11 = **27%** (F09, F10, F11) |
| Both (overlap) | 1 | 1 | 0 | 100% | 1 (F07) |

**File complexity refined hypothesis** — N=4 sessions empirical:

| Profile | Pattern | Evidence |
|---|---|---|
| Big + **homogeneously math-dense** | Gemini-dominant raw count | S03 factor_model 849 LoC; S04 optimizer 1515 LoC |
| Big + **heterogeneous** (classifier + state machine + helpers) | **Split by type** — Gemini owns math, Opus owns structural/parity | **Session 06: regime 1256 + regional 898 with Opus 7/7 structural, Gemini 3/3 math** |
| Small (<500 LoC) | Opus-dominant raw count | S05 BL service 439 LoC |

File complexity threshold is necessary but not sufficient for Gemini-dominance. Heterogeneous code dilutes Gemini's pattern-match advantage; homogeneous math concentrates it.

### Direct Opus↔Gemini contradiction adjudication (key institutional signal)

Two Gemini findings directly contradicted Opus "Checked invariants" claims:

| Contradiction | Jury verdict | Winner |
|---|---|---|
| F01 (Gemini math claim) vs Opus #3 "Weight amplification convexity" | **REFUTED** — production caller analysis shows path unreachable | **Opus** |
| F09 (Gemini math claim) vs Opus #1 "Hysteresis correctness" | **CONFIRMED** — severity-rank arithmetic verified line-level | **Gemini** |

**Split 1-1 across direct contradictions.** Confirms both models are essential. Removing either introduces incorrectness:
- Without Gemini: F09 hysteresis flap (T1 H/Crit) ships → portfolio rebalancing thrash
- Without Opus's invariant scrutiny: F01 ships as TP (FP) → wasted PR cycle on unreachable code

### Stage 2 jury (GPT 5.5) — accuracy 100%

12 verdicts: 9 CONFIRMED, 2 DOWNGRADED (F01 actually REFUTED, F02 DOWNGRADED Crit/Crit→Med/High), 1 REFUTED, 0 unsolicited.

**Per-finding alignment with Stage 3 final: 12/12 = 100%.**

GPT-5.5 sustained:
- Numerical reproduction discipline (S06-F10 verified line-level: PAYEMS/CPIAUCSL raw + units="lin" default + percentile_rank on monotonic levels)
- Sharp REFUTED via production caller analysis (S06-F01 — caller positivity argument)
- Severity adjudication on F02 (Crit/Crit → Med/High — bounded blast radius)
- Direct contradiction handling — 2 adjudications correct

**D-jury-5.5 validated for second consecutive Wave 6 session (S05 + S06, both 100%).**

### Charter §3 concentration

8 of 11 TPs (73%) are charter §3 silent-corruption violations — **highest concentration of any Wave 6 session**. Reflects regime/macro module's role as default propagation point: defaults wrong here propagate to every downstream worker AND every CLARABEL phase via CVaR multipliers.

### Calibration win observed

Both Stage 1 models avoided FP pattern S05-F13 ("generic-convention-without-source-verification") on a megaprompt §3.3 overclaim about GFC/COVID/Taper/Rate Shock parametric stress scenarios. Gemini explicitly invoked the FP heuristic in checked invariants. **Wave 6 FP heuristics now empirically internalized in Stage 1 agents N=2.**

---

### Session 05 closure summary (2026-04-27)

6 PRs Q44-Q49 shipped all 9 in-engine TPs. F14 (caller-side handoff) deferred to separate PR. 4 FPs (F05, F09, F10, F13) correctly refuted by jury 5.5.

**Reverse-subsumption pattern N=3 sustained** across Wave 6:
- Q41-followup (Session 04): 1-line follow-up after Q42 implementer flagged Q40's control test breaking under Q41's stricter Pareto bounds.
- Q45 (Session 05): in-PR rename of `test_missing_block_renormalized` → `test_missing_block_returns_empty` after pre-flight grep.
- Q47 (Session 05): in-PR update of 3 Data Commons tests asserting silent `[]` to expect `DataCommonsAPIError`.

**Quality progression:** Q41 missed → Q45 self-corrected (1 test) → Q47 self-corrected (3 tests). Memory entry `feedback_subsumption_reverse_test_gap.md` is being internalized by implementer agents; explicit pre-flight grep instruction in PR prompts producing reliable in-PR handling.

### New Wave 6 calibration signal: megaprompt contract claims must be source-verified

**S05-F13 lesson:** my (orchestrator) megaprompt §3.4 claim "Rebase to 100 at the start of the composite series" was incorrect — local codebase convention is consistently 1000.0 (verified across `benchmark_composite_service.py:9-12`, `model_portfolio.py:38-40`, `portfolio_nav_synthesizer.py:7-9`, plus tests). Both juries (5.4 and 5.5) caught this and REFUTED Gemini's finding. Important calibration:

- Orchestrator megaprompts must source-verify contract claims, not invoke conventions from training data or generic finance knowledge
- For Sessions 06+ megaprompts: when stating contract values (constants, ratios, defaults), grep the codebase + read schema files first
- Add to megaprompt §3 process: "Contract claims must cite file:line evidence"

---

### Session 04 closure — reverse-subsumption pattern (2026-04-27)

7 PRs Q37-Q43 + 1 hygiene followup (PR #341) shipped 12 TPs across Wave 6 Session 04. **Reverse-subsumption pattern observed during cycle:**

- Q40 added `test_optimize_portfolio_pareto_succeeds_with_complete_expected_returns` with `ProfileConstraints(blocks=[])` default cap 0.15; Pareto path used `xu=1.0` fallback → feasible.
- Q41 F09 tightened `xu` fallback to `constraints.max_single_fund_weight` → 2 × 0.15 = 0.30 < 1.0 → infeasible.
- Q41 implementer fixed its own test file but missed Q40's adjacent control test in another file.
- Q42 implementer's pre-existing-failures report surfaced it deterministically.
- Q41-followup PR #341: 1-line fix (add `max_single_fund_weight=1.0`). Diagnosed by orchestrator (math-trivial: 0.15 × 2 < 1.0); applied direct.

**Lesson:** stricter-check PRs need explicit instruction to grep ALL adjacent test files for fixtures relying on the looser pre-fix constraint, not just the PR's own tests. Memory: `feedback_subsumption_reverse_test_gap.md`. Add to Sessions 05+ stricter-check PR prompts.

**Distinct from forward-subsumption** (`feedback_pr_remediation_subsumption_check.md`):
- Forward: higher-tier fix in current PR makes lower-tier fix obsolete (Q34 F08 → F02). Look BEFORE bundling.
- Reverse: stricter check exposes test gap from prior PR. Look AFTER landing.

---

## Session 09 (2026-04-28) — Wealth Routes & Workers Integration

First non-quant integration audit. Inserted into roadmap §5 ahead of original Session 09 after smoke-test Caminho A surfaced 4 P1/P2 bugs in 4 HTTP calls (PR-Q91/Q92/Q93 already shipped before audit ran).

### Stage 1 discovery models

| Model | Raised | TP | FP | GRAY | TP rate | FP rate | GRAY rate | Unique TP |
|---|---|---|---|---|---|---|---|---|
| **Opus 4.6** | 14 | 13 | 1 (C-09 subsumed by Q92) | 0 | 93% | 7% | 0% | 9/14 = **64%** |
| **Gemini 3.1 Pro** | 5 | 5 | 0 | 0 | 100% | 0% | 0% | 1/14 = **7%** |

**Observation:** Roles inverted from prior 6 sessions. Routes/Workers integration is **low-math, low-LoC-density** (mostly ≤1500 LoC files), so Gemini's math-density advantage (`reference_gemini_math_strength_heuristic.md`) does NOT apply. Gemini was perfectly conservative (zero FP, 100% TP rate) but contributed only 1 unique TP (C-06 lock leak in drift_check). Opus dominated with 9 unique TPs across the integration surface.

**Concrete unique-Opus TPs that would have been missed by Gemini alone:**
- C-03 (UUID cast 5 sites) — Crit privilege-escalation-like bug
- C-04 (regime_fit dead lock) — High worker race
- C-05 (drift_check no RLS) — Crit multi-tenant leak
- C-08 (apply_rebalance no role gate) — Crit privilege escalation
- C-13 (DD trigger no IC role) — High unbounded LLM spend
- C-10, C-11, C-12, C-14 — 4 Med findings

If only Gemini had run, 4 Crit institutional defects would have shipped.

### Stage 2 jury (GPT 5.5)

| Verdicts | CONFIRMED | CONFIRMED-ESCALATED | CONFIRMED-DOWNGRADED | REFUTED | REFUTED-FP | GRAY |
|---|---|---|---|---|---|---|
| 15 | 9 | 3 (C-05, C-08, C-13) | 1 (C-06) | 1 (C-09 by Q92 subsumption) | 0 | 0 |

**Per-finding jury accuracy (vs Stage 3 final):**

All 15 verdicts align exactly with Stage 3 triage. The 3 escalations applied institutional convention §3.1 correctly (multi-tenant leak, privilege escalation). The 1 downgrade (C-06 from Crit to High) was a defensible reduction — lock leak doesn't auto-Crit unless DB restart proven required.

**Direct contradiction resolution:** C-07 had Opus saying bug, Gemini saying verified-OK in Checked Invariants. Jury read `dd_reports.py:572-583` directly and confirmed Opus + cited the missing UPDATE-before-INSERT pattern at line 572-583. Opus right, Gemini wrong.

**Jury accuracy:** 15/15 = **100%**. N=5 consecutive 100% sessions for GPT-5.5.

**Unsolicited hypotheses:** 0 (protocol respected).

### Protocol verdict for Session 09

- Both Stage 1 models still essential. Even though Gemini's recall fell to 7% unique on integration audit (vs 32% prior aggregate), it provided independent corroboration on 4 of Opus's findings + 1 unique catch (C-06). Cannot drop Gemini.
- File complexity hypothesis refined: **math-density** is the differentiator, not raw LoC. Routes/Workers ARE low-LoC compared to construction pipeline files (5666 model_portfolios), but their integration semantic is what Opus catches better — annotation lies, idempotency in route handlers, role gates. Gemini's pattern-matching strength is in number-line correctness, not workflow contract correctness.
- Stage 2 jury 5.5 sustained 100% accuracy on a session with 3 ESCALATIONS + 1 DOWNGRADE + 1 PR-subsumption REFUTE. Calibration robust.
- Audit roadmap §1 scope expansion (route/worker layer added 2026-04-28) immediately validated — 14 confirmed bugs in a domain prior 8 sessions never reached.

---

## Session 10 (2026-04-29) — Wealth Model Portfolio, Mandate Fit, Validation

Highest Crit-density session in Wave 6 to date (8 Crit at Stage 1, 7 Crit at Stage 2 after C-04 downgrade). Domain: model portfolio lifecycle + validation gate + mandate fit + stress scenarios + track record.

### Stage 1 discovery models

| Model | Raised | TP | FP | GRAY | TP rate | FP rate | GRAY rate | Unique TP |
|---|---|---|---|---|---|---|---|---|
| **Opus 4.6** | 8 | 8 | 0 | 0 | 100% | 0% | 0% | 5/14 = **36%** |
| **Gemini 3.1 Pro** | 9 | 9 | 0 | 0 | 100% | 0% | 0% | 6/14 = **43%** |

**Observation:** Both models hit 100% TP rate — no FPs, no GRAYs. Coverage roughly balanced (Opus 8/14 = 57%, Gemini 9/14 = 64%). Gemini outpaced Opus in raw count and unique contribution, consistent with `reference_gemini_math_strength_heuristic.md` — Session 10 has high math density (CVaR sign flip, stress scaling, dispersion seed, block weight invariants).

**Concrete unique-Gemini TPs that would have been missed by Opus alone:**
- C-02 (TRANSITIONS missing constructed→approved edge — OD-5 override broken) — Crit
- C-03 (CVaR improvement sign flip — advisor recommends WORST funds) — Math Crit
- C-06 (historical stress imputes 0% for missing fund history) — Math Crit
- C-07 (silent block dropping breaks 60/40 strategic targets) — Math High / Inst Crit
- C-08 (mandate fit hard/soft fusion) — Inst High
- C-11 (state_machine bypasses write_audit_event Q92 invariant) — Inst Crit

**Concrete unique-Opus TPs that would have been missed by Gemini alone:**
- C-01 (live approval path no validation gate check) — Crit
- C-04 (empty ValidationDbContext disables 5 checks) — High (post-jury downgrade)
- C-09 (block-severity check exception fail-open) — High
- C-10 (executor bypasses state_machine.transition) — High
- C-14 (CVaR sqrt(252) heuristic) — Low

**Counterfactual coverage** (per Stage 2 jury final severities):

- **If only Opus had run** (Gemini's 6 unique TPs missed): **5 Crit + 1 High** would be missed (C-02 + C-03 + C-06 + C-07 + C-11 + C-08).
- **If only Gemini had run** (Opus's 5 unique TPs missed): **1 Crit + 3 High + 1 Low** would be missed (C-01 Crit, C-04 + C-09 + C-10 High, C-14 Low).

**Both essential — domain inversion vs Session 09.** Skipping Gemini on this session would have left 5 Crit findings in production. Skipping Opus would have left 1 Crit (the live-path validation gate bypass C-01) plus 3 High audit/validation defects. Codex Auto Review on PR #415 caught an earlier version of this paragraph that misattributed the scenarios — the corrected counts above match the Opus-only and Gemini-only lists above and the Stage 2 jury final severities.

### Stage 2 jury (GPT 5.5)

| Verdicts | CONFIRMED | CONFIRMED-ESCALATED | CONFIRMED-DOWNGRADED | REFUTED | REFUTED-FP | GRAY |
|---|---|---|---|---|---|---|
| 14 | 13 | 0 | 1 (C-04 from Crit→High) | 0 | 0 | 0 |

**Per-finding jury accuracy:** All 14 verdicts align with Stage 3 final classification. The single downgrade (C-04) was correctly justified — current code now includes `as_of_date` in the validation payload, invalidating part of Opus's NAV bypass mechanism. The remaining empty-context defect (5 of 16 checks blind) is real and rated High.

**Direct contradiction resolution:** C-11 had Gemini saying Crit (write_audit_event invariant required), Opus marking it OK in checked-invariants (PortfolioStateTransition is sufficient domain audit). Jury confirmed Gemini's reading by citing Session 10 audit invariant I-State-1/I-Audit-Tenant-1 and CLAUDE.md §audit logging requirement. Q92's `allow_global=False` controls scoping but doesn't permit skipping the unified audit feed.

**Jury accuracy:** 14/14 = **100%**. N=6 consecutive 100% sessions for GPT-5.5.

**Unsolicited hypotheses:** 0 (protocol respected).

### Protocol verdict for Session 10

- Both Stage 1 models still essential — Session 10 confirms domain-aware dispatch needs both. Math-heavy domains favor Gemini's recall; workflow-heavy domains favor Opus. **Cannot drop either.**
- Stage 2 jury 5.5 sustained 100% accuracy across a session with 1 DOWNGRADE + 1 direct contradiction adjudication.
- Highest Crit-density session: 7 Crit + 5 High after Stage 2. Model portfolio lifecycle layer has the largest bug surface in Wave 6.
- 4 cross-cutting themes in remediation: validation gate bypassable (3 escape paths), risk math wrong (3 distinct ways), audit trail layered gaps (executor + state_machine), hard/soft discipline blurred (mandate + validation).

### Stage 3 remediation queue

12 PR prompts produced by Stage 3 orchestration (Opus 4.7), bundled by technical proximity:
- 6 P0 Crit PRs (Q110-Q115)
- 5 P1 High PRs (Q116-Q120)
- 1 P2/P3 batch (Q121: C-13 + C-14)

Q110 (state machine C-01+C-02 bundle) and Q121 (RNG + CVaR heuristic batch) are intentional bundles per coherent technical scope. All other PRs are 1-finding scope.

---

## Aggregate (running, 8 sessions including S10)

| Model | Sessions | Total raised | TP rate (avg) | Unique TP contribution (avg) | Notes |
|---|---|---|---|---|---|
| **Opus 4.6** | 8 | 3 + 6 + 5 + 4 + 8 + 11 + 14 + 8 = 59 | 100% + 83% + 100% + 100% + 88% + 62% + 93% + 100% = **91%** | 0% + 50% + 50% + 33% + 33% + 50% + 64% + 36% = **40%** | S10 Opus 100% TP rate, lower unique contribution than Gemini for first time post-S03 — Session 10 high math density favors Gemini's pattern recognition |
| **Gemini 3.1 Pro** | 8 | 9 + 6 + 3 + 6 + 9 + 6 + 5 + 9 = 53 | 78% + 50% + 100% + 100% + 89% + 83% + 100% + 100% = **88%** | 57% + 0% + 17% + 56% + 42% + 20% + 7% + 43% = **30%** | Math-domain dominance in S10 (CVaR sign, stress scaling, missing-data 0%, hard/soft mandate) — confirmed `reference_gemini_math_strength_heuristic.md` |
| **Jury 5.4** | Sessions 02-05 (default) | 8 + 6 + 9 + 14 = 37 verdicts | 100% / 100% / 100% / **78.6%** | — | Deprecated as default 2026-04-27 |
| **Jury 5.5** | Construction Pipeline + S05-corroboration + S06 + S07 + S08 + S09 + S10 | 8 + 14 + 12 + 10 + 10 + 15 + 14 = 83 verdicts | 100% / 100% / 100% / 100% / 100% / 100% / **100%** | — | N=6 consecutive 100% sessions; S10 had 1 DOWNGRADE + 1 direct contradiction adjudication, both correctly resolved |

**Pattern stability after 8 sessions:**

1. **Opus + Gemini are complementary, not redundant.** Domain inversion confirmed in S09: Opus dominates integration/workflow-contract domain (9 unique TPs out of 14), Gemini dominates math-density domain (S03/S04 both Gemini-dominant). Both must run in parallel — neither alone sufficient across the audit roadmap.

2. **Domain-aware dispatch refined:** the "math-density × LoC > 800" hypothesis is updated. **Math-density** is the differentiator, not LoC. Routes/Workers files in S09 ranged 73-3010 LoC but Gemini's recall was independent of size — the underlying domain (integration semantics, not numerical math) is what Gemini does not optimize for. Continue running both models on every session; do NOT skip Gemini on small-file sessions.

3. **Jury 5.5 accuracy 100% across 5 consecutive sessions.** S05-corroboration / S06 / S07 / S08 / S09 all 100% with verdict spaces ranging 8-15 findings, including escalations (S09 had 3 ESCALATIONS + 1 DOWNGRADE + 1 PR-subsumption REFUTE). Capability ceiling not yet reached.

4. **Gemini Inst severity bias = HIGH** (charter §3 invocations). **Opus Inst severity bias = MIXED** — under-rates privilege escalation and multi-tenant leaks (S09 C-05 / C-08 / C-13 all required jury escalation). Memory: prompt jury §3 institutional convention is what catches this consistently.

5. **GPT-5.5 default jury sustained.** No regression to 5.4 considered. The 22% accuracy gap from Session 05 dual-run continues to justify cost premium.

6. **Audit roadmap §1 scope (post-2026-04-28):** original `quant_engine + vertical_engines/wealth` scope was insufficient — the integration layer (routes + workers) was a blind spot. Session 09 validated the expansion. Sessions 10-15 should consider whether each has a similar integration-layer companion that needs auditing in parallel.

(Will accumulate as Sessions 05-13 complete.)
