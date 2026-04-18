# PR-A19 — Evidence Capture (Observed vs Expected)

**Date**: 2026-04-17 20:22 GMT-3
**Backend**: localhost:8000, commit 66ffe236 (PR-A19 merged)
**Builds triggered**: Conservative, Moderate (Balanced), Growth — all 3 canonical portfolios in org `403d8392-ebfa-5890-b740-45da49c556eb`
**Log sink**: `/tmp/uvicorn.log`

---

## 1. Prod Path Confirmation

All 3 profiles emit `fund_level_inputs_computed_phase_a` with `mu_prior=historical_1y`. BL posterior / THBB / IC views **do not run** in current production.

Direct consequence: hypotheses H1 (THBB bucket collapse), H3 (π equilibrium collapse via benchmark coverage), H4 (LW on μ) from the original A19 spec are **moot for current prod**. They only matter if operator flips config to `mu_prior="thbb"` or `"bl_posterior"`.

Evidence:
```
mu_trace_bl_path  legacy_path_called=False  path=multi_view_posterior  trace_resolved=['GLD', 'VTEB']
mu_trace_bl_result  legacy_historical_1y=True  mu_prior_i=None  ic_views_count=0  mu_delta=None
```

---

## 2. Critical Finding: SPY Missing from Universe

`mu_trace_asset_missing: reason=not_in_candidate_ids_or_no_ticker_match  ticker=SPY` fires 3× (once per profile). SPY is NOT in the candidate universe for any of the 3 canonical portfolios.

This alone explains most of the "0.83% delivered E[r]" — the 21%-returning reference asset isn't even eligible. Root cause is upstream in `InstrumentOrg` selection / block-mapping, not in μ construction.

---

## 3. μ values are numerically healthy (for the assets that ARE in universe)

From `mu_trace_data_view` and `mu_trace_lp_input` (historical_1y = log-annualized 1Y daily mean × 252):

| Profile | n_funds | GLD μ | VTEB μ | μ ordering correct? | μ_max in universe | μ_median |
|---|---|---|---|---|---|---|
| Conservative | 135 | 0.0850 | 0.0416 | GLD > VTEB ✓ | 0.4153 (idx 86) | 0.0174 |
| Moderate | 145 | 0.0850 | 0.0416 | ✓ | 0.4153 (idx 86) | 0.0177 |
| Growth | 146 | 0.1342 | 0.0208 | ✓ | 0.5751 (idx 75) | 0.0607 |

Invariant check: **`invariant_ok=True`** for all 6 LP input traces. `mu_reference == mu_lp_i` to 1e-12. **No μ transform happens between `compute_fund_level_inputs` return and RU LP entry.** The "silent μ mutation" hypothesis is ruled out at the wire.

GLD understated vs real market (~3-4×): real 1Y = 36.64%, observed historical_1y ≈ 8.5-13.4%. Sub-hypothesis: 1Y window endpoints stale in `nav_timeseries`, or log-vs-simple compounding gap. Worth investigating but not root cause of operator complaint.

VTEB tracks reasonably (real 5.46%, observed 2.1-4.2%).

---

## 4. Real root cause of "0.83% delivered E[r]" — Cascade Fallback to Phase 3

From `phase_winner_selection_trace`:

| Profile | cvar_limit | min_achievable | Phase1 usable | Winning phase | winner_return | Status |
|---|---|---|---|---|---|---|
| Conservative | **5.0%** | **7.36%** | ❌ | `phase_3_min_cvar` | **2.09%** | degraded |
| Moderate | **7.5%** | **7.44%** | ✓ | `phase_1_ru_max_return` | **0.83%** | optimal |
| Growth | **10.0%** | **10.08%** | ❌ | `phase_3_min_cvar` | **0.48%** | degraded |

Observations:

- **Conservative & Growth**: CVaR constraint infeasible by narrow margin (2.36 pp over; 0.08 pp over). Cascade correctly falls through to Phase 3 min-variance — which picks **low-volatility funds (muni-like)** by design, not high-μ funds. Operator sees "2% return at 5% CVaR target" and reads it as μ collapse, but it's actually cascade correctness + too-tight CVaR for this universe.

- **Moderate**: Phase 1 within limit (7.44% ≤ 7.5%). winner_return = 0.83%. Here Phase 1 IS picking, but `mu_argmax_idx=86` (μ=0.4153) is NOT chosen — the solver diversifies because CVaR is binding at 7.5%. GLD (μ=0.085) gets some weight but the portfolio averages down to 0.83% because the high-μ fund at idx 86 is capped by CVaR contribution.

