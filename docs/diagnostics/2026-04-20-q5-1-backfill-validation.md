# PR-Q5.1 Phase A3 Validation Evidence

Generated 2026-04-20 by `backfill_primary_benchmark_from_tiingo` against
local dev DB (migrations 0165, 0166, 0167 applied).

## Coverage per fund_type

```
mutual_fund   total=3652   with_benchmark=293   (8.0%)
closed_end    total= 965   with_benchmark=  0   (0.0%)
```

Target: mutual_fund ≥ 30%. **Gate failed — data ceiling, not regex ceiling.**

Root cause: `instruments_universe.attributes->'tiingo_description'` is
populated for only 702 unique CIKs, of which all 702 are mutual_fund
(0 closed_end). Regex extraction rate on that population is 41.7%
(293 / 702), which would translate to ~40% coverage *if* tiingo
descriptions existed for every registered fund.

Follow-up to unlock the remaining funds: re-run the Tiingo description
ingestion worker (Phase B on the Q5 roadmap) or the Q5.2 N-CSR XBRL
contingency path. Neither is in scope for this PR.

## Top 25 assigned benchmarks

```
  66  S&P 500
  41  Russell 2000
  21  Russell 1000
  18  Bloomberg US Aggregate Bond
  14  Russell 1000 Value
  14  MSCI Emerging Markets
  11  MSCI World
  10  Russell Midcap
   9  MSCI EAFE
   9  Russell 2000 Growth
   9  Russell Midcap Value
   8  Russell 1000 Growth
   8  Russell 2000 Value
   7  Russell 3000
   7  Russell 2500
   6  Russell Midcap Growth
   5  JP Morgan Emerging Markets Bond
   4  S&P SmallCap 600
   3  Russell 2500 Growth
   3  Bloomberg Municipal
   3  MSCI ACWI
   2  MSCI World ex-USA
   2  MSCI China
   2  MSCI USA Large Cap
   2  Bloomberg Commodity
```

Distribution aligns with institutional-default benchmarks: S&P 500 and
Russell 2000 on top, broad Bloomberg US Aggregate Bond, MSCI developed
and emerging. No garbage strings, no 2-character noise, no "Index"-only
captures.

## Dispatcher smoke

`resolve_benchmark()` over 6 random funds with populated
`primary_benchmark`:

```
CIK=872649     benchmark='Russell 2000'         → match=exact  ticker=IWM   class=equity_us_small
CIK=816153     benchmark='MSCI World'           → match=exact  ticker=URTH  class=equity_intl_dev
CIK=81443      benchmark='Russell 2000 Value'   → match=exact  ticker=IWN   class=equity_us_small
CIK=887991     benchmark='S&P 500'              → match=exact  ticker=SPY   class=equity_us_large
CIK=803191     benchmark='Russell 1000 Value'   → match=exact  ticker=IWD   class=equity_us_large
CIK=856119     benchmark='Russell 2000'         → match=exact  ticker=IWM   class=equity_us_small
```

6/6 Level-1 exact alias matches. Trigram fuzzy fallback (Level 2) and
asset-class fallback (Level 3) remain exercised by the Q5 attribution
test suite.

## Audit log summary

```
inserted       293  (one row per unique CIK UPDATEd)
unresolvable    89  (regex extracted, canonical map had no alias)
no_match       320  (regex found no benchmark in description)
```

`primary_benchmark_backfill_log` is queryable via standard SQL for
per-fund triage.
