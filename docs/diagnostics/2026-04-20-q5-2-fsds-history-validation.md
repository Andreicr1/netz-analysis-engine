# PR-Q5.2 — FSDS Historical Benchmark Backfill Validation

Date: 2026-04-20
Branch: `feat/q5.2-fsds-historical-backfill`
Target gate: MF coverage ≥30% (institutional)

## Scope

Full SEC FSDS RR-1 historical archive: 36 quarters, 2016Q4 through
2025Q3. Zero external API calls — streams local mirror at
`E:\EDGAR FILES\RR1\*_rr1\{sub,lab}.tsv`.

Scales Q5.1.3's single-quarter backfill to aggregate benchmark Member
labels per normalized CIK across the full history, then resolve once
against `benchmark_etf_canonical_map` (92 rows / 322 aliases post-0168).

## Ingest stats

| metric | value |
|---|---|
| quarters processed | 36 |
| filings scanned | ~47,000 |
| XBRL Member rows scanned | ~1.2M |
| benchmark label hits (raw) | ~130,000 |
| unique CIKs with labels | 1,528 |
| distinct (CIK, label) tuples | 41,081 |
| MF CIKs covered by FSDS | 1,343 / 2,600 (dedup-normalized) |

## Coverage delta

| cut | total MF | with `primary_benchmark` | pct |
|---|---|---|---|
| baseline (post-Q5.1) | 3,652 | 293 | 8.00% |
| post-Q5.1.3 | 3,652 | 470 | 12.87% |
| **post-Q5.2** | **3,652** | **1,245** | **34.09%** |
| Q5.2 delta | — | +775 | **+21.22pp** |

**Institutional gate ≥30% MF: CLEARED** (+4.09pp margin).

## Audit-log breakdown

```
fsds_history_v1           inserted         709 (first pass)
                          inserted          66 (after regex tightening)
fsds_history_v1           skipped_existing 1,160
fsds_history_v1           unresolvable       117
fsds_q1_2025_rr1_v1       inserted         177 (Q5.1.3)
fsds_q1_2025_rr1_v1       skipped_existing  83
fsds_q1_2025_rr1_v1       unresolvable      82
tiingo_description_regex_v1 inserted       293 (Q5.1)
tiingo_description_regex_v1 no_match       320
tiingo_description_regex_v1 unresolvable   89
```

Every MF CIK with an identifiable benchmark mention now has a row
explaining the resolution path.

## Normalization hardening (vs Q5.1.3)

Four regex upgrades applied based on the Q1 2025 unresolvable tail:

| pattern | effect |
|---|---|
| `(?:index\s+)?(?:reflects\s+)?no\s+deduct...` | captures boilerplate with or without "reflects" prefix |
| `returns\s+do\s+not\s+reflect...` | SPDR-style disclosure variant |
| `Bloomberg Barclays` → `Bloomberg` | pre-Aug-2021 brand unification (~26 CIKs recovered) |
| `U\s*\.?\s*S\s*\.?` → `US` | collapses "U S", "U.S.", "US" space variants |
| `Index Return` / `Total Return Index` / `-NR` | suffix noise eliminated |

Impact isolated: +66 additional CIKs recovered on re-run with tightened
rules (first pass 709 → final pass 775 inserted).

## Top canonicals populated (Q5.2 pass)

| count | canonical |
|---|---|
| 294 | S&P 500 |
| 78 | Bloomberg US Aggregate Bond |
| 66 | Bloomberg Municipal |
| 36 | MSCI EAFE |
| 28 | MSCI World |
| 26 | MSCI ACWI |
| 24 | Russell 3000 |
| 18 each | Russell 1000, Russell 2000 |
| 16 | Bloomberg Global Agg ex-USD |
| 15 each | MSCI Emerging Markets, Russell 1000 Value |

## Unresolvable tail (Q5.3 input)

117 CIKs had parsed labels with no canonical match. Top categories
dumped to `docs/diagnostics/2026-04-20-q5-2-unresolvable.csv`:

- Lipper category indices (`Lipper General US Government Funds Index`)
- Morningstar style indices (`Morningstar Moderate Target Risk Index`)
- CBOE strategy indices (`CBOE S&P 500 BuyWrite`)
- JP Morgan bespoke (`JPM EMBI Global Div ex-CCC`)
- Single-country MSCI not in map (`MSCI Kokusai`, `MSCI India`)

Expected Q5.3 uplift: +30-50 canonical rows, another +3-5pp coverage.

## Operator re-run command

Idempotent — safe to re-run monthly as the operator syncs fresh RR-1
quarters:

```bash
PYTHONPATH=. python -m scripts.backfill_primary_benchmark_from_fsds_history \
    --dump-unresolvable docs/diagnostics/$(date +%F)-fsds-unresolvable.csv
```

Rollback: `UPDATE sec_registered_funds SET primary_benchmark = NULL
WHERE cik IN (SELECT cik FROM primary_benchmark_backfill_log WHERE
source='fsds_history_v1' AND action='inserted')`.
