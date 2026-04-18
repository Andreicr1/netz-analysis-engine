# PR-A20 — Universe Sync Canonical Backfill

**Date**: 2026-04-18
**Status**: SCOPED SPEC (backlog from PR-A19.1)
**Branch**: `feat/pr-a20-universe-sync-canonical`
**Predecessor**: PR #205 (A19.1) merged as commit 86b9fca1.

---

## 0. Context

PR-A19.1 migration 0146 was designed to backfill 10 canonical liquid-beta tickers into every org's `instruments_org`. Empirically it only backfilled 6 because 4 tickers (**IVV, BND, TLT, SHY**) were missing from upstream `instruments_universe`. A fifth ticker (**VTI**) is in the catalog but has zero `nav_timeseries` rows — functionally missing from the optimizer.

Per A19.1 evidence capture and canonical window audit (2026-04-18 01:15 UTC):

| Ticker | In catalog? | NAV rows | 1Y simple compound | Staleness |
|---|---|---|---|---|
| SPY | ✓ | 236 | 24.8% | 21 days |
| IVV | ✗ | — | — | — |
| VTI | ✓ | **0** | — | — |
| AGG | ✓ | 245 | 6.2% | 7 days |
| BND | ✗ | — | — | — |
| IEF | ✓ | 245 | 5.1% | 7 days |
| TLT | ✗ | — | — | — |
| SHY | ✗ | — | — | — |
| GLD | ✓ | 245 | 38.5% | 7 days |
| VTEB | ✓ | 236 | 5.9% | 21 days |

5 of 10 canonical liquid-beta tickers are operationally unavailable to the cascade. A19.1 success (Balanced 9.22% E[r]) was driven by SPY + AGG + IEF + GLD + VTEB alone. Adding the 5 missing tickers should further improve Conservative min_achievable_cvar (currently 7.14% vs 5% target → operator sees `cvar_infeasible_min_var`), particularly BND/TLT/SHY for low-tail duration exposure.

## 1. Scope

### Section A — catalog backfill

For **IVV, BND, TLT, SHY**: insert rows into `instruments_universe` with:
- Correct `asset_class` (fixed_income for BND/TLT/SHY; equity for IVV)
- `name` from Tiingo metadata or ETF issuer profile
- `instrument_id` via `gen_random_uuid()`
- Source attribution for audit

Preferred: extend the ingestion worker (`instrument_ingestion`, lock 900_010) to include a canonical seed list. Fallback: one-off migration.

### Section B — NAV ingestion trigger

For **VTI** (catalog-present, NAV-absent) and the 4 new tickers from Section A: trigger `instrument_ingestion` worker to pull daily OHLC from Tiingo for the trailing 5 years (`cov_lookback_days = 1260`). Verify ≥ 245 rows post-ingestion per ticker.

### Section C — re-apply 0146 logic

The A19.1 migration 0146 was idempotent via `ON CONFLICT DO NOTHING`. Once Sections A+B land, re-run the same logic (either as migration 0147 or one-off script) to backfill the 5 new tickers into every org's `instruments_org` with `approval_status='approved'` + block mapping.

Block mapping per A19.1 spec:
- IVV → `na_equity_large`
- VTI → `na_equity_large` (or `equity_us_broad` if block exists)
- BND → `fi_us_aggregate`
- TLT → `fi_us_treasury` (or `fixed_income_treasury_long` if exists)
- SHY → `fi_us_treasury` (or `fixed_income_treasury_short` if exists)

### Section D — verification

Re-run the 3 canonical portfolio builds. Expected improvements:
- **Conservative**: min_achievable_cvar drops below 5% (with SHY/BND adding low-tail duration) → flips from `cvar_infeasible_min_var` to `optimal`
- **Balanced**: delivered E[r] may rise 1-2pp from current 9.22% with additional diversification
- **Growth**: already optimal; expect minor E[r] change

## 2. Non-goals

- Do not rewrite `instrument_ingestion` worker architecture
- Do not change Tiingo provider contract
- Do not modify A19.1 migration 0146 (keep idempotent semantics)
- Do not add non-canonical tickers (stay within the 10-ticker set)
- Do not change `compute_fund_level_inputs` μ estimator (H_WINDOW investigation deferred — see §3)

## 3. Deferred (non-blocking for A20)

- **GLD 1Y μ discrepancy** (A19 logs showed 8.5-13%, direct DB AVG×252 gives 36.6%): semantic difference in `_build_data_view` tail slice vs full-window AVG. Not a blocker — μ ordering correct, A19.1 delivers institutional returns. Needs archaeology of `_build_data_view` slice semantics; open as separate A21 if operator re-raises.
- **NAV staleness** (SPY/VTEB 21 days, others 7 days): separate tiingo scheduler concern. Not blocking A19.1 success criteria.

## 4. Success criteria

| # | Metric | Threshold |
|---|---|---|
| S.1 | `instruments_universe` canonical coverage | 10/10 tickers present |
| S.2 | NAV rows per canonical ticker | ≥ 245 for trailing 1Y |
| S.3 | `instruments_org` coverage | 10/10 approved for every wealth org |
| S.4 | Conservative flip | `winner_signal: cvar_infeasible_min_var` → `optimal` at same CVaR 5% target |
| S.5 | Tests green | `make check` + new `test_canonical_ingestion_coverage.py` |

## 5. Sequencing

Sections A → B → C → D. Each lands in the same PR. Stop at D if S.4 fails — escalate to A21 (μ estimator investigation).

## Files likely touched

- `backend/app/domains/wealth/workers/instrument_ingestion.py` (worker extension)
- `backend/app/core/db/migrations/versions/0147_canonical_catalog_backfill.py` (new)
- `backend/app/core/db/migrations/versions/0148_canonical_org_backfill.py` (new)
- `backend/tests/wealth/test_canonical_ingestion_coverage.py` (new)
- `backend/scripts/pr_a20_trigger_canonical_ingestion.py` (new, one-off trigger)
