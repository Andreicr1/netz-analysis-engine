# PR-A9 — κ(Σ) Threshold Calibration + Factor-Cov Fallback

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M)
**Branch:** `feat/pr-a9-kappa-calibration` (from `main` HEAD post PR-A8 merge)
**Scope:** Recalibrate the κ(Σ) guardrail thresholds based on empirical evidence from PR-A8 smoke runs, and add automatic fallback to the PR-A3 fundamental factor-model covariance when sample Σ is ill-conditioned. Unlocks CLARABEL from the three portfolio builds that currently return `status=degraded` because post-dedup κ=2.4e4-3e4 exceeds the aspirational `KAPPA_ERROR_THRESHOLD=1e4`.

## Empirical evidence from PR-A8 smoke runs (2026-04-16)

All 3 portfolios post-dedup (threshold 0.95):

| Portfolio | n_input → n_kept | κ(Σ) observed | wall (ms) | status |
|---|---|---|---|---|
| Conservative | 270 → 92 | ~2.4e4 | 4,462 | degraded |
| Balanced | 270 → 92 | ~2.4e4 | 5,784 | degraded |
| Dynamic Growth | 320 → 95 | ~3.0e4 | 6,009 | degraded |

All 3 hit `IllConditionedCovarianceError`. Threshold 1e4 set in PR-A1 was aspirational — chosen before empirical evidence of real institutional universes. T/N ratio ≈ 930/92 ≈ 10 is borderline for sample covariance estimation, and even post-dedup the residual market factor loading creates legitimate conditioning in the 1e3-1e5 band.

**Academic reality check:** For sample covariance in finance with T/N ~ 10, κ in the 1e4-1e5 range is normal. Aspirational bounds ≤ 1e4 apply to over-sampled regimes (T/N > 50) or factor-shrunk estimators. Institutional practice tolerates κ up to 1e5-1e6 when paired with aggressive shrinkage or factor-model substitution.

## Mandates

1. **`mandate_high_end_no_shortcuts.md`** — no threshold bumps without empirical + literature justification; no silent fallbacks
2. **`feedback_retrieval_thresholds.md`** — κ thresholds calibrated from observed distribution, not pulled from thin air
3. **`feedback_smart_backend_dumb_frontend.md`** — metrics emit numeric κ and the decision taken (`sample`/`factor_fallback`/`rejected`); frontend renders human label in PR-A10
4. **Preserve existing PR-A3 Hybrid Factor Model work** — `assemble_factor_covariance` already PSD-clamped; reuse, don't reimplement
5. **One PR, two commits** — (1) threshold recalibration + fallback wiring, (2) smoke validation. No migrations.

## Section A — Threshold recalibration

### A.1 — New values

File: `backend/app/domains/wealth/services/quant_queries.py:146-147`.

```python
# Before (PR-A1 aspirational):
KAPPA_WARN_THRESHOLD = 1e3
KAPPA_ERROR_THRESHOLD = 1e4

# After (PR-A9 empirical + literature):
KAPPA_WARN_THRESHOLD = 1e4    # log warning, still proceed with sample Σ
KAPPA_FALLBACK_THRESHOLD = 5e4  # switch to factor-model cov, still proceed
KAPPA_ERROR_THRESHOLD = 1e6   # raise IllConditionedCovarianceError only at truly pathological values
```

Three-tier ladder instead of two-tier. Rationale:
- **κ < 1e4**: pristine sample Σ, proceed silently
- **1e4 ≤ κ < 5e4**: log warning, proceed with sample Σ (matches current empirical band 2.4e4-3e4)
- **5e4 ≤ κ < 1e6**: sample Σ is too collinear — fall back to PR-A3 factor covariance, which has its own PSD floor
- **κ ≥ 1e6**: truly pathological (numeric failure territory) — raise error

### A.2 — Docstring update

`IllConditionedCovarianceError` docstring currently at line 152-157 says "κ > 1e4". Update to "κ > KAPPA_ERROR_THRESHOLD (1e6) — pathological rank deficiency, not recoverable". Make explicit that the two intermediate thresholds are recoverable.

