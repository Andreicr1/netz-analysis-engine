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
