# Classification Apply Runbook

End-to-end procedure for moving staged strategy reclassifications into
production via the apply gate. Pair with the cascade classifier
(`backend/app/domains/wealth/services/strategy_classifier.py`) and the
reclassification worker (`backend/app/domains/wealth/workers/strategy_reclassification.py`).

## Prerequisites

- A populated `strategy_reclassification_stage` `run_id` (output of the
  `strategy_reclassification` worker, lock 900_062).
- Migrations `0136_classification_source_columns` and
  `0137_stage_applied_batch_id` applied.
- `pg_dump` snapshot of source tables before any P2/P3 apply (insurance).

## Severity tiers

| Tier | Severity tag | Definition | Default gate |
|------|--------------|------------|--------------|
| P0 | `safe_auto_apply` | NULL → label | `--confirm` |
| P1 | `style_refinement` | same family (e.g. Large Blend → Large Growth) | `--confirm` |
| P2 | `asset_class_change` | cross family (e.g. Equity → Fixed Income) | `--confirm --force` |
| P3 | `lost_class` | label → NULL | `--confirm --force --justification` |
| skip | `unchanged` | current == proposed | never written |

Family mapping lives in
`backend/app/domains/wealth/services/classification_family.py`.

## Phase 1 — Review

Generate the diff CSV for manual inspection. Always run this before any
write.

```bash
# Full report (every tier)
python backend/scripts/strategy_diff_report.py --run-id <uuid>

# Per-severity slices for targeted review
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity asset_class_change
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity lost_class
```

Output lands in `reports/strategy_diff_<run8>.csv`. Open in a
spreadsheet, sort by `source_table` + `severity_tier` + `current_label`.
For P2/P3 the `allocation_blocks` column shows the blocks the *current*
label belongs to — those are the blocks that may shift if you apply.

## Phase 2 — Apply P0 (safe additions, ~1,400 rows)

Zero-risk: NULL → specific label is pure information gain.

```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity safe --confirm
```

Type `APPLY` at the prompt. Use `--yes` instead of `--confirm` only in
CI / scripted contexts that have no TTY.

## Phase 3 — Apply P1 (style refinements, ~5,000 rows)

Low risk: same family, no block movement.

```bash
# Re-review the slice first
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity style_refinement

python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity style --confirm
```

## Phase 4 — Apply P2 (asset class changes)

Empirically, P2 splits into two very different sub-buckets that should
be applied separately:

### 4a. Legacy → Canonical vocabulary migration (low risk, large volume)

Rows where the *current* `strategy_label` is from the old 37-category
vocabulary (no entry in `STRATEGY_FAMILY`) and the *proposed* label is
canonical. These were swept into "asset_class_change" only because
`unknown != equity` (etc), but they carry no information loss — the
previous label was already off-taxonomy. Use the dedicated flag:

```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity asset_class \
  --legacy-to-canonical-only --confirm
```

`--legacy-to-canonical-only` waives the `--force` requirement because
the operation is a vocabulary upgrade, not a real reclassification.
Counted in the result summary under `legacy_to_canonical`.

### 4b. True cross-family changes (medium risk, smaller volume)

Rows where both labels are canonical but in different families
(e.g. `Large Blend` → `High Yield Bond`). These need real review —
sample 20+ rows per `source_table` from the CSV first; reject the run
if the cascade is misclassifying a recognisable cohort.

```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity asset_class --confirm --force
```

Without `--legacy-to-canonical-only`, the script will apply BOTH
sub-buckets — only do this after Phase 4a has completed and the true
cross-family residual is small enough to inspect manually.

## Phase 5 — Apply P3 (lost class)

High risk: label becomes NULL. Use `--source-filter fallback` to
restrict the apply to rows where the cascade had no signal at any
layer (Tiingo description, name regex, ADV brochure all came up empty).
For those, NULL is genuinely better than a stale legacy label:

```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity lost --source-filter fallback \
  --confirm --force \
  --justification "Cascade fallback: no canonical label found, NULL preferable to non-canonical legacy"
```

For rows where `classification_source` is `tiingo_description` or
`name_regex` and the proposed label is NULL, treat as suspect — Layer
1/2 fired but didn't reach a canonical label, which usually indicates
a classifier bug rather than a genuine "this fund has no strategy"
case. Inspect manually before applying.

## Combined batches

`--severity` accepts a comma-separated list. Combining tiers in one
invocation is allowed when the operator wants a single audit event for
the whole sweep:

```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity safe,style --confirm
```

Mixed P2/P3 with P0/P1 is supported but discouraged — phase them so a
mid-batch error doesn't strand work in mixed-severity limbo.

## Idempotency

Re-running the same `(run_id, severity)` is a no-op: the candidate set
filters out rows where `applied_at IS NOT NULL`. Safe to re-invoke.

## Rollback

The stage table retains `current_strategy_label` for every applied row.
To rollback a batch, restore the old labels per-source-table and clear
the `applied_*` columns on the stage rows:

```sql
-- Example for sec_manager_funds. Repeat for each source_table touched.
UPDATE sec_manager_funds f
SET strategy_label            = s.current_strategy_label,
    classification_source     = 'rollback',
    classification_updated_at = NOW()
FROM strategy_reclassification_stage s
WHERE s.applied_batch_id = '<batch_id>'
  AND s.source_table     = 'sec_manager_funds'
  AND f.id::text         = s.source_pk;

UPDATE strategy_reclassification_stage
SET applied_at       = NULL,
    applied_by       = NULL,
    applied_batch_id = NULL
WHERE applied_batch_id = '<batch_id>';

REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds;
```

`instruments_universe` rolls back via JSONB merge:

```sql
UPDATE instruments_universe i
SET attributes = COALESCE(i.attributes, '{}'::jsonb) || jsonb_build_object(
    'strategy_label', s.current_strategy_label
)
FROM strategy_reclassification_stage s
WHERE s.applied_batch_id = '<batch_id>'
  AND s.source_table     = 'instruments_universe'
  AND i.instrument_id::text = s.source_pk;
```

## Audit trail

Each apply invocation emits one `AuditEvent`
(`entity_type=strategy_reclassification`, `action=apply_batch`) carrying
the `batch_id`, `run_id`, severities, per-tier counts, and the
operator's justification. Audit writes are best-effort — if no RLS
context is available (CLI invocation), the event is logged via structlog
but skipped at the row level. The script's stdout summary remains the
canonical record either way.

## Anti-patterns

- Auto-applying P2/P3 from cron — operator review is mandatory.
- Skipping the diff report — every apply must be preceded by a CSV.
- Editing the stage table to "fix" data — it is a historical record.
- Refreshing `mv_unified_funds` per-row — the script does it once at end
  of batch.
- Re-running the worker (`strategy_reclassification`) before applying
  the previous run — mixes vintages and breaks audit lineage. Apply
  first, or filter by `run_id` rigorously.

## Out of scope

- N-PORT holdings classifier (Phase 4) — separate sprint after the
  Construction Engine work.
- Round 3 keyword patches — explicitly rejected (diminishing returns).
- A web UI for diff review — CSV → spreadsheet is sufficient today.
