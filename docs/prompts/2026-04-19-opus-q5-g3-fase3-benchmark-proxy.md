---
pr_id: PR-Q5
title: "feat(wealth/g3-fase3): benchmark proxy attribution + canonical ETF map (0132)"
branch: feat/wealth-g3-benchmark-proxy
sprint: S3
dependencies: [PR-Q4]
loc_estimate: 320
reviewer: wealth
---

# Opus Prompt — PR-Q5: G3 Fase 3 Benchmark Proxy + Brinson-Fachler Wake-Up

## Goal

Ship the third rail of the attribution cascade: resolve each fund's `primary_benchmark` string to a canonical ETF via `benchmark_etf_canonical_map`, then run holdings-based attribution against that ETF's positions as benchmark. This closes the Brinson-Fachler circuit (fund holdings + benchmark holdings, no Bloomberg required).

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §3.2 (Brinson-Fachler refactor: allocation/selection/interaction)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §1 (migration 0132 DDL + seed + fuzzy match), §4.3 (join chain SQL)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-strategy.md` §4, §6 (integration, confidence badges)

## Files to create

1. `backend/alembic/versions/0132_benchmark_etf_canonical_map.py` — DDL per data-layer spec §1.2 + inline seed of 20 rows per §1.3. Creates `pg_trgm` extension if not exists.
2. `vertical_engines/wealth/attribution/benchmark_proxy.py` — resolver + proxy rail implementation.
3. `vertical_engines/wealth/attribution/brinson_fachler.py` — canonical Brinson-Fachler with both sides.
4. `backend/tests/vertical_engines/wealth/test_benchmark_proxy.py` — ≥10 tests.
5. `backend/tests/vertical_engines/wealth/test_brinson_fachler.py` — ≥8 tests.

## Files to modify

1. `vertical_engines/wealth/attribution/service.py` — dispatcher priority: HOLDINGS → PROXY → RETURNS → NONE. (IPCA rail placeholder until PR-Q9.)
2. `vertical_engines/wealth/attribution/models.py` — add `BenchmarkProxyResult`, `BrinsonResult` (with allocation/selection/interaction fields).
3. `vertical_engines/wealth/dd_report/chapters/ch4_performance.py` — render Brinson table when proxy rail wins + badge `MEDIUM CONFIDENCE — benchmark proxy`.

## Implementation hints

### Resolver (Python, 3-level fallback)

```python
async def resolve_benchmark(primary_benchmark: str | None, session) -> BenchmarkResolution:
    if not primary_benchmark or not primary_benchmark.strip():
        return BenchmarkResolution(match_type="null", proxy_ticker=None)

    # Level 1: exact alias
    result = await session.execute(text("""
        SELECT proxy_etf_cik, proxy_etf_series_id, proxy_etf_ticker, asset_class
        FROM benchmark_etf_canonical_map
        WHERE :name = ANY(benchmark_name_aliases)
          AND CURRENT_DATE BETWEEN effective_from AND effective_to
        LIMIT 1
    """), {"name": primary_benchmark})
    row = result.first()
    if row:
        return BenchmarkResolution(match_type="exact", **row._mapping)

    # Level 2: trigram fuzzy
    result = await session.execute(text("""
        SELECT proxy_etf_cik, proxy_etf_series_id, proxy_etf_ticker, asset_class,
               similarity(benchmark_name_canonical, :name) AS sim
        FROM benchmark_etf_canonical_map
        WHERE benchmark_name_canonical % :name
          AND CURRENT_DATE BETWEEN effective_from AND effective_to
        ORDER BY sim DESC LIMIT 1
    """), {"name": primary_benchmark})
    row = result.first()
    if row and row.sim > 0.7:
        return BenchmarkResolution(match_type="fuzzy", **row._mapping)

    # Level 3: asset class keyword classifier (Python)
    ac = classify_asset_class_keywords(primary_benchmark)
    if ac:
        return await resolve_by_asset_class(ac, session)

    return BenchmarkResolution(match_type="unmatched", proxy_ticker=None)
