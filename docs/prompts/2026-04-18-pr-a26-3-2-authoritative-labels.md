# PR-A26.3.2 — Authoritative-First Strategy Label Refresh

**Date**: 2026-04-18
**Status**: P0 DATA QUALITY — fixes the upstream contamination (SCHD/XLF/QQQM labeled "Real Estate", FT Vest Buffer ETFs labeled "Commodities", equity funds labeled "Cash Equivalent") that polluted every propose-mode proposal. Pre-requisite for A26.3 frontend ship.
**Branch**: `feat/pr-a26-3-2-authoritative-labels`
**Predecessors merged**: A21–A26.2 (full sequence), #167 Tiingo enrichment, #168 cascade classifier, #169 round 1 patches, #174/175 apply gate, #218 label patch revert.

---

## Context

The Tiingo description classifier (PR #168) with round 1 patches (PR #169) does **NOT** fix contamination in `Real Estate`, `Cash Equivalent`, `Commodities`, `Precious Metals` buckets. Direct verification 2026-04-18 against dev DB local run (`run_id=c43cf68f-...`):

| Ticker | Actual fund | Current label | Cascade proposed | Source | Confidence |
|---|---|---|---|---|---|
| SCHD | Schwab Dividend Equity | Real Estate | **Real Estate** (kept) | tiingo_description | high |
| XLF | Financial Sector SPDR | Real Estate | **Real Estate** (kept) | tiingo_description | high |
| QQQM | Invesco NASDAQ 100 | Real Estate | **Real Estate** (kept) | tiingo_description | high |
| SCHB | Schwab Total Market | Cash Equivalent | **Cash Equivalent** (kept) | tiingo_description | high |
| FEZ | EuroStoxx 50 ETF | Cash Equivalent | **Cash Equivalent** (kept) | tiingo_description | high |
| VMIAX | Vanguard Materials Index | Precious Metals | **Precious Metals** (kept) | tiingo_description | high |
| FT Vest Buffer ETFs | Defined-outcome equity | Commodities | **Commodities** (kept) | tiingo_description | high |
| SPMQX | Invesco SteelPath MLP | Commodities | **Commodities** (kept) | tiingo_description | high |

Round 2 classifier patches were never shipped per PR #170 note. This PR takes a different approach: **authoritative regulatory sources** as primary strategy_label, Tiingo cascade as late fallback.

## Authoritative source coverage (verified 2026-04-18)

| Table | Column | Total / Non-Null | Distinct values | Label quality |
|---|---|---|---|---|
| `sec_money_market_funds` | `mmf_category` + `strategy_label` | 373 / 373 | 4 categories / 5 strategy_labels | Clean — Government / Prime / Tax-Exempt / Single State |
| `sec_etfs` | `strategy_label` | 985 / 546 | 30 | Clean canonical — Large Blend, Sector Equity, Intermediate-Term Bond, International Equity, etc. |
| `sec_bdcs` | `strategy_label` | 196 / 196 | 3 | Clean |
| `esma_funds` | `strategy_label` | 10,436 / 6,051 | 33 | Clean — Multi-Asset, ESG/Sustainable Equity, Asian Equity, European Equity, etc. |
| `sec_registered_funds` | `fund_type` | 4,617 / 4,617 | 2 | Too coarse (only `mutual_fund` / `closed_end`); not useful |

**Bridges to `instruments_universe`:**
- `iu.attributes.sec_cik → sec_registered_funds.cik` — 5,086 / 5,450 (93%)
- `iu.ticker → sec_etfs.ticker` — 912 / 985 ETFs (92%)
- `iu.attributes.sec_cik → sec_money_market_funds.cik` — 44 / 373 MMFs (12% — bridge gap, address in A26.3.3)

---

## Scope

**In scope:**
- Migration 0156: create backup table `strategy_label_authoritative_backup` + add columns `attributes.strategy_label_source` and `attributes.strategy_label_source_table` (JSONB merge; no new SQL columns). Add `strategy_label_refresh_runs` audit table.
- Map file `backend/app/domains/wealth/services/authoritative_label_map.py` — dicts mapping authoritative values (from sec_etfs / sec_bdcs / sec_mmf / esma) to canonical strategy_label names used in `block_mapping.py`. Include unit tests.
- Script `backend/scripts/refresh_authoritative_labels.py`:
  - Priority ladder per instrument (MMF → ETF → BDC → ESMA → current cascade → NULL).
  - `--dry-run` default, `--apply` writes.
  - Per-run JSON report: counts by source, counts by label transition, top 20 changes, examples of contamination resolved (explicit check for SCHD, XLF, QQQM, FT Vest, etc.).
  - Atomic per-source transaction — rollback on failure.
- Block mapping extension: any clean authoritative label emerging from sec_etfs/sec_bdcs/esma that isn't in `block_mapping.py` (e.g., "International Equity", "Intermediate-Term Bond", "Sector Equity") gets added with correct block assignment.
- Integration test: seeds a small universe with known-contaminated labels, runs refresh, asserts expected reclassification.
- Post-apply smoke: re-run `pr_a26_2_smoke.py` and compare allocation distribution vs current (with cash temporarily excluded) — expect equity/FI/alt distribution change when fake equities move out of alt blocks.

**Out of scope:**
- Do NOT build fuzzy fund_name bridge for unlinked MMFs/BDCs — that's A26.3.3.
- Do NOT modify Tiingo cascade classifier or round 1 patches — they stay as late fallback.
- Do NOT delete rows from `instruments_universe`.
- Do NOT touch optimizer, composition, propose/approve flows.
- Do NOT attempt to reclassify private funds (sec_manager_funds) — their strategy is largely regulator-reported already; not the contamination target here.
- Do NOT build frontend UI for reclassification — CLI only.

---

## Execution Spec

### Section A — Migration 0156: backup table + audit run table

**File:** `backend/app/core/db/migrations/versions/0156_authoritative_label_refresh.py`

Down_revision: `0155_strategic_allocation_approved_state`.

```sql
CREATE TABLE strategy_label_authoritative_backup (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL,
  instrument_id UUID NOT NULL,
  ticker TEXT,
  fund_name TEXT,
  previous_strategy_label TEXT,
  new_strategy_label TEXT,
  source_table TEXT NOT NULL,
  source_value TEXT NOT NULL,  -- raw value from authoritative source before map
  backed_up_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_strategy_label_backup_run ON strategy_label_authoritative_backup(run_id);
CREATE INDEX ix_strategy_label_backup_instrument ON strategy_label_authoritative_backup(instrument_id);

CREATE TABLE strategy_label_refresh_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  candidates_count INTEGER,
  mmf_applied INTEGER DEFAULT 0,
  etf_applied INTEGER DEFAULT 0,
  bdc_applied INTEGER DEFAULT 0,
  esma_applied INTEGER DEFAULT 0,
  tiingo_fallback_count INTEGER DEFAULT 0,
  null_flagged_count INTEGER DEFAULT 0,
  report_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

No RLS (global infrastructure tables). Reversible down-migration.

**Acceptance:** `make migrate` up+down round-trip clean.

### Section B — Authoritative label map

**File:** `backend/app/domains/wealth/services/authoritative_label_map.py`

Maps raw values from each authoritative source to canonical strategy_label names compatible with `block_mapping.py`.

```python
MMF_CATEGORY_TO_LABEL: dict[str, str] = {
    "Government": "Government Money Market",
    "Prime": "Prime Money Market",
    "Other Tax Exempt": "Tax-Exempt Money Market",
    "Single State": "Single State Money Market",
}

SEC_ETF_LABEL_NORMALIZE: dict[str, str] = {
    # Pass-through when block_mapping already has the label:
    "Large Blend": "Large Blend",
    "Large Growth": "Large Growth",
    "Large Value": "Large Value",
    "Mid Growth": "Mid Growth",
    "Mid Value": "Mid Value",
    "Mid Blend": "Mid-Cap Blend",
    "Small Blend": "Small Blend",
    "Small Growth": "Small Growth",
    "Small Value": "Small Value",
    "Emerging Markets Equity": "Diversified Emerging Mkts",
    "International Equity": "Foreign Large Blend",
    "Sector Equity": "Sector Equity",  # NEW — needs block_mapping entry
    "ESG/Sustainable Equity": "ESG Equity",  # NEW — needs block_mapping
    "Intermediate-Term Bond": "Intermediate Core Bond",
    "Investment Grade Bond": "Corporate Bond",  # NEW alias
    "High Yield Bond": "High Yield Bond",
    "Municipal Bond": "Municipal Bond",
    "Balanced": "Balanced",  # NEW — multi-asset, needs block decision
    "Real Estate": "Real Estate",
    "Commodities": "Commodities",
    "Precious Metals": "Precious Metals",
    # ... (full enumeration from sec_etfs.strategy_label DISTINCT)
}

SEC_BDC_LABEL_NORMALIZE: dict[str, str] = {
    # Most BDCs: Private Credit
    # Verify via: SELECT DISTINCT strategy_label FROM sec_bdcs
}

ESMA_LABEL_NORMALIZE: dict[str, str] = {
    "European Equity": "Foreign Large Blend",
    "Asian Equity": "Asian Equity",
    "Multi-Asset": "Balanced",
    "ESG / Sustainable": "ESG Equity",
    # ... (full enumeration from esma_funds.strategy_label DISTINCT)
}
```

**Procedure:** before coding, run `SELECT DISTINCT strategy_label FROM sec_etfs` / `sec_bdcs` / `esma_funds` to enumerate every distinct value. Map each to either:
1. An existing `STRATEGY_LABEL_TO_BLOCKS` key in `block_mapping.py` (preferred — no changes needed), OR
2. A new canonical label (requires adding a new entry in `block_mapping.py` in the same PR).

**New labels identified** that likely need entries in `block_mapping.py`:
- `Sector Equity` → probably `na_equity_large` (fallback US) or a new block (out of scope).
- `Balanced` / `Multi-Asset` → tricky, could be split-proportional; for v1 map to `na_equity_large` as dominant.
- `ESG Equity` / `ESG/Sustainable Equity` / `ESG/Sustainable Bond` → map to `na_equity_large` or `fi_us_aggregate` as dominant.
- Any `Convertible` → new category, defer to v2.

**Acceptance:** unit tests assert every DISTINCT value from the 3 authoritative tables has a deterministic mapping to either a `block_mapping.py` key or to `None` with explicit reason ("requires operator review").

### Section C — Refresh script

**File:** `backend/scripts/refresh_authoritative_labels.py`

```
Usage:
  python backend/scripts/refresh_authoritative_labels.py [--dry-run | --apply]
```

**Priority ladder** (per instrument in `instruments_universe` with `is_active=TRUE`):
1. **MMF:** if `sec_money_market_funds.cik = iu.attributes->>'sec_cik'` returns exactly 1 row, use that fund's `mmf_category` mapped via `MMF_CATEGORY_TO_LABEL`.
2. **ETF:** elif `sec_etfs.ticker = iu.ticker` AND `sec_etfs.strategy_label IS NOT NULL` returns exactly 1 row, use `sec_etfs.strategy_label` mapped via `SEC_ETF_LABEL_NORMALIZE`.
3. **BDC:** elif `sec_bdcs.cik = iu.attributes->>'sec_cik'` returns exactly 1 row, use `sec_bdcs.strategy_label` mapped via `SEC_BDC_LABEL_NORMALIZE`.
4. **ESMA:** elif `esma_funds.isin = iu.isin` AND `esma_funds.strategy_label IS NOT NULL` returns exactly 1 row, use `esma_funds.strategy_label` mapped via `ESMA_LABEL_NORMALIZE`.
5. **Tiingo cascade:** elif most recent entry in `strategy_reclassification_stage` for this instrument has `classification_source='tiingo_description'` AND `confidence='high'` — use `proposed_strategy_label`.
6. **Fallback:** NULL + `attributes.needs_human_review = true`.

**For each instrument:**
- Compute new label via ladder.
- If differs from current `attributes->>'strategy_label'`:
  - Write backup row to `strategy_label_authoritative_backup` (capturing previous + new + source_table + source_value).
  - If `--apply`: JSONB-merge update to `instruments_universe.attributes` — set `strategy_label`, `strategy_label_source` (one of: `sec_mmf`, `sec_etf`, `sec_bdc`, `esma_funds`, `tiingo_cascade`, `needs_review`), `strategy_label_refreshed_at`.
- Tally counters by source.
- Track **explicit regression check** for SCHD, XLF, QQQM, SCHB, FEZ, VMIAX, FT Vest tickers — assert their label in the report (should move from `Real Estate / Cash Equivalent / Precious Metals / Commodities` to appropriate authoritative label).

**Output:** JSON report + human-readable summary printed to stdout. JSON includes:
```json
{
  "run_id": "...",
  "dry_run": true,
  "candidates": 5450,
  "applied_by_source": {"sec_mmf": 44, "sec_etf": 912, "sec_bdc": 0, "esma_funds": 0, "tiingo_cascade": 1500, "needs_review": 2994},
  "transitions_top_20": [...],
  "contamination_resolved": {
    "SCHD": {"before": "Real Estate", "after": "<new>", "source": "sec_etf"},
    ...
  }
}
```

Persist to `strategy_label_refresh_runs`.

**Acceptance:**
- Dry-run output against dev DB shows SCHD/XLF/QQQM/SCHB/FEZ/VMIAX resolved to non-contaminated labels via `sec_etf` source.
- No writes to `instruments_universe.attributes.strategy_label` in dry-run mode.
- Apply mode writes + creates backup rows.
- Re-running after apply is idempotent (no-op second time — backup rows track prior state; script skips rows already matching target).

### Section D — Block mapping extensions

**File:** `backend/vertical_engines/wealth/model_portfolio/block_mapping.py`

Add entries for any new canonical labels introduced by the map in Section B. Examples (final list depends on SELECT DISTINCT enumeration):

```python
# Sector-aggregate labels (map to US large as dominant fallback — refine later)
"Sector Equity": ["na_equity_large"],

# Multi-asset / ESG / Convertible (v1: dominant block; refine later)
"Balanced": ["na_equity_large"],
"ESG Equity": ["na_equity_large"],
"ESG/Sustainable Equity": ["na_equity_large"],
"ESG/Sustainable Bond": ["fi_us_aggregate"],
"Corporate Bond": ["fi_ig_corporate"],  # if not already present
```

Each addition documented with one-line comment referencing the source (sec_etfs label count, esma label count).

**Acceptance:** every canonical label produced by Section B map exists in `STRATEGY_LABEL_TO_BLOCKS`.

### Section E — Integration tests

**Files:**
- `backend/tests/scripts/test_refresh_authoritative_labels.py`
- `backend/tests/wealth/services/test_authoritative_label_map.py`

Test scenarios:
- Seed `sec_etfs` with known clean labels, seed `instruments_universe` with contaminated ones, run refresh in apply mode, assert labels flipped to clean + backup rows written.
- Priority ladder: instrument linked to both MMF and ETF — MMF wins (higher priority).
- Instrument with no authoritative source + no Tiingo cascade → falls through to `needs_human_review`.
- Re-run idempotency: applying twice produces zero changes on second invocation.
- Regression suite: explicit tickers SCHD/XLF/QQQM/FT Vest — assert post-refresh labels match expected canonical values.

### Section F — Post-apply smoke + comparison

**Runbook** (documented in a new file `docs/reference/authoritative-label-refresh-runbook.md`):

1. Apply A26.0 → A26.2 + current PR migrations.
2. `python backend/scripts/refresh_authoritative_labels.py` (dry-run) — inspect report.
3. `python backend/scripts/refresh_authoritative_labels.py --apply` — execute.
4. Re-set `excluded_from_portfolio=false` on cash block (was set true in experiment 2026-04-18).
5. Re-dispatch `pr_a26_2_smoke.py` — propose → approve → realize.
6. Compare new approved allocation breakdown vs 2026-04-18 experiment (cash-excluded run):
   - **Expected:** cash block now has 44+ candidates (MMFs bridged via sec_cik), allocation falls to realistic 5-15%.
   - **Expected:** alt_real_estate candidates drop significantly (SCHD/XLF/QQQM/dozens of equity funds move out).
   - **Expected:** Conservative recovers some equity exposure (equity funds correctly re-labeled get considered for equity blocks).
   - **Expected:** Sharpe ratios drop from 3.2-3.8 range to more defensible 1.5-2.5 (previous figures were inflated by fake-alt contamination).
7. Paste new distribution table in PR description as evidence.

---

## Ordering inside this PR

A (migration) → B (map + tests) → D (block_mapping extensions + tests) → C (refresh script + tests) → E (integration tests) → F (runbook doc). One commit per Section.

## Global guardrails

- `CLAUDE.md` rules. Async-first, RLS context via `SET LOCAL` (though backup + refresh tables are global), `expire_on_commit=False`, `lazy="raise"`.
- No new Python dependencies.
- `make check` green.
- Do NOT touch: optimizer, composition, Tiingo cascade classifier internals, frontend.

## Final report format

1. Migration up/down round-trip.
2. Test output (unit + integration).
3. Dry-run report against dev DB (full JSON + transition table top-20).
4. Apply mode execution log (counters + backup row count).
5. Explicit regression table:
   - SCHD: before=Real Estate, after=<new>, source=sec_etf
   - XLF: before=Real Estate, after=<new>, source=sec_etf
   - QQQM: before=Real Estate, after=<new>, source=sec_etf
   - SCHB: before=Cash Equivalent, after=<new>, source=sec_etf
   - FEZ: before=Cash Equivalent, after=<new>, source=sec_etf
   - VMIAX: before=Precious Metals, after=<new>, source=sec_etf
   - (expand to top 20 by AUM)
6. Post-apply `pr_a26_2_smoke.py` output showing new allocation distribution — paste comparison table.
7. List deviations from spec.
