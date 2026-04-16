# PR-A8 — Universe Pre-Filter Layer 3 (Correlation Dedup)

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M)
**Branch:** `feat/pr-a8-correlation-dedup` (from `main` HEAD post PR-A7 merge)
**Scope:** Add Layer 3 of the pre-filter cascade — collapse highly-correlated peer funds via union-find clustering, keeping one representative per cluster (highest manager_score). Without this, CLARABEL receives 269-319 candidates that have pairwise ρ > 0.95 (many S&P 500 trackers, many aggregate bond funds), producing κ(Σ) ≈ 4.9e5-7.3e5 — orders of magnitude above the PR-A1 error threshold (1e4). All 3 portfolio builds post-A7 fail with `IllConditionedCovarianceError`.

## Empirical evidence from 3 builds post-PR-A7 (2026-04-16)

| Portfolio | N | κ(Σ) | Worst eigenvalues | Wall (ms) | Status |
|---|---|---|---|---|---|
| Conservative Preservation | 269 | 4.915e5 | 6.5e-6, 7.9e-6, 1.5e-5 | 7,292 | failed |
| Balanced Income | 269 | 4.915e5 | 6.5e-6, 7.9e-6, 1.5e-5 | 12,616 | failed |
| Dynamic Growth | 319 | 7.328e5 | 6.7e-6, 7.9e-6, 1.3e-5 | 11,637 | failed |

Post-PR-A7 is behaving correctly — the `status=failed` is the honest signal from PR-A1's `IllConditionedCovarianceError` guardrail. The 269 funds share too much common variance. Eigenvalue floor near 1e-6 means rank(Σ) << 269. Residual PCA would show ~1-5 dominant factors absorbing >95% variance.

Quant-architect's Layer 3 recommendation (brazenly honest version):
- Cluster candidates where pairwise rolling 1Y correlation > 0.95
- Pick top-1 per cluster via `manager_score` DESC
- Expected output cardinality: **80-150 funds** (50 na_equity_large trackers collapse to ~3-5)
- CLARABEL κ(Σ) drops to 10-1000 range → within tolerance

## Mandates

