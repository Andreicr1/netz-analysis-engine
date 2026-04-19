# Authoritative Strategy Label Refresh — Runbook

**Owner:** Andrei
**Script:** `backend/scripts/refresh_authoritative_labels.py`
**Migration:** `0156_authoritative_label_refresh`
**Status (2026-04-18):** PR-A26.3.2 — first deployable run.

## Purpose

Overwrite the contaminated `instruments_universe.attributes->>'strategy_label'` values produced by the Tiingo description cascade with cleaner labels sourced from authoritative regulatory tables (`sec_money_market_funds`, `sec_etfs`, `sec_bdcs`, `esma_funds`). Falls back to the Tiingo cascade only when no authoritative source is available.

## Priority ladder

For every active row in `instruments_universe`:

| Slot | Source table | Bridge column |
|---|---|---|
| 1 | `sec_money_market_funds` | `series_id` ↔ `iu.attributes->>'series_id'` (or `iu.isin` when it begins with `S0`) |
| 2 | `sec_etfs` | `series_id` first, then `ticker` as secondary bridge |
| 3 | `sec_bdcs` | `series_id` |
| 4 | `esma_funds` | real `isin` only — IU rows whose `isin` actually stores an SEC `S0…` series id are skipped |
| 5 | `strategy_reclassification_stage` | most recent high-confidence row with `classification_source = 'tiingo_description'` |
| 6 | NULL + `attributes.needs_human_review = true` | (no source available) |

**CIK is intentionally NOT used as a bridge.** CIK is the issuer-level registrant identifier; one CIK can host dozens of unrelated funds (e.g., Schwab CIK 0001454889 covers SCHD, SCHB, Schwab Government MMF, …). A CIK bridge would smear MMF labels across every Schwab fund.

## Procedure

### 1. Pre-flight

```bash
make up                  # docker-compose: PG + Redis
make migrate             # ensure 0156 applied (alembic head: 0156_authoritative_label_refresh)
```

Verify the two new tables exist:

```sql
\d strategy_label_authoritative_backup
\d strategy_label_refresh_runs
```

### 2. Dry-run (always start here)

```bash
cd backend
python scripts/refresh_authoritative_labels.py
```

Prints summary + writes one row to `strategy_label_refresh_runs` with `dry_run=true` and the full JSON report inline. **No writes** to `instruments_universe`. Inspect:

* `applied_by_source` counters
* `transitions_top_20` (e.g., `Real Estate -> Sector Equity (sec_etf)`)
* `regression_check` block — confirms SCHD / XLF / QQQM / SCHB / FEZ / VMIAX / SPMQX status
* `contamination_resolved_count` — primary KPI

### 3. Apply

```bash
python scripts/refresh_authoritative_labels.py --apply
```

Single transaction:

* Per change: insert backup row in `strategy_label_authoritative_backup`, JSONB-merge update on `instruments_universe.attributes` setting `strategy_label`, `strategy_label_source`, `strategy_label_source_table`, `strategy_label_refreshed_at`, `needs_human_review`.
* Audit row in `strategy_label_refresh_runs` with `dry_run=false`.

Idempotent: re-running after a successful apply is a no-op (no row matches the change condition).

### 4. Post-apply portfolio smoke

```bash
# Re-enable cash block if it was excluded for any prior experiment:
docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine \
  -c "UPDATE strategic_allocation SET excluded_from_portfolio = false WHERE block_id = 'cash'"

cd backend
python scripts/pr_a26_2_smoke.py
```

Compare the new approved-allocation breakdown against the cash-excluded run from 2026-04-18 (captured in PR description).

**Expected directional changes:**

* `cash` candidate count climbs (more MMFs reachable → realistic 5-15% allocation rather than degenerate 0%).
* `alt_real_estate` candidate count drops as ETFs like XLF / SPMQX / FT Vest funds move to their proper blocks (Sector Equity, Commodities, etc.).
* Conservative profile reclaims equity exposure as previously-misclassified equity funds rejoin equity blocks.
* Sharpe ratios fall from the inflated 3.2-3.8 range toward defensible 1.5-2.5.

Paste the post-apply distribution table into the PR description as evidence.

## Rollback

Per-row rollback (single instrument):

