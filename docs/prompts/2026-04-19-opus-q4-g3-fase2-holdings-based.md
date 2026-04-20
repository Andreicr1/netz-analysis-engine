---
pr_id: PR-Q4
title: "feat(wealth/g3-fase2): holdings-based attribution via N-PORT + matview + GICS diagnostic + 0133 conditional"
branch: feat/wealth-g3-holdings-based
sprint: S2
dependencies: [PR-Q3]
loc_estimate: 750
reviewer: wealth
---

# Opus Prompt — PR-Q4: G3 Fase 2 Holdings-Based Attribution

## Goal

Ship the second rail of the attribution cascade: holdings-based Brinson contribution via N-PORT data. This PR includes a GICS diagnostic step that determines whether migration 0133 (`sic_gics_mapping`) ships with this PR or is skipped. Runs in S2 with 3-4 day buffer to absorb the diagnostic.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §3.2 (Brinson math — refactored later in PR-Q5; this PR only aggregates holdings by sector)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §2 (GICS diagnostic SQL + decision tree A/B/C), §3 (matview DDL), §4.2 (query pattern)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §5 (GICS Diagnostic Protocol), §6 (Matview Refresh Final Decision)

## Sequence

1. **Day 1-2 S2:** run `backend/scripts/diagnose_nport_gics.py` against prod (read-only). Commit output as `docs/diagnostics/2026-XX-XX-nport-gics-coverage.json` + human-readable summary in PR description.
2. **Decide scenario:**
   - **Cenário A** (`pct_null < 10%`): skip migration 0133. Matview uses `industry_sector` directly (COALESCE to 'Unclassified').
   - **Cenário B** (`pct_null > 10%`, SIC >90% filled): commit migration 0133 + seed 1200 SIC→GICS rows. Matview LEFT JOINs `sic_gics_mapping`.
   - **Cenário C** (both null): abort 0133, flag wealth-architect, degrade F2 to `issuer_category × country` with `confidence='low'`.
3. **Implement** holdings-based rail + matview + worker refresh hook.

## Files to create

1. `backend/scripts/diagnose_nport_gics.py` — read-only runner for the 4 SQL blocks in data-layer spec §2.1. Outputs JSON + summary. Idempotent (no writes).
2. `docs/diagnostics/2026-XX-XX-nport-gics-coverage.json` — diagnostic artifact (also in PR description).
3. **Conditional on Cenário B:** `backend/alembic/versions/0133_sic_gics_mapping.py` — DDL per data-layer spec §2.3 + `op.bulk_insert()` of 1200 rows (seed sourced from MSCI/S&P public SIC→GICS 2023 mapping).
4. `backend/alembic/versions/XXXX_mv_nport_sector_attribution.py` — matview DDL per spec §6.1 of followup (uses COALESCE + LEFT JOIN conditional on Cenário B/C).
5. `vertical_engines/wealth/attribution/holdings_based.py` — reads matview, computes sector weights + AUM coverage + confidence score. Returns `HoldingsBasedResult`.
6. `backend/tests/vertical_engines/wealth/test_attribution_holdings.py` — ≥15 unit tests.
7. `backend/tests/integration/test_nport_matview_refresh.py` — ≥5 integration tests.

## Files to modify

1. `vertical_engines/wealth/attribution/service.py` — extend dispatcher to try holdings rail FIRST; fall back to returns-based rail if holdings unavailable or coverage <80%.
2. `vertical_engines/wealth/attribution/models.py` — add `HoldingsBasedResult`, `SectorWeight`, rail priority logic.
3. `backend/app/core/jobs/nport_ingestion.py` — add post-ingest matview refresh (FORA do advisory lock 900_018; separate session per spec §3.2 of data-layer).
4. `vertical_engines/wealth/dd_report/chapters/ch4_performance.py` — render holdings-based view when available; fall back to returns-based. Badge `HIGH CONFIDENCE — position-level` when holdings rail wins.

## Implementation hints

### Matview refresh hook

```python
# backend/app/core/jobs/nport_ingestion.py
async def run():
    got = await try_advisory_lock(900_018)
    if not got: return
    try:
        await ingest_nport_batches(session)
        await session.commit()
    finally:
        await release_advisory_lock(900_018)

    # Outside the lock
    async with get_session() as refresh_session:
        await refresh_session.execute(text(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_nport_sector_attribution"
        ))
        await refresh_session.commit()
```

