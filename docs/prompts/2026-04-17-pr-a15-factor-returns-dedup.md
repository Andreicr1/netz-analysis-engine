# PR-A15 — Factor Returns Dedup: Restore Factor-Model Fallback

**Branch:** `feat/pr-a15-factor-returns-dedup` (cut from `main` post-PR-A17.1 at commit `2dedf1e1`).
**Estimated effort:** ~1-1.5h Opus.
**Predecessors:** PR-A17.1 #201 (raised KAPPA_FALLBACK_THRESHOLD 5e4→1e5 to unblock cascade).
**Unblocks:** Reverting A17.1 threshold to 5e4 once factor fallback works again; PR-A9's three-tier guardrail operating as originally designed.

---

## Section A — Problem & root cause (fully diagnosed)

Since at least 2026-04-17 09:51 UTC (`docs/ux/logs.txt:245`), the factor-model fallback path has been silently dead:

```
factor_returns_fetch_failed      reason='Index contains duplicate entries, cannot reshape'
fundamental_factor_model_skipped reason='insufficient factor data'
```

Root cause is a **data bug in `allocation_blocks`**: three legacy block_id rows share benchmark_ticker with the current (fi_us_*) naming. When `build_fundamental_factor_returns` joins `benchmark_nav` × `allocation_blocks` and filters on specific tickers, the duplicate mappings produce Cartesian-multiplied rows, and `pd.pivot(index=nav_date, columns=ticker)` raises on the duplicate index.

### A.1 Empirical verification (live local DB, 2026-04-17)

Duplicate ticker→block mappings in `allocation_blocks`:

| benchmark_ticker | legacy block_id | current block_id | Data overlap |
|---|---|---|---|
| AGG | `fi_aggregate` | `fi_us_aggregate` | 5,670 benchmark_nav rows, **100% identical** |
| HYG | `fi_high_yield` | `fi_us_high_yield` | 4,781 rows, **100% identical** |
| TIP | `fi_tips` | `fi_us_tips` | 5,621 rows, **100% identical** |
| **Total** | | | **16,072 duplicate benchmark_nav rows** |

Downstream references to the legacy block_ids:

| Legacy block_id | `instruments_org` refs | `strategic_allocation` refs | `benchmark_nav` refs |
|---|---|---|---|
| fi_aggregate | 0 | 0 | 5,670 |
| fi_high_yield | 0 | 0 | 4,781 |
| fi_tips | 0 | 0 | 5,621 |

**Nothing except benchmark_nav references the legacy rows.** `strategic_allocation` migrated to regional naming (fi_us_*) presumably in a pre-A9 PR; the benchmark_ingest worker (lock 900_004) kept populating NAV for both naming schemes in lock-step (same Yahoo source → identical data per `nav_date`).

### A.2 Downstream impact

- `compute_fund_level_inputs` tries to fit the 8-factor model; fetch raises; catch logs warning and sets `fit = None`, `k_factors_effective = 0`
- PR-A9's three-tier κ guardrail then has no factor fallback available when κ ∈ [FALLBACK, ERROR) band
- PR-A17 expanded the universe from 95 → 135-146 funds, pushing κ from 2.4-3.0e4 (WARN band, sample-only) into 5.6-8.4e4 (fallback band)
- With factor fallback broken, the guard raised `IllConditionedCovarianceError` — production construction fully blocked
- PR-A17.1 (raising threshold 5e4 → 1e5) **masked** the factor fallback deadness by just accepting the less-conditioned sample Σ directly

**PR-A15 closes the masked issue. Post-merge, A17.1 threshold can be reverted to 5e4 (cleaner design, safety net restored).**

---

## Section B — Scope: one migration, zero code change

The fix is entirely data cleanup. The `build_fundamental_factor_returns` query is correct; it just operates on dirty data.

### B.1 New Alembic migration `0144_drop_legacy_allocation_block_aliases.py`