### A.3 — `check_covariance_conditioning` function

Locate the function at `quant_queries.py:538` (the one that raises or warns today). Restructure:

```python
class CovarianceConditioningResult(typing.NamedTuple):
    kappa: float
    decision: Literal["sample", "factor_fallback", "rejected"]
    warn: bool
    min_eigenvalue: float


def check_covariance_conditioning(
    cov_matrix: npt.NDArray[np.float64],
) -> CovarianceConditioningResult:
    """Evaluate κ(Σ) and recommend a decision.

    Returns a decision enum — caller applies it. Does NOT raise for recoverable
    cases (factor_fallback). Raises IllConditionedCovarianceError only for
    κ >= KAPPA_ERROR_THRESHOLD (1e6).
    """
    eigvals = np.linalg.eigvalsh(cov_matrix)
    min_eig = float(eigvals.min())
    max_eig = float(eigvals.max())
    kappa = max_eig / max(min_eig, 1e-12)

    if kappa >= KAPPA_ERROR_THRESHOLD:
        raise IllConditionedCovarianceError(
            f"κ(Σ)={kappa:.3e} exceeds pathological threshold "
            f"({KAPPA_ERROR_THRESHOLD:.0e}); rank deficient, not recoverable.",
        )
    if kappa >= KAPPA_FALLBACK_THRESHOLD:
        return CovarianceConditioningResult(
            kappa=kappa, decision="factor_fallback", warn=True, min_eigenvalue=min_eig,
        )
    if kappa >= KAPPA_WARN_THRESHOLD:
        return CovarianceConditioningResult(
            kappa=kappa, decision="sample", warn=True, min_eigenvalue=min_eig,
        )
    return CovarianceConditioningResult(
        kappa=kappa, decision="sample", warn=False, min_eigenvalue=min_eig,
    )
```

Existing callers of the old function must be updated to consume the `decision` + handle `factor_fallback`.

## Section B — Factor-model fallback wiring

### B.1 — Compute factor cov eagerly (or lazily?)

PR-A3 already produces `FundamentalFactorFit` inside `compute_fund_level_inputs` (quant_queries.py:1219). The factor covariance `Σ_factor = B·Σ_f·B' + D_residual` is assembled via `assemble_factor_covariance(fit)`.

Decision: **lazy** — only assemble factor cov when `check_covariance_conditioning(sample_cov).decision == "factor_fallback"`. Avoid wasted work when sample Σ is acceptable.

Edit `compute_fund_level_inputs` so that after the Ledoit-Wolf shrinkage step produces the candidate Σ, the conditioning check runs:

```python
sample_cov = _apply_ledoit_wolf(returns_matrix, ...)  # current code
cond = check_covariance_conditioning(sample_cov)

if cond.decision == "factor_fallback":
    # Use PR-A3's assembled factor covariance instead of sample Σ
    from backend.quant_engine.factor_model_service import assemble_factor_covariance
    cov_matrix = assemble_factor_covariance(factor_fit)
    # Re-verify the factor-based cov is not itself pathological
    factor_cond = check_covariance_conditioning(cov_matrix)
    if factor_cond.decision != "sample":
        raise IllConditionedCovarianceError(
            f"Both sample (κ={cond.kappa:.2e}) and factor (κ={factor_cond.kappa:.2e}) "
            f"covariances are ill-conditioned.",
        )
    covariance_source = "factor_model"
else:
    cov_matrix = sample_cov
    covariance_source = "sample"
```

Add `covariance_source` + `kappa_sample` + `kappa_factor` (if used) to `FundLevelInputs.inputs_metadata` so it persists in `statistical_inputs` and is auditable.

### B.2 — Safety constraint

If `factor_fit.k_factors_effective == 0` (all 8 factors were skipped in PR-A3), factor fallback is not available. In that case, propagate the sample κ to the error path. The audit event `factor_skipped` count from PR-A3 already captures this state.

## Section C — SSE telemetry

### C.1 — Metrics payload

In the SHRINKAGE phase event (`_run_construction_async` or `construction_run_executor`), extend the existing metrics dict:

