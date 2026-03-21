---
status: resolved
priority: p3
issue_id: "216"
tags: [backend, quant-engine, macro, bis, imf]
dependencies: ["213", "215"]
---

# Integrate BIS + IMF into regional_macro_service scoring

## Problem Statement

After BIS and IMF data is ingested into hypertables, `quant_engine/regional_macro_service.py` needs to read these new data sources to enrich its scoring dimensions.

## Proposed Solution

### Approach

1. **BIS credit-to-GDP gap → `financial_conditions` dimension:**
   - Read `bis_statistics` WHERE `indicator = 'credit_to_gdp_gap'` for target countries
   - Pre-computed by BIS (CG_DTYPE=C) — no HP filter computation needed
   - Incorporate as a sub-score within existing `financial_conditions` scoring

2. **BIS debt service ratio + property prices** → Consider adding a 7th `credit_cycle` dimension combining:
   - Credit-to-GDP gap (BIS)
   - Debt service ratio (BIS)
   - Property prices (BIS)

3. **IMF GDP forecasts → `growth` dimension:**
   - Read `imf_weo_forecasts` WHERE `indicator = 'NGDP_RPCH'` for target countries
   - Forward-looking complement to FRED backward-looking GDP data
   - Weight: blend FRED actual (70%) + IMF forecast (30%) for composite growth score

4. **IMF inflation forecasts** → complement to FRED CPI in existing inflation sub-score.

All reads from DB hypertables (DB-first pattern). Config passed as parameter (no YAML loading). Queries include time-column filters for chunk pruning.

## Technical Details

**Affected files:**
- `backend/quant_engine/regional_macro_service.py` — add BIS + IMF data reads and scoring integration

**Constraints:**
- `quant_engine` services receive config as parameter (no YAML loading, no `@lru_cache`)
- Import-linter: `quant_engine` must not import from `app.domains.wealth`
- All hypertable queries must include time-column filters
- Never-raises: capture exceptions and return defaults

## Acceptance Criteria

- [ ] BIS credit-to-GDP gap integrated into `financial_conditions` scoring
- [ ] IMF GDP forecasts integrated into `growth` scoring
- [ ] All hypertable queries include time-column filters
- [ ] Never-raises: missing BIS/IMF data returns safe defaults
- [ ] Import-linter passes
- [ ] `make check` passes (lint + typecheck + test)
