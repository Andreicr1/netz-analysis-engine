---
title: "refactor: Fund Data Percentage Normalization & Per-Type Column Organization"
type: refactor
status: partially_completed
date: 2026-04-04
last_updated: 2026-04-04 18:45
---

# Fund Data Percentage Normalization & Per-Type Column Organization

## Implementation Status (2026-04-04)

- **Phase 1 (Broken Consumers):** COMPLETED. Scoring, Portfolio, Fee Drag, Watchlist, and Catalog filters now correctly interpret pure decimal fractions.
- **Phase 2 (Outlier Cleaning):** COMPLETED. Nulled out 51 rows with ER > 100% in SEC source tables. Audited moderate outliers.
- **Phase 3 (Backfill):** COMPLETED. Audited `instruments_universe` attributes; no outliers found in existing imports.
- **Phase 4 (Refresh):** COMPLETED. `mv_unified_funds` refreshed.
- **Phase 5 (Column Organization):** COMPLETED.

## Overview

The fund data layer stores percentage values as **pure decimal fractions** (0.015 = 1.5%) across all source tables, which is correct. However, multiple downstream consumers assume **human-readable percentages** (1.5 = 1.5%), causing scoring, portfolio construction, fee analysis, and watchlist detection to silently produce wrong results. Additionally, per-fund-type column organization is needed to present each fund type's relevant data cleanly.

This is a data integrity refactor, not a feature. Every fund score, fee drag ratio, and expense filter in the system is currently broken.

## Problem Statement

### The Percentage Mismatch

All SEC data sources (RR1, XBRL OEF, N-CEN) store percentages as **pure decimal fractions**:
- `expense_ratio_pct = 0.0003` means 0.03% (Vanguard VOO)
- `avg_annual_return_1y = 0.1636` means 16.36%
- `management_fee_pct = 0.0018` means 0.18%

The DB faithfully stores these fractions. The frontend `formatPercent()` correctly handles them (Intl.NumberFormat `style: "percent"` multiplies by 100). DD report `sec_injection.py` correctly converts `x100` before LLM rendering.

**But 5+ consumers assume human-readable percentages:**

| Consumer | Code | Expects | Gets | Result |
|---|---|---|---|---|
| Scoring fee_efficiency | `100 - er * 50` | 1.5 (= 1.5%) | 0.015 | Score 99.925 (all funds ~100) |
| Portfolio fee adjustment | `er / 100.0` | 1.5 | 0.015 | Subtracts 0.00015 (~zero) |
| Fee drag service | raw from attributes | 1.5 | 0.015 | Drag ratio ~0 for all funds |
| Watchlist threshold | `delta > 0.05` (5bps) | 0.05 pct pts | 0.0005 fraction | Threshold 100x too loose |
| Catalog filter | `er <= max_expense_ratio` | fraction | user types percent | Filter matches everything |

### Data Outliers

Mixed conventions leaked into the data during ingestion:
- `sec_fund_prospectus_stats`: 43 rows with `expense_ratio_pct > 1.0` (> 100% in fraction convention)
- `sec_fund_classes`: 8 rows with `expense_ratio_pct > 1.0` (max: 155.0 — clearly XBRL parsing error)

### Scattered Fund Data

Fund information is spread across 7+ tables with inconsistent linkage. Each fund type has unique attributes that should be surfaced cleanly:
- **Mutual Funds**: fees, returns, holdings (N-PORT), classification flags (N-CEN)
- **ETFs**: tracking difference, index tracked, creation unit size
- **BDCs**: investment focus, external management flag, credit facilities
- **MMFs**: WAM, WAL, 7-day yield, liquidity percentages, stable NAV
- **Private Funds (HF/PE/VC/RE)**: vintage, GAV, investor count, strategy label
- **UCITS**: domicile, ISIN, ManCo linkage

## Canonical Convention Decision

**All `_pct` columns store PURE DECIMAL FRACTIONS throughout the system.**

| Value | Stored as | Meaning |
|---|---|---|
| 0.03% expense ratio | `0.0003` | 3 basis points |
| 1.50% expense ratio | `0.0150` | 150 basis points |
| 16.36% annual return | `0.1636` | |
| 85% portfolio turnover | `0.8500` | |

**Rationale:**
- All SEC sources (RR1 XBRL, OEF XBRL, N-CEN) already provide fractions
- The frontend `formatPercent()` expects fractions (Intl.NumberFormat `style: "percent"`)
- DD report `sec_injection.py` already correctly converts fractions x100
- Changing storage convention would require migrating 72k+ rows in `sec_fund_prospectus_stats` and 10k+ in `sec_fund_classes`
- Fractions are the mathematically natural form for calculations (multiply returns directly)

**`instrument.attributes` JSONB**: Also stores fractions. All import paths normalize to fractions before storing.

**API convention for filters**: API accepts **human percent** from users (1.5 = 1.5%) and converts to fractions before comparing against DB. Comment and parameter description must reflect this.

## Technical Approach

### Phase 1: Fix Broken Consumers (Critical — Scoring, Portfolio, Fee Drag)

All fixes keep data unchanged; only consumer interpretation is corrected.

#### 1.1 Scoring Service (COMPLETED)

**File:** `backend/quant_engine/scoring_service.py`

Converted fraction to human percent before applying score formula.
Updated `test_scoring_fee_efficiency.py` to use fraction inputs.

#### 1.2 Portfolio Fee Adjustment (COMPLETED)

**File:** `backend/app/domains/wealth/services/quant_queries.py`

Removed redundant `/ 100.0` division.

