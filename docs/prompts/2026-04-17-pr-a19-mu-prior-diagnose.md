# PR-A19 — μ Prior Diagnose-First Spec

**Date**: 2026-04-17
**Status**: DIAGNOSE-ONLY (pattern = PR-A12.3 / A17.1). No fix in this PR.
**Branch**: `feat/pr-a19-mu-prior-diagnose`
**Predecessors merged**: A11, A12, A14, A15, A17, A17.1, A18.

---

## 0. Problem Statement (empirical, not hand-wavy)

Run 2026-04-17, Balanced profile (CVaR limit 7.5% per PR-A18), post-A15/A17.1 (κ healthy = 5.8k, factor fit working, coverage 78-91%).

| Metric | Observed | Market truth (1Y) |
|---|---|---|
| Delivered E[r] | **~0.83%** | n/a |
| Top holding | **VTEB** (muni) | real 1Y return **+5.46%** |
| SPY weight | **~0** (ignored) | real 1Y return **+21.09%** |
| GLD weight | **~0** (ignored) | real 1Y return **+36.64%** |
| Universe | 2629 eligible US equity funds + FI | — |

The optimizer is NOT infeasible (PR-A12's RU LP guarantees always-solvable). Phase 1 `max μᵀw` picks VTEB because **the μ vector entering the LP is collapsed** — muni vs SPY signal is inverted or flattened. Expected E[r] for Balanced at 7.5% CVaR with a 21%-returning SPY in the universe should be **10-15% minimum**. Delivered 0.83% is a μ construction defect, not a constraint defect.

Prior evidence tracked in memory `project_mu_prior_calibration_concern.md`: PR-A12 saw 30%+ E[r] at 2% CVaR for Conservative and flat E[r] for Balanced in different runs — i.e. μ is not stable across profiles and universes. Real-market delta now nails it.

---

## Section A — Code Archaeology (mandatory reading before Section C instrumentation)

### A.1 μ construction path — authoritative file

**`backend/app/domains/wealth/services/quant_queries.py`** is the single entry point. Function `compute_fund_level_inputs` (line **1213**) builds the μ vector passed to the optimizer. No other path writes μ. Vertical-agnostic optimizer code (`quant_engine/optimizer_service.py`, `quant_engine/ru_cvar_lp.py`) consumes μ as a read-only parameter — it performs no μ transform.

### A.2 Seven transforms applied to μ, in order

Trace from raw historical returns → LP input:

| # | Step | File:line | What happens | Units |
|---|---|---|---|---|
| 1 | Fetch daily returns | `quant_queries.py:954` (`_fetch_returns_by_type`) | Pull `NavTimeseries.return_1d`, prefer `log`, fallback `arithmetic` | daily decimal |
| 2 | Sanitize | `quant_queries.py:720` (`_sanitize_returns`) | Drop NaN/Inf/zero-var funds | daily decimal |
| 3 | Align + trim 5Y | `quant_queries.py:1270-1280` | ffill align; trim to `cov_lookback_days` | daily decimal, T×N |
| 4a | THBB prior μ₀ | `quant_queries.py:798-852` (`_build_thbb_prior`) | `μ₀_i = w10·r10y_i + w5·r5y_i + weq·π_i`, π=γΣw_bench | annual decimal |
| 4b | Fetch horizons | `quant_queries.py:736-778` (`_fetch_return_horizons`) | Read `FundRiskMetrics.return_5y_ann`/`return_10y_ann` | annual decimal (verified via `_compute_annualized_return`, risk_calc.py:138-148, `total**(1/years)-1`) |
| 5 | Data view Q | `quant_queries.py:855-879` (`_build_data_view`) | `Q_i = daily_mean_1Y × 252`, `Ω_ii = σ²_ann / N_obs` | annual decimal (log-annualized if return_type='log') |
| 6 | IC views | `quant_queries.py:1057-1150` (`_build_ic_views`) | Pull `portfolio_views`, Idzorek Ω | annual decimal |
| 7 | BL posterior | `quant_queries.py:1616-1621` → `black_litterman_service.py:79` (`compute_bl_posterior_multi_view`) | Stack data + IC views; solve BL posterior with τ=0.05, Ω regularization | annual decimal |
| 8 | Fee adjustment | `quant_queries.py:1626-1642` | `μ_i -= expense_ratio_pct` (only if `config.fee_adjustment.enabled`) | annual decimal |
| 9 | → LP | `optimizer_service.py:55` (`compute_phase1_rucvar`) | `mu` consumed verbatim by `max μᵀw` | annual decimal |

**Regime service does NOT touch μ** — verified by grep: `quant_engine/regime_service.py` operates on covariance-conditioning and stress scoring only. H5 can be ruled out at design time; no instrumentation needed.

### A.3 τ (Black-Litterman tau)

`TAU_PHASE_A = 0.05` hardcoded at `black_litterman_service.py:49`. Phase A uses this fixed value. Adaptive τ=1/T exists in the **legacy** single-view path (`compute_bl_returns`, line 156) but that path is **not called** from `compute_fund_level_inputs` — only `compute_bl_posterior_multi_view` (multi-view, τ=0.05 fixed) is invoked.

### A.4 Dead / shadow code to confirm

- `fetch_bl_views_for_portfolio` (line **999**) returns legacy dict-format views. `_build_ic_views` (line **1057**) returns `View` dataclasses. Only the latter is consumed at line 1612. **Opus must confirm** `fetch_bl_views_for_portfolio` is not silently shadowing IC views via a second code path — grep usages across backend/.

### A.5 Strategic weights (π input)

`fetch_strategic_weights_for_funds` (line **1155-1210**) joins `StrategicAllocation` → `InstrumentOrg.block_id`. If Balanced's allocation blocks don't map to SPY/VTEB/GLD's `block_id`, their `w_benchmark` entries are 0 and π_i = 0 for those funds. Then `weq·π_i = 0` — which for a 1y_only fund means μ_prior_i = 0. Must instrument.

---

## Section B — Hypothesis Ranking (by likelihood × empirical fit)

Scored against the observed signal: VTEB (muni, r1Y=5.46%) beats SPY (r1Y=21.09%) in μᵀw maximization.

### H1 (HIGH) — THBB bucket collapse via NULL return_5y_ann/return_10y_ann

**Signature**: `_fetch_return_horizons` at `quant_queries.py:736-778` returns `{"5y": None, "10y": None}` for SPY/GLD (not VTEB — muni ETFs tend to have long histories) because either (a) their `FundRiskMetrics.calc_date` row is stale vs `as_of_date`, (b) `return_5y_ann`/`return_10y_ann` stored NULL by `global_risk_metrics` worker, or (c) the `FundRiskMetrics` row for the instrument was never computed. Funds without 5y/10y fall to `w_eq=1.0` (line 795). Then μ_prior_i = π_i only. If the Balanced strategic block for SPY has low weight, π_i is tiny.

**Why ranked highest**: asymmetric failure — equities (SPY) get dumped into 1y_only; bonds (VTEB) keep full THBB with stable 5y/10y means. Directly reproduces the observed "muni preferred over equity" bias.

**Observable in instrumentation**: `buckets["1y_only"]` >> expected; SPY/GLD in the `1y_only` list.

### H2 (HIGH) — Data view dominance swamped by THBB zero-prior

Per Ω math: data view Ω_ii ≈ σ²_SPY_ann / 252 ≈ (0.16)²/252 ≈ 1e-4 vs τΣ_ii = 0.05 × (0.16)² ≈ 1.3e-3 → data view is ~13× more certain than prior. If data view Q is correct (SPY daily_mean × 252 ≈ 0.19-0.21), posterior μ_SPY should be ~0.19-0.21 even if μ_prior=0.

**Candidate defect**: the data view Q is itself broken — for instance if `_build_data_view` tail slice (line 874) takes log-returns when THBB weights were computed on simple-compound r10y/r5y (risk_calc.py:148 uses simple compound). **Unit mismatch**: log-annualized daily mean vs simple-compound 5Y. For SPY+21% annual this is small (19% log ≈ 21% simple) but for extreme cases it compresses signal. Not primary cause but must instrument.

**Sub-hypothesis H2b**: if `return_type` fallback to `arithmetic` is hit and the cov/μ path mixes types silently.

**Observable**: log Q_data per asset, compare Q vs pre-blend prior, show posterior-prior delta.

### H3 (MEDIUM) — π (equilibrium) collapse via benchmark coverage hole

**Signature**: `fetch_strategic_weights_for_funds` returns `w_benchmark` with zeros for SPY/GLD because Balanced's `StrategicAllocation` blocks don't include the block SPY/GLD are tagged to in `InstrumentOrg`. Then π_i = γ·Σ·w_bench has near-zero rows for SPY/GLD. Combined with H1 (if those funds are in `1y_only`), μ_prior_i is ~0, and if data view Q path also has a bug, posterior collapses.

**Observable**: `w_benchmark[SPY] == 0`, `pi[SPY] ≈ 0`.

### H4 (LOW) — Ledoit-Wolf applied to μ

Grep `backend/` for `ledoit|shrinkage` on μ: `_apply_ledoit_wolf` at `quant_queries.py` operates on covariance only. LW is **not** applied to μ. Rule out via code archaeology, no instrumentation needed.

### H5 (RULED OUT) — Regime-conditioning μ collapse

Verified in A.2: `regime_service.py` touches covariance windowing and stress scoring, never μ. CVaR multipliers (RISK_OFF=0.85, CRISIS=0.70) enter at `cvar_service.py` on the tail scenarios, not on μ. Not in the μ → LP path.

### H6 (LOW) — Decimal/float cast regression (A15 class of bug)

`FundRiskMetrics.return_5y_ann` is NUMERIC → Python `Decimal`. At `quant_queries.py:770-771` we cast via `float(r5)`. If that cast path has a subtle bug (e.g. `decimal.Decimal("NaN")` propagating), `_build_thbb_prior` may silently receive zeros. Grep for `Decimal` in risk_calc dump paths. Low likelihood — there's an explicit None guard — but cheap to instrument by logging raw DB row.

**Final ranking for Opus to test**: **H1 > H2 > H3 > H6 > H4 (rule out) > H5 (ruled out)**.

---

## Section C — Instrumentation Plan

### C.1 Representative assets

Opus must resolve the `instrument_id` UUIDs for **SPY** (S&P 500 ETF), **VTEB** (Vanguard Tax-Exempt Bond ETF), **GLD** (SPDR Gold Shares) once at function entry to `compute_fund_level_inputs`, cache them in a local set `TRACE_IDS`, and check `fid in TRACE_IDS` at each log point below.

If any of the 3 is not in `available_ids` for a given run, log `mu_trace_asset_missing` with the reason (`excluded`, `not_in_universe`, `no_nav`) — that itself is diagnostic.

### C.2 Log points (file:line, event name, fields)

All logs use `structlog.get_logger()` and structured fields, no f-string interpolation. Bind run_id + profile + as_of_date at top of `compute_fund_level_inputs`.

| # | File:line (post-instrumentation) | Event name | Fields |
|---|---|---|---|
| L1 | `quant_queries.py:~778` (end of `_fetch_return_horizons`) | `mu_trace_horizons` | per trace asset: `instrument_id`, `ticker`, `calc_date_used`, `r5y_raw` (pre-cast, `repr`), `r10y_raw`, `r5y_final`, `r10y_final`, `has_5y`, `has_10y`, `fund_risk_metrics_row_found` (bool) |
| L2 | `quant_queries.py:~852` (end of `_build_thbb_prior`) | `mu_trace_thbb_per_fund` | per trace asset: `w10`, `w5`, `weq`, `r10y`, `r5y`, `pi_i` (from π = γ·Σ·w_bench slice), `mu_prior_i`, `bucket` (`10y+` / `5y+` / `1y_only`), `w_benchmark_i`, `gamma` |
| L3 | `quant_queries.py:~852` (aggregate) | `mu_trace_thbb_buckets` | `n_10y_plus`, `n_5y_plus`, `n_1y_only`, `n_total`, `mean_weights_used`, plus `trace_buckets = {SPY:..., VTEB:..., GLD:...}` |
| L4 | `quant_queries.py:~879` (end of `_build_data_view`) | `mu_trace_data_view` | per trace asset: `daily_mean`, `daily_var`, `tail_n`, `q_annualized`, `omega_diag`, `return_type_used` (log/arithmetic) |
| L5 | `black_litterman_service.py:~141` (inside `compute_bl_posterior_multi_view`, after solve) | `mu_trace_bl_posterior` | accept new optional kwarg `trace_indices: dict[str, int] \| None` from caller; if present, log per-asset `mu_prior_i`, `mu_post_i`, `delta`, `tau`, `omega_eps`, `n_views_total`, `n_view_groups` |
| L6 | `quant_queries.py:~1621` (immediately after `compute_bl_posterior_multi_view`) | `mu_trace_bl_result` | per trace asset: `mu_prior_i`, `mu_posterior_i`, `mu_delta`, `ic_views_count`, `data_view_dominant` (bool: `Ω_data_ii < trace(τΣ_ii)`) |
| L7 | `quant_queries.py:~1642` (after fee adjustment block) | `mu_trace_fee_adj` | per trace asset: `mu_pre_fee`, `expense_ratio_pct`, `mu_post_fee`, `fee_adjustment_enabled` |
| L8 | `optimizer_service.py` at RU CVaR LP entry (just before `prob.solve`) | `mu_trace_lp_input` | per trace asset: `mu_lp_i`, `cov_diag_i`, `w_lb_i`, `w_ub_i`, plus `mu_min`, `mu_max`, `mu_median`, `mu_argmax_idx` → to confirm nothing between quant_queries and LP mutated μ |

**Invariant check (add as assertion, not just log)**: at L8, assert `abs(mu_lp[i] - mu_from_quant_queries[i]) < 1e-12` for all trace assets — detects any silent transform between compute_fund_level_inputs return and RU LP input.

### C.3 Bucket-shame log

Add one-shot list log at `mu_trace_thbb_buckets`:
```
trace_equities_in_1y_only_bucket = [fid for fid in TRACE_IDS if bucket[fid] == "1y_only"]
```
If this list is non-empty for SPY or GLD post-A19, **H1 confirmed**.

### C.4 Legacy path shadow check

Add one boot-time log in `compute_fund_level_inputs` that emits:
```
{"event": "mu_trace_bl_path", "path": "multi_view_posterior", "legacy_path_called": False}
```
And grep for any `fetch_bl_views_for_portfolio` invocation in hot path. If invoked, log `legacy_path_called=True`.

---

## Section D — Success Criteria (when the fix is correct)

Run the same Balanced config post-A19 with real SPY/VTEB/GLD in universe, and the diagnostic logs must show:

1. **Bucket placement**: SPY, GLD, VTEB all in `10y+` bucket (weight 0.5/0.3/0.2). None in `1y_only`.
2. **μ_prior_i sanity floor** (THBB step):
   - SPY: **0.10 ≤ μ_prior ≤ 0.15** (0.5×0.13_r10 + 0.3×0.15_r5 + 0.2×π ≈ 0.11-0.14)
   - VTEB: **0.005 ≤ μ_prior ≤ 0.04** (muni 10Y ann ≈ 2-3%)
   - GLD: **0.05 ≤ μ_prior ≤ 0.12** (gold 10Y ann ≈ 6-8%)
3. **Data view Q sanity floor** (1Y annualized daily mean):
   - SPY: **0.17 ≤ Q ≤ 0.22**
   - VTEB: **0.03 ≤ Q ≤ 0.07**
   - GLD: **0.30 ≤ Q ≤ 0.40**
4. **BL posterior dominance**: data view Ω_ii ≈ 10×-20× tighter than τΣ_ii for equity funds → μ_post_SPY ≥ 0.15 with default IC view set (empty).
5. **Ordering invariant**: μ_post_GLD > μ_post_SPY > μ_post_VTEB (matches real 1Y ordering). If violated post-fix, μ is still broken.
6. **LP verdict**: Phase 1 max-μᵀw allocates non-trivial weight to SPY and GLD (>5% each for Balanced with no explicit exclusion). VTEB weight ≤ its implied bond-sleeve block cap, not dominant unless TOC caps force it.
7. **E[r] floor**: Balanced delivered E[r] at 7.5% CVaR ≥ **8%** (defensible vs 10-year SPY+bond 60/40 backtest).

If criterion 5 fails with criteria 1-4 passing, the defect is NOT in μ — escalate to cascade/cov.

---

## Section E — Sequencing Recommendation

Operator proposed: **A19 → A17.2 (NEW) → IWF+EFA benchmarks**.

**Confirmed, with one clarification.**

A19 dominates everything downstream because:

- **A17.2** (Growth residue — 3.5% wealth in `unclassified_equity`) depends on classifier coverage. If μ is broken, Growth's delivered return is unreliable regardless of classifier health. Fixing classifier without fixing μ ships an optimizer that still picks VTEB over SPY in the newly-classified blocks.
- **IWF + EFA benchmark expansion** multiplies the optimizer's attention surface. Expanding benchmarks while μ is collapsed steers the LP toward more — not fewer — bad allocations. Benchmark expansion must postdate a trusted μ.

**Recommended order**:
1. **PR-A19 (this spec)** — instrument only. Ship. Run Balanced + Conservative + Growth. Capture logs. Confirm hypothesis.
2. **PR-A19.1 (diagnose-driven fix)** — address whichever H1-H6 the logs confirm. Likely: backfill `return_5y_ann`/`return_10y_ann` for SPY/GLD + guard in `_fetch_return_horizons` + add `trace_indices` kwarg to multi-view BL permanently (not just for diagnosis — for audit trail of every future run).
3. **PR-A19.2 (cleanup)** — remove dead `fetch_bl_views_for_portfolio` if archaeology confirms it's unused; consolidate to one IC view builder.
4. **PR-A17.2** — Growth residue classifier work.
5. **IWF + EFA benchmark expansion** — only after A19.1 success criteria 1-7 hold on 3 profiles.

**Do not parallelize A17.2 with A19.** They both touch `_build_thbb_prior` input set (A17.2 via classification coverage changing `available_ids`; A19 via horizon NULLs). Serial merge keeps diagnostic signal clean.

**Do not start A17.2 speculatively in parallel on a sibling branch** — A19 logs may expose that A17.2's classifier work is moot (if the real driver is FundRiskMetrics row staleness, not classification).

---

## Section F — Non-goals for PR-A19

- No change to THBB weights (0.5/0.3/0.2).
- No change to τ (stays 0.05 Phase A).
- No change to BL regularization.
- No change to LP or cascade.
- No benchmark expansion.
- No changes to `_compute_annualized_return` (return_5y_ann/10y_ann semantics stay simple-compound decimal).

Pure instrumentation PR. If Opus is tempted to fix-in-place, defer to A19.1.

---

## Section G — Deliverable Checklist for Opus

- [ ] Archaeology confirmations: `fetch_bl_views_for_portfolio` usage grepped; regime_service confirmed μ-free; factor_model confirmed μ-free.
- [ ] 8 log points (C.2) wired.
- [ ] TRACE_IDS resolution helper added (graceful when missing).
- [ ] `trace_indices` kwarg plumbed through `compute_bl_posterior_multi_view`.
- [ ] Invariant assertion at L8.
- [ ] No production path changes (logs only + passthrough kwarg).
- [ ] Tests: 1 unit asserting TRACE_IDS missing → `mu_trace_asset_missing` fires but no exception. 1 unit asserting all L1-L7 events emit for a 3-asset fixture.
- [ ] Run Balanced / Conservative / Growth against current prod universe. Capture log dumps. Attach to PR description.
- [ ] PR description fills a table of observed vs expected for criteria D.2-D.7 per profile.

---

## Appendix — Files Opus will touch

Absolute paths:
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py` (L1-L4, L6, L7)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\black_litterman_service.py` (L5, `trace_indices` kwarg)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py` (L8 + invariant)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\tests\quant_engine\test_mu_trace_instrumentation.py` (new)

Reference docs to read before starting:
- `docs/reference/portfolio-construction-reference-v2-post-quant-upgrade.md` §3 (μ pipeline)
- `backend/tests/quant_engine/test_black_litterman_multi_view.py` (existing BL test patterns)

---

End of spec. Operator writes this file. Opus executes in fresh session.