Deletes the legacy `allocation_blocks` rows AND their 16,072 duplicate `benchmark_nav` rows. Order matters (benchmark_nav first to avoid FK violation if a constraint exists; if no FK, order doesn't matter but keep this sequence for clarity):

```python
"""Drop legacy allocation_block aliases (fi_aggregate, fi_high_yield, fi_tips).

Three legacy block_ids shared benchmark_tickers with the current regional
naming (fi_us_aggregate, fi_us_high_yield, fi_us_tips), producing
duplicate (nav_date, ticker) rows in the factor_model_service pivot and
silently breaking the factor-model fallback path since at least
2026-04-17 09:51 UTC.

Verified 2026-04-17:
  - zero references in instruments_org
  - zero references in strategic_allocation
  - 100% identical data across legacy vs current benchmark_nav

This migration is data-only; no schema change.
"""
from alembic import op

revision = "0144_drop_legacy_allocation_block_aliases"
down_revision = "0143_cvar_profile_defaults"
branch_labels = None
depends_on = None

_LEGACY_BLOCKS = ("fi_aggregate", "fi_high_yield", "fi_tips")


def upgrade() -> None:
    # Step 1: remove duplicate benchmark_nav rows pointing at legacy blocks.
    op.execute(f"""
        DELETE FROM benchmark_nav
        WHERE block_id IN {_LEGACY_BLOCKS};
    """)
    # Step 2: remove the legacy allocation_blocks rows themselves.
    op.execute(f"""
        DELETE FROM allocation_blocks
        WHERE block_id IN {_LEGACY_BLOCKS};
    """)


def downgrade() -> None:
    # Cannot reliably reconstruct legacy rows from current state.
    # If rollback is required, restore from backup.
    pass
```

**Use `IN ('fi_aggregate','fi_high_yield','fi_tips')` with single quotes inside the f-string`** — the tuple literal in Python renders with parentheses suitable for SQL IN. Verify final SQL text with `op.execute` before running; escape carefully.

No `instruments_org` touch needed (zero refs). No `strategic_allocation` touch (zero refs). No code change.

### B.2 Defensive safeguard in `build_fundamental_factor_returns` (recommended)

Even post-migration, add a belt-and-suspenders `groupby + mean` before the pivot so a future regression (operator manually adds a duplicate benchmark_ticker, or an aliased allocation_block gets re-seeded) doesn't break factor fitting silently:

```python
# In backend/quant_engine/factor_model_service.py build_fundamental_factor_returns
# Immediately before `bench_pivot = bench_df.pivot(...)`:
bench_df = (
    bench_df
    .groupby(["nav_date", "ticker"], as_index=False)["return_1d"]
    .mean()
)
```

Only deduplicates identical-date-identical-ticker rows via mean (which is idempotent for identical values). If future duplicates have divergent values (data-quality issue), this takes the mean — not silently corrupt, but mergeable. Log a warning if the groupby reduces row count:

```python
_raw_rows = len(bench_df)
bench_df = bench_df.groupby(["nav_date", "ticker"], as_index=False)["return_1d"].mean()
if len(bench_df) != _raw_rows:
    logger.warning(
        "factor_returns_input_duplicates_deduped",
        raw_rows=_raw_rows,
        deduped_rows=len(bench_df),
        dropped=_raw_rows - len(bench_df),
    )
```

Same pattern for `macro_df` on `(obs_date, series_id)`.

### B.3 Revert A17.1 threshold (OPTIONAL, separate commit in same PR)

Once migration + smoke confirms factor fallback works, in `backend/app/domains/wealth/services/quant_queries.py`:

```python
# Before A15:
KAPPA_FALLBACK_THRESHOLD = 1e5   # temporary raise pending PR-A15 factor fallback revival

# After A15:
KAPPA_FALLBACK_THRESHOLD = 5e4   # PR-A9 original; factor fallback restored by PR-A15
```

Include the associated test update (parametrized κ regression) and the TODO-removal.

Only revert if F.2 smoke confirms factor fit succeeds. If factor fit still fails for some other reason, keep 1e5 and document the residual blocker.

---

## Section C — Tests

### C.1 Regression: factor returns query returns without raising

New test `backend/tests/quant_engine/test_factor_returns_dedup.py`:

```python
async def test_factor_returns_builds_without_pivot_error(db_session):
    """PR-A15 regression: build_fundamental_factor_returns must not raise
    'Index contains duplicate entries' post-migration. Would have caught the
    issue that silently broke factor_model fallback from pre-A17 onwards."""
    from datetime import date
    from quant_engine.factor_model_service import build_fundamental_factor_returns

    start = date(2020, 1, 1)
    end = date(2025, 12, 31)
    df = await build_fundamental_factor_returns(db_session, start, end)

    # Must return a non-empty DataFrame with unique index
    assert not df.empty, "factor_returns unexpectedly empty post-A15"
    assert df.index.is_unique, "factor_returns index has duplicates — B.2 safeguard failed"
    # At least the 8 expected factors (up to skipped count)
    assert df.shape[1] >= 5, f"Only {df.shape[1]} factor columns — too many skipped"
```

### C.2 Unit test: groupby dedup safeguard

```python
def test_pivot_safeguard_handles_synthetic_duplicates():
    """B.2 safeguard: if duplicates re-enter benchmark_nav, groupby+mean prevents pivot raise."""
    # Synthetic bench_df with duplicate (nav_date, ticker) rows — identical return values
    # Apply the groupby dedup; assert row count drops, no error raised
    ...
```

### C.3 Integration: live DB smoke

Post-migration, re-run A14 smoke. Expected log lines that SHOULD NOT appear:

```
factor_returns_fetch_failed         ← must NOT appear
fundamental_factor_model_skipped    ← must NOT appear
```

Expected log line that SHOULD appear (or continue appearing):

```
fund_level_inputs_computed_phase_a  covariance_source=sample (or factor_model when κ high)
```

Post-fix κ for the 3 canonical portfolios should still be in 5.6-8.4e4 range (universe didn't change). With factor fallback now available, if A17.1 threshold is reverted to 5e4, κ would trigger the `factor_fallback` branch → substitute factor covariance → proceed. Verify by querying `cascade_telemetry.statistical_inputs->>'covariance_source'` — should show `factor_model` for the 3 runs.

### C.4 A12.4 invariant preserved

All existing A12.4 regression tests (winner-selection cvar_within_limit) must remain green. Run the full `backend/tests/quant_engine/` suite post-fix. 230+ tests expected green.

---

## Section D — Pass criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | Migration 0144 applies cleanly | `alembic upgrade head` green |
| 2 | `allocation_blocks` has no legacy fi_aggregate / fi_high_yield / fi_tips rows | SQL SELECT |
| 3 | `benchmark_nav` no longer has 16,072 duplicate rows | SQL SELECT COUNT |
| 4 | `test_factor_returns_builds_without_pivot_error` passes | pytest |
| 5 | Live smoke: `factor_returns_fetch_failed` NOT emitted for any of 3 canonical builds | grep uvicorn logs |
| 6 | Live smoke: `covariance_source = factor_model` for at least one portfolio (if A17.1 threshold reverted), OR `covariance_source = sample` with factor fit available (if threshold retained) | SQL query on cascade_telemetry |
| 7 | All A12.4 / A14 / A17 regression tests remain green | full quant+wealth sweep |
| 8 | If A17.1 threshold reverted: κ 5.6-8.4e4 routes through factor fallback, cascade_summary unchanged from current post-A17.1 state | live smoke |

Per `feedback_dev_first_ci_later.md`: live DB smoke is the merge gate.

---

## Section E — Out of scope

- Fixing the `benchmark_ingest` worker to prevent future duplicate insertions (worker is idempotent on `(block_id, nav_date)` — the duplicates are a data-state bug, not a worker bug)
- Updating `benchmark_ticker` column to have a UNIQUE constraint on `allocation_blocks` (might conflict with future legitimate multi-block-per-ticker designs like regional sub-blocks; leave as soft convention)
- PR-A17.2 (Tiingo fund catalog ingestion for blue-chip bond ETFs) — separate
- PR-A16 (attribution log spam + taa_bands config miss) — separate
- Any change to PR-A17's classifier or PR-A17.1's κ threshold math

---

## Section F — Commit & PR

**Branch:** `feat/pr-a15-factor-returns-dedup`

**Commit message:**

```
fix(quant): dedup legacy allocation_block aliases — restore factor fallback (PR-A15)

allocation_blocks had 3 legacy rows (fi_aggregate, fi_high_yield, fi_tips)
sharing benchmark_ticker with their current fi_us_* counterparts. The JOIN
in build_fundamental_factor_returns produced Cartesian-multiplied rows and
pd.DataFrame.pivot raised 'Index contains duplicate entries', silently
killing the factor-model fallback path since at least 2026-04-17 09:51 UTC.

Empirical state pre-migration:
  - 3 legacy block_ids, zero references in instruments_org / strategic_allocation
  - 16,072 duplicate benchmark_nav rows (100% identical data to fi_us_* rows)
  - PR-A9's [5e4, 1e6) κ-fallback band unreachable in production

Fix: migration 0144 deletes the legacy rows + their duplicate benchmark_nav
rows. Defensive groupby+mean safeguard added to build_fundamental_factor_returns
so future regressions are logged (warn) not raised.

KAPPA_FALLBACK_THRESHOLD reverted from 1e5 → 5e4 (PR-A9 original). PR-A17.1
raised it as a temporary unblock pending this PR.

Post-fix smoke: factor_returns_fetch_failed no longer emitted; Phase 1/3
cascade proceeds with factor_model covariance when κ ∈ [5e4, 1e6).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR body:** include before/after SQL verification output for `allocation_blocks` + `benchmark_nav` row counts; pre/post log line diff showing `factor_returns_fetch_failed` disappearance; cascade_telemetry covariance_source for the 3 canonical smokes.

---

## Section G — Operating rules

1. **Migration only — no downgrade path.** If rollback needed, restore DB backup. Document this explicitly.
2. **Verify benchmark_nav data IS identical pre-migration** by re-running the diagnostic query (`SELECT COUNT ... INNER JOIN a USING (nav_date) WHERE a.return_1d IS NOT DISTINCT FROM b.return_1d`) before DELETE. If mismatch exists in any date, investigate — do NOT proceed blindly.
3. **Live smoke mandatory.** Factor-model fit on real post-A17 universe must succeed. If it fails for any OTHER reason (insufficient factor data despite query working), A15 is incomplete and threshold revert stays deferred.
4. **Threshold revert is optional.** If factor fit works but behaves unexpectedly post-revert (e.g., factor-cov itself has extreme κ > 1e6 for this universe), keep threshold at 1e5 and document.

---

**End of spec. Execute exactly. This closes the silent-death-of-factor-fallback that's been running since at least 09:51 UTC 2026-04-17 and re-enables the three-tier guardrail as PR-A9 designed it.**
