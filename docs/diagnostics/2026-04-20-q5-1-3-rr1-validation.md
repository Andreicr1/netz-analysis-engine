# PR-Q5.1.3 — Canonical Map Expansion + RR-1 Slice Backfill Validation

Date: 2026-04-20
Branch: `feat/q5.1.3-canonical-map-rr1-backfill`
Target gate: MF coverage ≥12% (baseline 8.0%, projection 13-15%)

## Phase A — Migration 0168 (canonical map expansion)

Source: [`docs/diagnostics/2026-04-20-canonical-map-expansion-proposal.csv`](./2026-04-20-canonical-map-expansion-proposal.csv) (135 mapped rows over 81 unique `(proxy_etf_ticker, asset_class)` buckets).

Pre-apply: 44 rows (20 from 0165 + 24 from 0166).
Post-apply: 92 rows (+48 inserted, 33 merged into existing by ticker+asset_class lookup).

Apply log:

```
INFO  [alembic] Running upgrade 0167_primary_benchmark_backfill_log -> 0168_expand_canonical_map_fsds_q1_2025
[0168] benchmark_etf_canonical_map: merged_into_existing=33 inserted_new=48 total_groups=81
```

Source distribution after migration:

| source | rows |
|---|---|
| `manual_seed_0165` | 20 |
| `manual_seed_0166` | 24 |
| `fsds_q1_2025_slice_0168` | 48 |
| **total** | **92** |

Top aliases-merged buckets (new):

| ticker | canonical | #aliases |
|---|---|---|
| BIL | ICE BofA U.S. Treasury Bill Index | 11 |
| BIV | Bloomberg U.S.1-5 Year Government/Credit Index | 6 |
| UBND | Bloomberg U.S. Universal Index | 4 |
| BKLN | S&P UBS Leveraged Loan Index | 4 |

## Phase B — RR-1 slice backfill

Inputs:
- `E:\EDGAR FILES\Tickers\sub.tsv` — 1,506 Q1 2025 filings (`adsh → cik`)
- `E:\EDGAR FILES\Tickers\lab.tsv` — 50,738 XBRL Member rows; 3,245 benchmark-label hits; 348 unique CIKs

Resolver: benchmark_etf_canonical_map (322 alias lookup entries post-0168).

Planned actions:

| action | count |
|---|---|
| inserted | 177 |
| skipped_existing | 83 |
| unresolvable | 82 |

Top canonicals inserted (by CIK count):

| count | canonical |
|---|---|
| 73 | S&P 500 |
| 29 | Bloomberg US Aggregate Bond |
| 21 | Bloomberg Municipal |
| 9 | Russell 3000 |
| 5 | Russell 1000 |
| 5 | MSCI ACWI |
| 5 | MSCI EAFE |

## Coverage gate

| cut | total | with `primary_benchmark` | pct |
|---|---|---|---|
| MF baseline (post-Q5.1) | 3,652 | 293 | 8.00% |
| MF post-Q5.1.3 | 3,652 | 470 | **12.87%** |
| delta | — | +177 | **+4.87pp** |
| closed_end | 965 | 0 | 0.00% |

**Gate ≥12% MF: PASSED** (+0.87pp margin).

Audit trail: every processed CIK landed in `primary_benchmark_backfill_log`
with `source='fsds_q1_2025_rr1_v1'` and one of `inserted / skipped_existing / unresolvable`.
Combined with the Q5.1 audit rows (`source='tiingo_description_regex_v1'`),
operators can answer "why is fund X still missing?" with a single query.

## Unresolvable tail (Q5.2 input)

82 CIKs had a benchmark label parsed but no canonical match. The label set
is Q5.2 fodder — expected patterns include: `MSCI Kokusai Index`, `FTSE
World Government Bond Index` variants, `CBOE S&P 500 BuyWrite`, `Lipper
Growth Index`, Morningstar target-risk variants. Full historical FSDS
ingest worker (Q5.2) will expand the canonical map another 30-50 rows.