1. **`mandate_high_end_no_shortcuts.md`** — no skipped branches, no `# type: ignore`, 110+ wealth tests green before commit
2. **`feedback_retrieval_thresholds.md`** — do NOT treat 0.95 as a sacred absolute threshold. Start with 0.95 as default (quant-architect's expertise) but log the empirical percentile achieved per run so we can calibrate. If the default clusters < 3 groups on a real universe, threshold was too strict; if > 50% of pairs flagged, too loose.
3. **`feedback_smart_backend_dumb_frontend.md`** — SSE emits `{universe_size_before_dedup, universe_size_after_dedup, n_clusters_formed, threshold_used, pair_correlation_p95}` as numbers; frontend composes any human label in PR-A9
4. **DB-first hot path** — returns fetched via existing `_fetch_returns_by_type`; no external API
5. **Async-first** — `dedup_correlated_funds` is `async def`
6. **Deterministic** — same inputs → same output. Stable tiebreak: `manager_score DESC, instrument_id ASC`
7. **Single-purpose PR** — one file for the service, one for caller wiring, one test file. No frontend changes. No migrations expected.

## Section A — Correlation dedup service

### A.1 — New file `correlation_dedup_service.py`

Location: `backend/app/domains/wealth/services/correlation_dedup_service.py`.

Primary API:

```python
from __future__ import annotations

from typing import Any
from uuid import UUID
from datetime import date, timedelta

import numpy as np
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.services.quant_queries import _fetch_returns_by_type

logger: Any = structlog.get_logger()

# Defaults — document why each value was chosen
DEFAULT_CORR_THRESHOLD = 0.95       # quant-architect recommendation; tune via telemetry
DEFAULT_WINDOW_DAYS = 252           # 1Y daily returns window (not 5Y — dedup is about current structure)
MIN_OBSERVATIONS_FOR_DEDUP = 63     # 3M minimum; below this skip dedup for the instrument


class DedupResult(typing.NamedTuple):
    kept_ids: list[UUID]
    cluster_map: dict[UUID, int]    # instrument_id -> cluster_id (rep has same id as a member)
    n_clusters: int
    n_input: int
    threshold_used: float
    pair_corr_p50: float            # observed median pairwise correlation
    pair_corr_p95: float            # observed 95th percentile
    skipped_no_data: list[UUID]
    duration_ms: int


async def dedup_correlated_funds(
    db: AsyncSession,
    fund_ids: list[UUID],
    manager_scores: dict[UUID, float | None],
    *,
    threshold: float = DEFAULT_CORR_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of_date: date | None = None,
) -> DedupResult:
    """Collapse highly-correlated peer funds into cluster representatives.

    Algorithm:
      1. Fetch 1Y daily returns for each fund_id (reuse _fetch_returns_by_type)
      2. Align returns on common dates via forward-fill ≤ 2 days
      3. Compute N×N Pearson correlation matrix
      4. Union-find single-linkage clustering: two funds share a cluster iff
         their correlation exceeds ``threshold``. Transitive via union.
      5. Per cluster, elect representative: highest manager_score, tiebreak
         by instrument_id ASC (deterministic).
      6. Return kept_ids + cluster_map + observed percentiles for calibration.

    Performance budget:
      - N=320: correlation matrix ~50ms, clustering O(N²) pair scan ~50ms,
        total ~1-3s including DB fetch of returns.
      - Should NOT refetch returns if the caller already has them; accept
        optional ``returns_matrix`` parameter in a future refactor.

    Honest tradeoff: threshold=0.95 may be too permissive in bear regimes
    (everything correlates). Logs the observed p50 and p95 so operator
    can calibrate the threshold empirically after 2-3 runs.
    """
```

Implementation notes:

- **Returns fetching:** call `_fetch_returns_by_type(db, fund_ids, lookback_start, as_of_date)`. Compatible with how `compute_fund_level_inputs` does it — returns `dict[UUID, list[(date, return)]]`. Convert to aligned matrix.
- **Alignment:** same forward-fill ≤ 2 days policy as PR-A3 (see `factor_model_service.py:213` for the `factor_data_gap` audit pattern). If an instrument ends up with < `MIN_OBSERVATIONS_FOR_DEDUP` valid points after alignment, **skip it from clustering** and keep it as a singleton in output (conservative — err toward keeping). Log to `skipped_no_data`.
- **Correlation matrix:** `np.corrcoef(returns_matrix.T)` on the (T×N) array. Handle NaN by masking: use `numpy.ma.corrcoef` or manual pairwise with masked arrays. Zero-variance columns → corr undefined; treat as singleton.
- **Union-find:** classic implementation with path compression + union by rank. Iterate upper triangle `(i, j) where i < j` and union if `|corr[i,j]| > threshold`. Use `abs()` — negative correlations at -0.95 are as collinear as +0.95 for Σ conditioning. Clarify this choice in docstring.
- **Representative selection:** for each cluster, pick fund with max `manager_score` (None scores sort last). Tiebreak by UUID ASC via `sorted(cluster, key=lambda i: (-score_or_neg_inf(i), str(i)))[0]`.
- **Percentiles:** compute `np.percentile(upper_triangle, [50, 95])` on the raw correlation values (absolute) BEFORE clustering — gives observability into the universe's correlation structure.

### A.2 — Return contract

`DedupResult` is a `typing.NamedTuple` for frozenness + mypy. Fields already described above. `cluster_map` lets downstream observability see which funds were collapsed (for reporting / debugging). `skipped_no_data` lets caller log which instruments had insufficient observations.

### A.3 — Logging

Emit one structured log at function exit:

```python
logger.info(
    "correlation_dedup.completed",
    n_input=result.n_input,
    n_kept=len(result.kept_ids),
    n_clusters=result.n_clusters,
    threshold_used=result.threshold_used,
    pair_corr_p50=round(result.pair_corr_p50, 3),
    pair_corr_p95=round(result.pair_corr_p95, 3),
    duration_ms=result.duration_ms,
    skipped_no_data=len(result.skipped_no_data),
)
```

No audit event needed (it's telemetry, not state change).

## Section B — Caller wiring

### B.1 — `_run_construction_async`

File: `backend/app/domains/wealth/routes/model_portfolios.py` around line 1858-1990 (post Layer 0+2 load, pre `compute_fund_level_inputs`).

After `universe_funds = await _load_universe_funds(db, org_id, profile=profile, regime=current_regime)` and before the `fund_info / fund_blocks / fund_instrument_ids` loop, insert Layer 3:

```python
from app.domains.wealth.services.correlation_dedup_service import (
    dedup_correlated_funds,
)

fund_instrument_ids_raw = [uuid.UUID(f["instrument_id"]) for f in universe_funds]
manager_scores = {
    uuid.UUID(f["instrument_id"]): f.get("manager_score") for f in universe_funds
}

dedup = await dedup_correlated_funds(
    db,
    fund_instrument_ids_raw,
    manager_scores,
)

# Replace universe_funds with the deduped subset, preserving block_id + name
keep_set = set(str(uid) for uid in dedup.kept_ids)
universe_funds = [f for f in universe_funds if f["instrument_id"] in keep_set]
```

Expected cardinality drop: **269-319 → 80-150** (per quant-architect).

### B.2 — SSE metrics

In the SHRINKAGE phase event payload, surface dedup telemetry so the frontend can render it (PR-A9 will format):

```python
await _publish_phase(
    job_id,
    "SHRINKAGE",
    message="Stabilising covariance for the prevailing regime.",
    progress=0.25,
    metrics={
        "universe_size_before_dedup": dedup.n_input,
        "universe_size_after_dedup": len(dedup.kept_ids),
        "n_clusters": dedup.n_clusters,
        "threshold": dedup.threshold_used,
        "pair_corr_p50": dedup.pair_corr_p50,
        "pair_corr_p95": dedup.pair_corr_p95,
    },
)
```

Coordinate with the existing `builder.py` worker (PR-A5) — it already emits a SHRINKAGE phase; just extend the `metrics` dict. If the worker uses `execute_construction_run`, route the payload through that function's return shape instead (check `construction_run_executor.py:579` for the exact SSE path — add `dedup_metrics` to `statistical_inputs` JSONB).

### B.3 — Persist dedup trace

Add `dedup_trace` to `portfolio_construction_runs.statistical_inputs` JSONB (no migration — JSONB is open):

```python
statistical_inputs["dedup"] = {
    "threshold_used": dedup.threshold_used,
    "n_input": dedup.n_input,
    "n_kept": len(dedup.kept_ids),
    "n_clusters": dedup.n_clusters,
    "pair_corr_p50": dedup.pair_corr_p50,
    "pair_corr_p95": dedup.pair_corr_p95,
    "skipped_no_data": [str(uid) for uid in dedup.skipped_no_data],
}
```

## Section C — Threshold calibration observability

### C.1 — Telemetry query (run after PR-A8 smoke)

```sql
SELECT mp.display_name,
       pcr.statistical_inputs->'dedup'->>'n_input' as n_in,
       pcr.statistical_inputs->'dedup'->>'n_kept' as n_out,
       pcr.statistical_inputs->'dedup'->>'n_clusters' as n_clusters,
       pcr.statistical_inputs->'dedup'->>'pair_corr_p50' as p50,
       pcr.statistical_inputs->'dedup'->>'pair_corr_p95' as p95,
       pcr.status,
       pcr.failure_reason
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.started_at > NOW() - INTERVAL '1 hour'
ORDER BY pcr.started_at DESC;
```

Expected observations:
- `p50` likely 0.55-0.75 (moderate correlation across mixed universe)
- `p95` likely 0.92-0.97 (top-tier correlated peers)
- `n_kept / n_input` ratio: 25-50%
- `n_clusters` ≈ `n_kept` (1:1 when clustering works; less if orphans)

### C.2 — Threshold tuning note (do NOT implement in this PR)

If post-merge telemetry shows:
- All runs still `failed` with `IllConditionedCovarianceError` and `p95 < 0.90`: threshold 0.95 is too strict (we're not clustering enough). Flag PR-A9 to lower to 0.85.
- Output collapses to < 20 funds: threshold too loose. Flag PR-A9 to raise to 0.97.
- Mid-run during CRISIS regime, `p50` spikes to > 0.85: consider regime-conditioned threshold in PR-A10.

Document this explicitly in the commit message so operators know what to watch.

## Section D — Tests

Target: `backend/tests/wealth/test_correlation_dedup_service.py` (new file).

### D.1 — Synthetic: perfect duplicates collapse to 1

Seed 5 instruments with IDENTICAL return series (e.g., all +0.01 daily for 252 days). Assert `len(kept_ids) == 1` and that `cluster_map` maps all 5 to the same cluster_id.

### D.2 — Synthetic: uncorrelated funds all kept

Seed 5 instruments with mutually uncorrelated random returns (different RNG seeds, variance 0.01). Assert `len(kept_ids) == 5` and `n_clusters == 5`.

### D.3 — Representative election

Seed 3 instruments with identical returns but `manager_score` = [0.5, 0.9, 0.7]. Assert the survivor is the one with 0.9. Repeat with `manager_score` = [None, 0.5, None]: survivor is 0.5.

### D.4 — Tiebreak determinism

Seed 2 instruments with identical returns AND identical `manager_score`. Run twice. Assert same survivor both times (UUID ASC tiebreak).

### D.5 — Threshold sensitivity

Seed 4 instruments: A ≈ B with ρ=0.97, C ≈ D with ρ=0.88. With `threshold=0.95`: expect 2 kept (A or B, plus C and D separately). With `threshold=0.85`: expect 2 kept (A or B, C or D).

### D.6 — Negative correlation handling

Seed 2 instruments with ρ = -0.99 (inverted). Assert they ARE clustered together (|ρ| > threshold). Document this in the test.

### D.7 — Insufficient observations skip

Seed 3 instruments: 2 with 252 observations, 1 with 30 observations. Assert the 30-obs one lands in `skipped_no_data` and is kept as singleton (returned in `kept_ids` without being clustered).

### D.8 — Zero-variance column

Seed 1 instrument with constant return (0.00 every day) among others. Assert it does NOT crash correlation computation (would produce NaN); treated as singleton.

### D.9 — Integration test (docker-compose)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_dedup_live_db_produces_tractable_universe():
    """Post-dedup cardinality lands in CLARABEL's feasible band."""
    org_id = "403d8392-ebfa-5890-b740-45da49c556eb"
    async with async_session_factory() as db:
        universe = await _load_universe_funds(db, org_id, profile="moderate")
    fund_ids = [uuid.UUID(f["instrument_id"]) for f in universe]
    scores = {uuid.UUID(f["instrument_id"]): f.get("manager_score") for f in universe}

    async with async_session_factory() as db:
        result = await dedup_correlated_funds(db, fund_ids, scores)

    # Per quant-architect: Layer 3 should produce 80-150 candidates
    assert 50 <= len(result.kept_ids) <= 200, \
        f"Dedup produced {len(result.kept_ids)} funds, expected 50-200"
    # Percentile sanity
    assert 0.0 <= result.pair_corr_p50 <= 0.9
    assert result.pair_corr_p95 >= result.pair_corr_p50
```

### D.10 — Existing tests must still pass

Run `pytest backend/tests/wealth/ -q`. 104 tests from PR-A7 + any new ones from construction executor must remain green.

## Section E — Verification (manual, after all tests green)

### E.1 — Smoke against 3 portfolios

With docker-compose running, trigger builds for Conservative / Balanced / Dynamic Growth via the admin endpoint OR frontend Builder UI. Capture `portfolio_construction_runs` rows and run C.1 telemetry query.

Pass criteria:
- All 3 `status = succeeded`
- `weights_proposed` has 20-100 funds
- `optimizer_trace.solver` is `clarabel` (not `heuristic_fallback`)
- `statistical_inputs->dedup->n_kept` in [80, 150]
- `wall_clock_ms` in [45_000, 110_000]
- `failure_reason` is NULL

Fail criteria:
- Still `IllConditionedCovarianceError` — dedup wasn't aggressive enough. Investigate p95; if < 0.93, lower threshold to 0.85 and re-run manually (don't commit the change yet — discuss first).
- `status = degraded` with `heuristic_fallback` — CLARABEL is failing for another reason (not κ). Check `optimizer_trace.error`; likely a different numerical issue.
- `n_kept < 20` — over-clustering. Raise threshold to 0.97 and re-run.

### E.2 — Cardinality sanity

```sql
SELECT mp.display_name,
       pcr.statistical_inputs->'dedup'->>'n_input' as before,
       pcr.statistical_inputs->'dedup'->>'n_kept' as after,
       pcr.optimizer_trace->>'solver' as solver,
       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) as n_weights,
       pcr.wall_clock_ms
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.started_at > NOW() - INTERVAL '30 minutes'
ORDER BY pcr.started_at DESC;
```

Attach the output to the PR body.

## Section F — What NOT to do

- Do NOT cache the correlation matrix in Redis — dedup input changes per-run (universe_funds depends on profile + current manager_scores), cache complexity > compute savings
- Do NOT pre-compute dedup offline via worker — it's session-scoped and cheap (<3s)
- Do NOT change the threshold to something other than 0.95 in this PR — ship the default, then tune via Section C observability after 2-3 real runs
- Do NOT combine with Layer 2 (top-N per block) — keep cascade layers separate for auditability
- Do NOT mutate `universe_funds` in-place — create a new filtered list
- Do NOT skip the `abs()` on correlation — negative 0.99 is as colinear as positive 0.99 for Σ
- Do NOT add a new migration — `statistical_inputs` is JSONB, schema is open
- Do NOT run clustering before returns are fetched — batch fetch once, reuse
- Do NOT write frontend rendering for the dedup chip — PR-A9 scope
- Do NOT silently pass `dedup.kept_ids` if `n_kept < 2` — raise early ValueError that `_run_construction_async` surfaces as `failure_reason: 'dedup_collapsed_too_far'`

## Section G — Deliverables checklist

- [ ] Branch `feat/pr-a8-correlation-dedup` from `main`
- [ ] `correlation_dedup_service.py` with `dedup_correlated_funds` and `DedupResult`
- [ ] `_run_construction_async` (+ construction_run_executor if needed) wires Layer 3 between Layer 2 output and `compute_fund_level_inputs`
- [ ] SHRINKAGE SSE phase emits dedup metrics
- [ ] `statistical_inputs` persists `dedup` block
- [ ] `test_correlation_dedup_service.py` with 9 tests (D.1-D.9)
- [ ] Integration test (D.9) passes against docker-compose
- [ ] All 104+ existing wealth tests green
- [ ] `make lint` clean, `make typecheck` clean (zero `# type: ignore` introduced)
- [ ] Live smoke E.1 captured: 3 rows with `status=succeeded`, `solver=clarabel`, `n_weights>=20`
- [ ] Telemetry query E.2 attached to PR body
- [ ] Commit message includes observed p50, p95, n_input → n_kept ratios

## Reference files

- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:1092` (`compute_fund_level_inputs`) — call site downstream of Layer 3
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py` (search for `_fetch_returns_by_type`) — reuse this for fetching returns in dedup
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py:1818` (`_run_construction_async`) — Layer 3 injection point
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py:579` (`execute_construction_run`) — alternate injection point if SSE path flows through here
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\factor_model_service.py:213` (`factor_data_gap` audit pattern — same forward-fill ≤ 2 days policy)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\portfolios\builder.py` (PR-A5 worker — SSE phase emitter)

## Constants

```python
DEFAULT_CORR_THRESHOLD = 0.95       # absolute |ρ|
DEFAULT_WINDOW_DAYS = 252           # 1Y daily
MIN_OBSERVATIONS_FOR_DEDUP = 63     # 3M minimum
```

## Expected cardinality after dedup (current DB state, extrapolated)

| Block | Post-L2 | Expected post-L3 | Rationale |
|---|---|---|---|
| na_equity_large | 50 | ~5-8 | S&P 500 trackers heavily duplicated |
| fi_us_aggregate | 50 | ~8-12 | AGG-like funds cluster |
| alt_real_estate | 50 | ~10-20 | More strategy diversity (REITs, private, hybrid) |
| fi_us_high_yield | 50 | ~8-15 | Some dispersion, but correlated to HY index |
| na_equity_small | 50 | ~5-10 | Russell 2000 trackers |
| cash | 44 | ~3-5 | Money market funds all ≈ same |
| alt_gold | 26 | ~3-5 | Gold ETFs |
| **Total** | **~320** | **~80-150** | Target band |

κ(Σ) expected to drop from 4.9e5-7.3e5 (rejected) to ~100-5,000 (within tolerance after Ledoit-Wolf shrinkage).

---

**End of spec. Execute end-to-end. Report with: 3 portfolio rerun outputs + SQL of Section E.2 + test counts + commit SHA. Do NOT commit until all 3 smoke builds produce `status=succeeded` + `solver=clarabel`.**