```python
metrics={
    ...  # existing dedup metrics from PR-A8
    "kappa_sample": float(cond.kappa),
    "covariance_source": covariance_source,  # "sample" | "factor_model"
    "kappa_final": float(final_cond.kappa),  # after any fallback
}
```

Frontend in PR-A10 will render "conditioning: good / acceptable / fallback applied" labels. This PR does NOT modify the frontend.

### C.2 — Persist in `statistical_inputs`

`FundLevelInputs.inputs_metadata` already persists. Just ensure new fields flow through.

## Section D — Ledoit-Wolf shrinkage diagnostic (observability only)

Per the empirical sweep (threshold 0.95 → n=92 → κ=2.4e4), Ledoit-Wolf's default auto-intensity might be producing weak λ when sample correlations are already moderate. Add a single log line at LW completion:

```python
logger.info(
    "ledoit_wolf.shrinkage_completed",
    lambda_optimal=float(lw.shrinkage_),
    n_funds=int(returns_matrix.shape[1]),
    t_observations=int(returns_matrix.shape[0]),
    kappa_pre=float(...) if possible,   # optional, if we can compute cheaply
    kappa_post=float(cond.kappa),
)
```

If telemetry shows `lambda_optimal < 0.1` consistently with high κ, PR-A10 will introduce a `shrinkage_intensity_override` in portfolio_calibration (the column already exists — `shrinkage_intensity_override` per migration 0xxx). Do **not** wire that override in this PR.

## Section E — Tests

Target: extend `backend/tests/wealth/test_quant_queries_conditioning.py` (if exists) or `backend/tests/quant_engine/test_covariance_conditioning.py` (new).

### E.1 — Threshold enum boundary tests

Feed synthetic `cov_matrix` with known κ at each boundary:
- κ=500 → decision=`sample`, warn=False
- κ=5e3 → decision=`sample`, warn=True
- κ=1e5 → decision=`factor_fallback`, warn=True
- κ=5e6 → raises `IllConditionedCovarianceError`

Construct via `np.diag([1.0, 1.0/kappa, 1.0])` and pad — deterministic κ.

### E.2 — Fallback integration test

Mock `_apply_ledoit_wolf` to return a high-κ sample cov. Mock `assemble_factor_covariance` to return a well-conditioned factor cov. Assert `compute_fund_level_inputs`:
- Uses factor cov as `cov_matrix`
- Sets `inputs_metadata.covariance_source == "factor_model"`
- Does NOT raise

### E.3 — Both ill-conditioned test

Both sample and factor covs high-κ (> 1e6). Assert `IllConditionedCovarianceError` raised with message citing both values.

### E.4 — Factor fallback disabled when k_factors_effective=0

Mock `factor_fit` with `k_factors_effective=0`. High-κ sample. Assert error is raised (no fallback attempted).

### E.5 — Existing PR-A3 / PR-A8 tests remain green

Run `pytest backend/tests/wealth/ backend/tests/quant_engine/ -q`. All 112+ tests green before commit.

## Section F — Verification (manual, after all tests green)

### F.1 — Smoke against 3 portfolios

Trigger builds via admin endpoint or Builder UI. Capture run output:

```sql
SELECT mp.display_name,
       pcr.status,
       pcr.optimizer_trace->>'solver' as solver,
       pcr.statistical_inputs->'dedup'->>'n_kept' as n_kept,
       pcr.statistical_inputs->>'covariance_source' as cov_src,
       pcr.statistical_inputs->>'kappa_sample' as kappa_s,
       pcr.statistical_inputs->>'kappa_final' as kappa_f,
       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) as n_weights,
       pcr.wall_clock_ms
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.started_at > NOW() - INTERVAL '30 minutes'
ORDER BY pcr.started_at DESC;
```

### F.2 — Pass criteria

All 3 portfolios:
- `status = succeeded` (not `degraded`)
- `solver = clarabel` (not `heuristic_fallback`)
- `n_weights >= 20`
- `covariance_source` may be either `sample` or `factor_model` — both valid
- `kappa_sample` in [1e3, 1e5] (empirically expected band)
- `wall_clock_ms` in [45_000, 120_000]