### Holdings-based rail logic

```python
async def run_holdings_rail(request: AttributionRequest) -> HoldingsBasedResult | None:
    if not await has_recent_nport_filing(request.fund_cik, max_age_months=9):
        return None  # degrade to returns-based

    sectors = await fetch_sector_weights(request.fund_cik, request.period_start, request.period_end)
    coverage_pct = compute_aum_coverage(sectors)
    if coverage_pct < 0.80:
        return HoldingsBasedResult(degraded=True, reason="low_aum_coverage",
                                   coverage_pct=coverage_pct, ...)
    # Compute sector attribution contribution
    contributions = [(s.sector, s.weight * s.period_return) for s in sectors]
    confidence = coverage_pct
    return HoldingsBasedResult(sectors=sectors, contributions=contributions,
                               coverage_pct=coverage_pct, confidence=confidence,
                               degraded=False)
```

Note: this PR does NOT compute full Brinson-Fachler (allocation/selection/interaction) — that requires benchmark holdings and lands in PR-Q5. This PR computes only fund-side sector weights + contributions for rendering.

### Dispatcher priority

```python
async def compute(request):
    holdings = await run_holdings_rail(request)
    if holdings and not holdings.degraded:
        return AttributionResult(badge=RAIL_HOLDINGS, holdings_based=holdings, ...)
    returns = await run_returns_based_rail(request)
    if returns and not returns.degraded:
        return AttributionResult(badge=RAIL_RETURNS, returns_based=returns, ...)
    return AttributionResult(badge=RAIL_NONE, reason="no_rail_available")
```

## Tests

### Holdings rail (≥15)
- Fund with fresh N-PORT filing → holdings rail succeeds
- Fund with stale filing (>9 months) → returns None → dispatcher degrades to returns
- AUM coverage >80% → confidence = coverage_pct
- AUM coverage <80% → degraded with reason
- GICS sector aggregation: 3 holdings in same sector → sum weights correctly
- Cenário A (sector direct): matview query returns non-null sectors
- Cenário B (SIC→GICS fallback): missing `industry_sector` row resolves to `gics_sector` via JOIN
- Cenário C (both null): sector = 'Unclassified' placeholder, log warning
- Period boundary: only holdings within `[period_start, period_end]` counted
- Invalid fund_cik → returns None
- Concurrent fund requests: no shared state leak
- Idempotent: same `(fund_cik, period_start, period_end)` → same result
- Matview staleness: if matview older than 10 days, log warning
- Confidence score bounds: [0, 1]
- Rendering integration: `ch4_performance` renders sector table with 11 GICS sectors max

### Matview integration (≥5)
- REFRESH CONCURRENTLY completes without errors on test fixture
- UNIQUE INDEX covers all rows (no nulls after COALESCE)
- Refresh hook runs AFTER advisory lock release
- Refresh failure does not block next ingestion run
- Refresh duration logged and <5min on fixture

## Acceptance gates

- `make check` green
- Diagnostic script ran; scenario (A/B/C) explicitly documented in PR description
- If Cenário B: migration 0133 seed = exactly 1200 rows (assert in test)
- Matview UNIQUE INDEX verified (test that `REFRESH CONCURRENTLY` works)
- `nport_ingestion` worker refresh hook verified in integration test
- Performance: DD ch.4 render ≤2s p95 for 200-holdings fund
- Invariant scanner: no raw quant terms in rendered copy
- P5 idempotent: refresh hook safe to run multiple times

## Non-goals

- Do NOT implement full Brinson-Fachler (allocation/selection/interaction) — PR-Q5 scope
- Do NOT ingest benchmark holdings — PR-Q5
- Do NOT touch returns-based code from PR-Q3 beyond dispatcher priority update
- Do NOT build UI to select scenario manually — scenario is auto-determined

## Branch + commit

```
feat/wealth-g3-holdings-based
```

PR title: `feat(wealth/g3-fase2): holdings-based attribution via N-PORT + matview + GICS diagnostic`