```

### Brinson-Fachler

```python
def brinson_fachler(
    fund_weights: dict[str, float],     # sector -> weight
    fund_returns: dict[str, float],     # sector -> period return
    bench_weights: dict[str, float],
    bench_returns: dict[str, float],
) -> BrinsonResult:
    sectors = set(fund_weights) | set(bench_weights)
    R_B = sum(bench_weights.get(s, 0) * bench_returns.get(s, 0) for s in sectors)
    allocation, selection, interaction = 0.0, 0.0, 0.0
    by_sector = {}
    for s in sectors:
        w_p = fund_weights.get(s, 0)
        w_b = bench_weights.get(s, 0)
        r_p = fund_returns.get(s, 0)
        r_b = bench_returns.get(s, R_B)  # if benchmark sector missing, use aggregate
        a = (w_p - w_b) * (r_b - R_B)
        sel = w_b * (r_p - r_b)
        i = (w_p - w_b) * (r_p - r_b)
        by_sector[s] = {"allocation": a, "selection": sel, "interaction": i}
        allocation += a
        selection += sel
        interaction += i
    return BrinsonResult(
        allocation_effect=allocation,
        selection_effect=selection,
        interaction_effect=interaction,
        by_sector=by_sector,
        total_active_return=allocation + selection + interaction,
    )
```

### Proxy rail

```python
async def run_proxy_rail(request):
    fund = await get_fund_metadata(request.fund_cik)
    resolution = await resolve_benchmark(fund.primary_benchmark, session)
    if resolution.match_type in ("null", "unmatched"):
        return None
    # Fetch proxy ETF holdings via Fase 2 query
    proxy_holdings = await fetch_sector_weights(resolution.proxy_etf_cik, ...)
    if not proxy_holdings:
        return None  # ETF has no N-PORT (BDC/MMF edge)
    fund_holdings = await fetch_sector_weights(request.fund_cik, ...)
    brinson = brinson_fachler(
        fund_weights={s.sector: s.weight for s in fund_holdings},
        fund_returns={s.sector: s.period_return for s in fund_holdings},
        bench_weights={s.sector: s.weight for s in proxy_holdings},
        bench_returns={s.sector: s.period_return for s in proxy_holdings},
    )
    return BenchmarkProxyResult(
        resolution=resolution,
        brinson=brinson,
        confidence=0.6 if resolution.match_type == "exact" else 0.4,
    )
```

### Dispatcher priority

```
HOLDINGS (position-level, coverage≥80%) → PROXY (Brinson with resolved ETF) → RETURNS → NONE
```

## Tests

### Benchmark proxy (≥10)
- Exact alias match for "S&P 500" → SPY
- Fuzzy match for "Standard & Poor's 500 Index" → SPY (similarity > 0.7)
- No match for garbage string → match_type="unmatched"
- NULL primary_benchmark → match_type="null"
- Asset class fallback for "Large Cap Blend Index" → SPY via keyword classifier
- Temporal versioning: `effective_to` in the past → not returned
- BDC proxy (no N-PORT holdings) → rail degrades
- ETF ticker verification: proxy_etf_cik matches sec_registered_funds row
- Multiple canonical candidates → best similarity wins
- Aliases array GIN index used (explain analyze shows `bitmap index scan`)

### Brinson-Fachler (≥8)
- Golden: known textbook example returns exact allocation/selection/interaction
- Total active return = sum of 3 effects (identity check)
- Fund sector absent from benchmark → allocation captures contribution
- Zero benchmark weight for sector → selection=0, interaction=0
- Zero fund weight for sector → selection=0, interaction=0
- Same weights fund and benchmark → allocation=0
- Same returns fund and benchmark → selection=0
- Deterministic: same inputs → same outputs

## Acceptance gates

- `make check` green
- Migration 0132 reversible (downgrade drops table + type; leaves pg_trgm)
- Seed = exactly 20 rows (test assertion)
- Coverage audit: run resolver against `sec_registered_funds` where `primary_benchmark IS NOT NULL` and assert ≥60% match rate exact+fuzzy (target 70%, tolerate 60% on first seed)
- DD ch.4 renders Brinson table with 3 effects + sector breakdown when PROXY rail wins
- Badge sanitization: no "brinson-fachler" in rendered copy; UI says "Why the manager beat/lagged: asset mix vs. stock picks vs. timing"
- Performance: proxy rail completes in <3s p95 for typical fund

## Non-goals

- Do NOT seed more than 20 rows — additional aliases go in follow-up audit-driven backlog
- Do NOT expose raw allocation_effect number in UI — sanitize as "Asset mix contribution"
- Do NOT implement IPCA rail — PR-Q9
- Do NOT touch Tiingo worker — PR-Q7

## Branch + commit

```
feat/wealth-g3-benchmark-proxy
```

PR title: `feat(wealth/g3-fase3): benchmark proxy attribution + canonical ETF map (0132)`