- **Note**: Conservative cvar_limit=**0.05** (5%), NOT the 2.5% PR-A18 recalibration. The tested portfolio still has its own override. Need to check `portfolio_calibration` vs defaults for these 3 specific portfolios.

---

## 5. Revised Hypothesis Ranking for PR-A19.1

Original H1-H6 ranking needs complete re-do now that `historical_1y` is confirmed as prod path.

| Rank | Hypothesis | Signal |
|---|---|---|
| **H_U1 HIGH** | SPY (and likely IVV/VTI/AGG/BND/IEF) missing from `InstrumentOrg` for `403d8392…`. Investigate approval_status + block mapping. | `mu_trace_asset_missing` fires for SPY |
| **H_U2 HIGH** | Mu_argmax fund (μ=0.41-0.57) is likely a 1Y outlier or data artifact. Not a real investable candidate. Need to resolve ticker for idx 86 (cons/mod) and idx 75 (growth). | argmax never GLD/VTEB; absurd μ for diversified equity |
| **H_CASCADE HIGH** | Operator-facing "0.83% delivered" IS cascade fallback to phase_3_min_cvar (not μ collapse). Conservative + Growth off by narrow CVaR margin. Need operator signal that distinguishes "phase 1 optimal" from "phase 3 fallback — CVaR infeasible". | winner_status=degraded + winning_phase=phase_3_min_cvar |
| **H_WINDOW MED** | GLD historical_1y 8.5% vs real 36.6%. Investigate nav_timeseries endpoint staleness + log-vs-simple compounding. | data_view q_annualized values |
| H1-H6 MOOT | THBB / BL posterior / IC views / LW on μ — all dark code in prod. | legacy_historical_1y=True everywhere |

---

## 6. Recommended Next Steps (PR-A19.1)

1. **Universe audit** — list `InstrumentOrg` for org `403d8392…` and verify SPY, IVV, VTI, AGG, BND, IEF, TLT, SHY, GLD present + `approval_status=approved` + `block_id` mapped.

2. **argmax resolver** — query DB for fund at position idx 86 (cons/mod universe) and idx 75 (growth universe). Log its ticker + raw nav_timeseries 1Y slice. If outlier: exclude via quality gate. If legitimate: feature, not bug.

3. **Cascade-aware operator signal** — when `winning_phase=phase_3_min_cvar AND cvar_within_limit=False`, surface dedicated signal: *"Your CVaR target of X% is infeasible with this universe. Achievable minimum is Y%. Delivered result is min-variance portfolio."* Prevent operator from interpreting phase_3 output as μ failure.

4. **GLD window investigation** — check `nav_timeseries` last row date for GLD, compare 252-day log sum × 252 vs simple compound. Likely small signal (log≈simple for 21%), but log it.

5. **Preserve instrumentation** — keep L1-L8 logs in prod indefinitely. They are cheap (6 events per build × 3 profiles = 18 structured lines) and essential for any future μ diagnostic.

6. **THBB branch latent bugs** — even if not in prod path today, H1 (bucket collapse) and H3 (π collapse) should be fixed before the operator flips `mu_prior="thbb"`. Leave as follow-up PR, lower priority.

---

## 7. What NOT to do

- Don't rewrite μ construction math. historical_1y is working correctly.
- Don't change cascade semantics. Phase 1 → 3 fallback is design-correct.
- Don't change CVaR defaults again. PR-A18 values are defensible for their universe; the problem is universe misses SPY/IVV, not that 7.5% is wrong for Balanced.
- Don't touch BL / THBB / LW code yet — dead path in prod.

---

## Raw event counts captured

```
3 mu_trace_asset_missing   (SPY × 3 profiles)
3 mu_trace_bl_path         (confirms legacy_historical_1y path × 3)
6 mu_trace_bl_result       (GLD + VTEB × 3)
6 mu_trace_data_view       (GLD + VTEB × 3)
6 mu_trace_fee_adj         (fee_adjustment_enabled=False — no fee applied)
6 mu_trace_lp_input        (GLD + VTEB × 3, invariant_ok=True × 6)
```

30 events total. Zero THBB logs (`mu_trace_horizons`, `mu_trace_thbb_per_fund`, `mu_trace_thbb_buckets`) — confirms THBB branch never entered.

End of evidence capture.
