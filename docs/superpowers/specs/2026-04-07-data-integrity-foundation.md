# Sprint S1 — Data Integrity Foundation

**Date:** 2026-04-07
**Branch:** `feat/data-integrity-foundation`
**Origin:** Diagnostics by `financial-timeseries-db-architect` and `wealth-portfolio-quant-architect` (this conversation, 2026-04-07).

## Problem

Three independent P0 defects break replicability of risk metrics:

1. **P0-1 — `fund_risk_metrics` PK stomping.** Primary key is `(instrument_id, calc_date)`. Two writers (`run_global_risk_metrics`, `run_risk_calc`) `ON CONFLICT DO UPDATE SET organization_id = …`. Multiple tenants overwrite each other; the row's `organization_id` reflects whichever worker wrote last. Two reloads of the same DD page can show different Sharpe values without any recomputation.

2. **P0-2 — DD report ordering inverts freshness.** `quant_injection.py` orders `organization_id NULLS LAST` **before** `calc_date DESC`. An old org-scoped row from 30 days ago beats today's global row.

3. **P0-3 — `portfolio_nav_synthesizer` math errors.** Reads `nav_timeseries.return_1d` without filtering on `return_type`; sums log returns linearly as `Σ w·r` (mathematically invalid); renormalizes weights `weight_sum/active_weight` on missing-data days, distorting mandate weights and producing time-dependent NAV that depends on data-arrival timing.

## Scope

| Phase | Files | Deliverable |
|---|---|---|
| 1 | `backend/app/core/db/migrations/versions/0093_*.py`, `backend/app/domains/wealth/models/risk.py`, `backend/app/domains/wealth/workers/risk_calc.py` | Migration 0093 + composite-PK ORM model + 3 ON CONFLICT updates |
| 2 | `backend/vertical_engines/wealth/dd_report/quant_injection.py` | One-line ORDER BY fix |
| 3 | `backend/app/domains/wealth/workers/portfolio_nav_synthesizer.py` | Read `return_type`, log→arithmetic conversion, remove weight renormalization |
| Tests | `backend/tests/wealth/...` | Regression tests for each phase |

## Out of scope (deferred to S2-S5)

- Optimizer max-Sharpe / Phase 2 CVaR / regime multiplier propagation
- Ledoit-Wolf shrinkage branch fix
- Black-Litterman τ calibration
- GARCH long-run column
- Triple Sharpe unification across screener/risk_calc/DD
- FX in `mv_unified_funds.aum_usd`
- Outlier filter alignment

These have their own sprints planned (see diagnostic adendo).

## Migration design — Phase 1 critical detail

`fund_risk_metrics` is a TimescaleDB hypertable (`c3d4e5f6a7b8`) with `compress_segmentby='organization_id'` and a 30-day compression policy. Constraint changes require decompressing affected chunks first.

PK approach: PostgreSQL forbids `NULL` columns in `PRIMARY KEY`. Use a `UNIQUE INDEX … NULLS NOT DISTINCT` (PG 15+, available on Timescale Cloud PG 16) on `(instrument_id, calc_date, organization_id)`. With `NULLS NOT DISTINCT`, two `NULL` org rows for the same instrument/date are still treated as duplicate — exactly the semantics we want (one global row per instrument/date, plus N tenant rows).

Migration steps:
1. Decompress all chunks (idempotent via `if_compressed => true`).
2. `ALTER TABLE fund_risk_metrics DROP CONSTRAINT fund_risk_metrics_pkey`.
3. `CREATE UNIQUE INDEX ux_fund_risk_metrics_pk ON fund_risk_metrics (instrument_id, calc_date, organization_id) NULLS NOT DISTINCT`.
4. Compression policy survives — re-compression handled by background job.

Worker `ON CONFLICT` updates: change `index_elements=["instrument_id", "calc_date"]` → `["instrument_id", "calc_date", "organization_id"]`. PG 15+ matches the `NULLS NOT DISTINCT` index automatically when the column list matches.

ORM update: add `primary_key=True` to `organization_id` mapper (SQLAlchemy accepts nullable PK columns; identity-map works on the tuple).

## Definition of Done

- [ ] Migration 0093 applies cleanly on PG 16 with TimescaleDB.
- [ ] Two tenants writing the same `(instrument_id, calc_date)` coexist; global row also coexists.
- [ ] `quant_injection.gather_quant_metrics` returns the freshest row by `calc_date`, not the freshest org row.
- [ ] `portfolio_nav_synthesizer` converts `log → arithmetic` before linear weighting, and does not renormalize weights on missing-data days.
- [ ] Regression tests cover each phase.
- [ ] `make lint` and `mypy` pass on modified files.
- [ ] Two logical commits: (1) DB migration + model + worker upserts, (2) DD ordering + NAV synthesizer + tests.

## Follow-ups (S2-S5)

The diagnostic adendo from `wealth-portfolio-quant-architect` defines four follow-up sprints:

- **S2 — Optimizer Correctness**: Achados C, D, G, E
- **S3 — Statistical Inputs**: Achados B, A, F
- **S4 — Triple Sharpe + Cross-cutting**: unification + QW1/QW2/QW4/QW5
- **S5 — Audit & Quality**: I, H, J + survivorship + share-class dedup