```sql
SELECT instrument_id, previous_strategy_label
FROM strategy_label_authoritative_backup
WHERE instrument_id = '<uuid>'
ORDER BY backed_up_at DESC
LIMIT 1;

UPDATE instruments_universe
SET attributes = attributes || jsonb_build_object('strategy_label', '<previous>')
WHERE instrument_id = '<uuid>';
```

Full-run rollback (revert one `run_id`):

```sql
UPDATE instruments_universe iu
SET attributes = attributes || jsonb_build_object(
    'strategy_label', b.previous_strategy_label
)
FROM strategy_label_authoritative_backup b
WHERE b.run_id = '<run_id>'
  AND b.instrument_id = iu.instrument_id;
```

## Known limitations (driving A26.3.3)

* Funds whose `sec_etfs.strategy_label IS NULL` (439 of 985 ETFs) and whose Tiingo cascade gave a contaminated label remain stuck. Examples confirmed 2026-04-18: SCHD, QQQM, SCHB, VMIAX, SPMQX. A26.3.3 introduces a fuzzy `fund_name` bridge to `sec_registered_funds` (mutual fund / closed-end side) where labelling tends to be cleaner.
* MMF coverage is 1 of 373 funds — most MMFs aren't in `instruments_universe` because `instrument_ingestion` doesn't pull them. A26.3.3 will seed cash-eligible MMFs into IU before the refresh.
* ESMA bridge is 0 hits because `instruments_universe.isin` predominantly stores SEC series ids. A26.3.3 will add a real-ISIN normalisation pass.

## Audit columns added to `instruments_universe.attributes` (no schema change)

| Key | Type | Set when |
|---|---|---|
| `strategy_label_source` | text | every apply |
| `strategy_label_source_table` | text | every apply (NULL for needs_review) |
| `strategy_label_refreshed_at` | text (ISO-8601) | every apply |
| `needs_human_review` | boolean | only when source = `needs_review` |

---

## A26.3.3 extension — fuzzy bridge + sec_etfs backfill

**Migration:** `0157_fuzzy_bridge_audit`
**Scripts:** `backend/scripts/bridge_mmf_catalog.py`, `backend/scripts/backfill_sec_etfs_strategy_label.py`

Two new closures for the gaps documented above:

1. **MMF fuzzy bridge** — `bridge_mmf_catalog.py` uses deterministic token-set Jaccard + `difflib.SequenceMatcher` (pure stdlib) to match `instruments_universe.name` against `sec_money_market_funds.fund_name`. Auto-apply threshold 0.85 with a second-pass verifier (Jaccard ≥ 0.70 AND SeqMatch ≥ 0.80 AND same category family). 0.70–0.85 matches land in `sec_mmf_bridge_candidates` tier `needs_review` for manual resolution. Writes `sec_cik` + `sec_series_id` into `instruments_universe.attributes`.
2. **sec_etfs label backfill** — `backfill_sec_etfs_strategy_label.py` runs the Tiingo cascade classifier (`classify_fund`) against the 439 `sec_etfs` rows with `strategy_label IS NULL`, writes result plus `strategy_label_source = 'tiingo_cascade'` (or `'unclassified'` when cascade falls back).

### Full execution sequence (A26.3.2 already applied, running the A26.3.3 extension)

```bash
# 1. Apply 0157
make migrate                                              # head becomes 0157_fuzzy_bridge_audit

# 2. Fuzzy bridge MMFs — dry-run, inspect top auto / needs_review, then apply
python backend/scripts/bridge_mmf_catalog.py --json | tee /tmp/mmf_bridge_dryrun.json
python backend/scripts/bridge_mmf_catalog.py --apply --json | tee /tmp/mmf_bridge_apply.json

# 3. Backfill sec_etfs.strategy_label — dry-run, then apply
python backend/scripts/backfill_sec_etfs_strategy_label.py --json | tee /tmp/etf_backfill_dryrun.json
python backend/scripts/backfill_sec_etfs_strategy_label.py --apply --json | tee /tmp/etf_backfill_apply.json

# 4. Re-run authoritative labels to propagate new bridges + new sec_etfs labels
python backend/scripts/refresh_authoritative_labels.py --apply --json | tee /tmp/authoritative_second_pass.json

# 5. Smoke test
python backend/scripts/pr_a26_2_smoke.py
```

### Expected outcomes