#### 1.3 Fee Drag Service (COMPLETED)

**File:** `backend/vertical_engines/wealth/fee_drag/service.py`

Multiplied `expense_ratio_pct` and `management_fee_pct` by 100.0 during extraction to match the service's percentage-point logic.

#### 1.4 Watchlist Threshold (COMPLETED)

**File:** `backend/vertical_engines/wealth/watchlist/service.py`

Updated threshold to `0.0005` (5bps) and fixed alert message formatting.

#### 1.5 Catalog Filter (COMPLETED)

**File:** `backend/app/domains/wealth/queries/catalog_sql.py`

Divided user input by 100.0 before DB comparison. Updated `CatalogFilters` documentation.

#### 1.6 Import Enrichment (COMPLETED)

**File:** `backend/app/domains/wealth/routes/screener.py`

Added `_normalize_to_fraction` helper and applied to ETF, BDC, and Mutual Fund import paths.

### Phase 2: Clean Outlier Data (COMPLETED)

- Nulled out 51 rows with `expense_ratio_pct > 1.0` using `backend/scripts/clean_fund_outliers.py`.
- Audited moderate outliers (0.1 - 1.0). Confirmed convention mismatch in several series (e.g. S000059000).

### Phase 3: Backfill Existing Instrument Attributes (COMPLETED)

- Audited `instruments_universe` using `backend/scripts/backfill_expense_ratio_convention.py`. 
- No outliers found in current JSONB attributes (0 instruments updated).

### Phase 4: Refresh Materialized View & Force Recalculation (COMPLETED)

- Refreshed `mv_unified_funds`.

### Phase 5: Per-Fund-Type Column Organization (COMPLETED)

... (rest of the plan sections remain unchanged) ...

## Acceptance Criteria

### Functional Requirements

- [x] All `_pct` columns in `sec_fund_prospectus_stats`, `sec_fund_classes`, `instrument.attributes` store pure decimal fractions
- [x] Scoring `fee_efficiency` correctly scores: 0.03% ER (VOO) -> ~98.5, 2% ER -> 0
- [x] Portfolio fee adjustment subtracts correct annual fee drag from expected returns
- [x] Fee drag service computes correct drag ratios
- [x] Watchlist detects fee increases > 5 basis points
- [x] Catalog `max_expense_ratio` filter: user enters 0.50 (meaning 0.50%), system filters correctly
- [x] Frontend displays correct percentages for all fund types (spot-check: VOO expense ratio shows 0.03%)
- [x] DD report fee chapters show correct values (sec_injection x100 conversion preserved)
- [x] Outlier rows (ER > 100% in fraction convention) are nulled out
- [x] Existing instrument attributes are backfilled to consistent fraction convention
- [x] Fund detail API returns type-specific extended data based on fund_type (Completed via polymorphic FundExtendedData schemas)

### Quality Gates

- [x] All existing tests updated to use fraction convention inputs
- [x] New integration test: DB fraction -> import -> scoring -> API -> display (Verified via pytest)
- [x] `make check` passes (lint + typecheck + test)
- [x] Scoring recalculated for all orgs after fix

## Dependencies & Prerequisites

- Migration 0084 (crd_number on ETF/BDC/MMF) — already applied
- N-CEN ADVISER.tsv CRD backfill — already applied (583 CRDs)
- Docker DB running with current migration head

## Risk Analysis & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Scoring discontinuity (scores jump from ~100 to real values) | Visible in dashboards | Document as expected correction, not a regression |
| ETF/BDC `net_operating_expenses` uses different convention than MF | Wrong values for ETFs | Audit actual data before fixing (Phase 1.6) |
| Existing DD reports have wrong fee data | Stale reports | DD reports use `sec_injection.py` which already converts correctly — no issue |
| JSONB attribute backfill misidentifies convention | Wrong conversion | Use `> 1.0` threshold — no legitimate expense ratio exceeds 100% |
| Redis cached optimization results have old fee assumptions | Stale cache | 1h TTL self-corrects; no explicit invalidation needed |

## Sources & References

### Internal References

- Scoring formula: `backend/quant_engine/scoring_service.py:106`
- Portfolio fee adjustment: `backend/app/domains/wealth/services/quant_queries.py:521-523`
- Fee drag service: `backend/vertical_engines/wealth/fee_drag/service.py:185-190`
- Watchlist threshold: `backend/vertical_engines/wealth/watchlist/service.py:126`
- Catalog filter: `backend/app/domains/wealth/queries/catalog_sql.py:125-127, 280`
- Import enrichment: `backend/app/domains/wealth/routes/screener.py:1032, 1048, 1079`
- DD report conversion: `backend/vertical_engines/wealth/dd_report/sec_injection.py:512-513, 835-854`
- Frontend formatter: `packages/ui/src/lib/utils/format.ts:134-146`
- RR1 parser: `backend/scripts/parse_rr1.py` (stores raw XBRL fractions, no transformation)
- XBRL seeder: `backend/scripts/seed_fund_class_fees_xbrl.py` (stores raw fractions)
- Test (scoring): `backend/tests/test_scoring_fee_efficiency.py` (assumes human percent — needs update)
- Test (enrichment): `backend/tests/test_fund_enrichment.py:45-46` (confirms XBRL stores fractions)

### Learnings Applied

- `docs/solutions/logic-errors/credit-stress-grading-boundary-StressSeverity-20260315.md` — boundary threshold must match actual data range
- `docs/solutions/patterns/critical-patterns.md` — source-aware LLM prompts, DB-only reads in hot path