### F.3 — Fail criteria (discuss before committing)

- All 3 `covariance_source = factor_model` with `kappa_sample > 1e5`: sample Σ is systematically worse than expected; investigate whether Ledoit-Wolf is producing λ < 0.05 (too weak). Consider raising minimum λ floor.
- `weights_proposed` < 20 even with CLARABEL solver: downstream optimizer constraints over-tight; flag for PR-A10.
- Any run hits `KAPPA_ERROR_THRESHOLD (1e6)`: unexpected; dump raw returns + factor_fit to understand.

## Section G — What NOT to do

- Do NOT widen thresholds without the three-tier ladder — a single bump from 1e4 to 1e6 loses the graceful fallback opportunity
- Do NOT remove `KAPPA_ERROR_THRESHOLD` entirely — 1e6 is still a pathological guard
- Do NOT wire `shrinkage_intensity_override` in this PR — the calibration column exists but its use is PR-A10
- Do NOT change Ledoit-Wolf's target from `_apply_ledoit_wolf`'s current single-index — it's fine; the issue is threshold, not shrinkage
- Do NOT rebuild factor covariance if PR-A3's `factor_fit` is already computed — reuse
- Do NOT patch `assemble_factor_covariance` — PR-A3's PSD floor is correct; just call it
- Do NOT silently swallow the `IllConditionedCovarianceError` when both covs fail — fail loud, operator needs to know
- Do NOT skip audit events — `covariance_source` changes are auditable decisions
- Do NOT add migration — `statistical_inputs` is JSONB, schema is open

## Section H — Deliverables checklist

- [ ] Branch `feat/pr-a9-kappa-calibration` from `main`
- [ ] `quant_queries.py:146-147`: three-tier thresholds
- [ ] `check_covariance_conditioning` returns `CovarianceConditioningResult` enum
- [ ] `compute_fund_level_inputs` wires factor-cov fallback via `decision == "factor_fallback"`
- [ ] SHRINKAGE SSE emits `kappa_sample`, `kappa_final`, `covariance_source`
- [ ] `FundLevelInputs.inputs_metadata` persists same fields
- [ ] `test_covariance_conditioning.py` with 5 tests (E.1-E.5)
- [ ] All existing wealth + quant_engine tests green
- [ ] `make lint` clean, `make typecheck` clean
- [ ] Live smoke F.1: 3 rows with `status=succeeded`, `solver=clarabel`, `n_weights>=20`
- [ ] Commit message lists the 3 runs' κ_sample + covariance_source + n_weights

## Reference files

- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:146-147` (threshold constants)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:152-172` (IllConditionedCovarianceError + current two-tier check)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:538` (`check_covariance_conditioning`)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:1092-1500` (`compute_fund_level_inputs` — factor fallback injection site)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\factor_model_service.py` (PR-A3 `assemble_factor_covariance` — reuse)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\models\allocation.py` (PortfolioCalibration — `shrinkage_intensity_override` column for PR-A10 context)

## Constants summary

```python
# PR-A9
KAPPA_WARN_THRESHOLD = 1e4       # up from 1e3 (PR-A1)
KAPPA_FALLBACK_THRESHOLD = 5e4   # new tier — switch to factor cov
KAPPA_ERROR_THRESHOLD = 1e6      # up from 1e4 (PR-A1) — pathological only
```

## Expected outcome (empirical prediction)

Post PR-A9, the 3 portfolios:
- Conservative/Balanced: κ_sample ≈ 2.4e4 → within WARN band → `decision=sample`, `warn=True` → CLARABEL proceeds with LW-shrunk sample Σ
- Dynamic Growth: κ_sample ≈ 3e4 → same band → same path
- If any edge case hits κ > 5e4, factor fallback kicks in transparently

All 3 should reach `status=succeeded` with `solver=clarabel`.

---

**End of spec. Execute end-to-end. Report with: 3 portfolio rerun outputs + SQL of Section F.1 + test counts + commit SHA. Do NOT commit until F.2 pass criteria are verified on live DB.**