| Step | Before | After (target) |
|---|---|---|
| `sec_etfs.strategy_label NOT NULL` | 546 (of 985) | ≥ 900 |
| `sec_mmf` bridges in IU | 44 | 300+ |
| `applied_by_source.sec_mmf` (second pass) | 1 | 50+ |
| `applied_by_source.sec_etf` (second pass) | 507 | 950+ |
| Cash block share in propose output | 51–61 % | 5–15 % |
| Portfolio Sharpe (Balanced) | 3.1–3.6 (inflated) | 1.5–2.5 |

### Rollback

```sql
-- 1. Undo the second-pass authoritative refresh
UPDATE instruments_universe iu
SET attributes = COALESCE(attributes, '{}'::jsonb) ||
                 jsonb_build_object('strategy_label', b.previous_strategy_label)
FROM strategy_label_authoritative_backup b
WHERE b.run_id = '<second_pass_run_id>'
  AND b.instrument_id = iu.instrument_id;

-- 2. Undo the fuzzy MMF bridge (only auto_applied rows wrote into attributes)
UPDATE instruments_universe iu
SET attributes = iu.attributes - 'sec_cik' - 'sec_series_id'
                                - 'mmf_bridge_source' - 'mmf_bridge_score'
                                - 'mmf_bridge_at'
FROM sec_mmf_bridge_candidates c
WHERE c.match_tier = 'auto_applied'
  AND c.applied_at IS NOT NULL
  AND c.instrument_id = iu.instrument_id;

-- 3. Undo the sec_etfs backfill
UPDATE sec_etfs
SET strategy_label = NULL, strategy_label_source = NULL
WHERE strategy_label_source = 'tiingo_cascade';

-- 4. Drop migration if needed
-- alembic downgrade 0156_authoritative_label_refresh
```

### Known limitations remaining after A26.3.3

* BDC and ESMA bridges still rely on direct identifier matching — no fuzzy extension in v1.
* Funds where Tiingo has no description and the fund name is a short opaque mark (e.g. `"AAA"`, `"XYZ"`) stay `unclassified`. Manual brochure classification is the follow-on path.
* `sec_mmf_bridge_candidates` rows with `match_tier = 'needs_review'` accumulate until an operator resolves them via SQL update — no UI in v1.

---

## PR-A26.3.5 Session 1 — Curator Overrides (priority 0)

Migration `0158_instrument_strategy_overrides` adds a curator-managed
override table that takes precedence over every authoritative source in
`refresh_authoritative_labels.py`. Seeded with 48 canonical institutional
tickers (SPY/IVV/VOO/VTI, QQQ family, SCHD/SCHB/VMIAX regression fixes,
core bond/treasury ETFs, commodities, sector SPDRs).

### Adding a new override

**Preferred path (durable):** add an entry to `SEED_OVERRIDES` in the
next migration. The seed list is code-reviewed and versioned.

**Hot-patch path (SQL):**

```sql
INSERT INTO instrument_strategy_overrides (ticker, strategy_label, rationale, curated_by)
VALUES ('TICKER', 'Canonical Label', 'why this override exists', 'operator:name')
ON CONFLICT (ticker) DO UPDATE
SET strategy_label = EXCLUDED.strategy_label,
    rationale = EXCLUDED.rationale,
    curated_by = EXCLUDED.curated_by,
    curated_at = now();
```

Then re-run `python backend/scripts/refresh_authoritative_labels.py --apply`
to propagate into `instruments_universe.attributes`.

The `strategy_label` MUST be a key in
`vertical_engines.wealth.model_portfolio.block_mapping.STRATEGY_LABEL_TO_BLOCKS`
— otherwise candidate discovery returns zero funds silently.

### When to use an override vs fix the classifier

- **Override:** single-ticker outliers, SEC-registered regression fixes
  where the authoritative bulk data is wrong or missing, fund families
  with bespoke structures (FT Vest Buffer ETFs — handled via class-level
  regex, not per-ticker).
- **Classifier fix:** categorical issues (every Financial-sector fund
  mislabeling as Real Estate). Prefer Session 2/3 patches.

### FT Vest Buffer ETF family

Tickers `FJAN..FDEC` are resolved to `Balanced` via a class-level regex
inside `_resolve_override` — no per-ticker seed needed. An exact table
entry for any buffer ticker still wins over the regex.

### Review cadence

Quarterly: audit `instrument_strategy_overrides` and remove entries that
Session 3 (context-gated patterns) now handles correctly. Entries stay
in the backup chain, so removal is safe.
