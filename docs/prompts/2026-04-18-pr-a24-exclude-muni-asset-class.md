# PR-A24 — Exclude US Muni Bonds as Strategic Asset Class

**Date**: 2026-04-18
**Status**: P1 — small cleanup after A23 merge. Removes the "needs_human_review" backlog introduced by VTEB/MUB.
**Branch**: `feat/pr-a24-exclude-muni-asset-class`
**Predecessors merged**: PR-A21 (#207), PR-A22 (#209), PR-A23 (#210).

---

## Context

A23 left VTEB (Vanguard Tax-Exempt Bond ETF) and MUB (iShares National Muni) flagged as `needs_human_review` because muni bonds have no destination block in `allocation_blocks` (neither `fi_us_aggregate` nor a hypothetical `fi_us_aggregate_muni` was deemed appropriate). A23's canonical reference left the block_id as `fi_us_aggregate_muni` with a note that the operator would decide whether to create it.

**Product decision (Andrei, 2026-04-18):** US muni bonds are categorically excluded from the Netz wealth engine. Rationale:
- The tax-exempt premium that makes muni economically attractive applies only to US taxpayers.
- Netz's client base is international portfolios (Brazilian PFICs / offshore structures), which do not benefit from US muni tax treatment.
- Holding muni in an international structure introduces tax inefficiency vs. direct Treasury exposure at equivalent duration/credit.
- No plan to create `fi_us_aggregate_muni` block.

This PR converts the A23 "needs_human_review" state for muni instruments into a categorical exclusion with clear semantics.

---

## Scope

**In scope:**
- Add explicit `EXCLUDED_STRATEGY_LABELS` set to `backend/scripts/_pr_a23_canonical_reference.py` (or a new sibling module).
- Update `backend/app/domains/wealth/services/universe_auto_import_classifier.py` to detect excluded strategy labels and return `(None, "excluded_asset_class")` — distinct signal from `needs_human_review`.
- Update the caller in `backend/app/domains/wealth/services/universe_auto_import_service.py` to skip row creation entirely when classifier returns `excluded_asset_class`. Do NOT insert into `instruments_org`. Do NOT set `needs_human_review` on the universe row (set `attributes.strategic_excluded_reason = "<label>"` instead for audit).
- Migration 0152: DELETE existing `instruments_org` rows where linked `instruments_universe.attributes->>'strategy_label'` matches any excluded label AND `source = 'universe_auto_import'`. Leave manually-added rows (`source != 'universe_auto_import'`) untouched — operator explicitly chose them. Log affected row count. Reversible down-migration (back up deleted rows to `pr_a24_muni_exclusion_backup` table).
- Update `pr_a23_classifier_audit.py` to surface "excluded asset class contamination" as a distinct report section (separate from mismatches and needs-review).
- Update `pr_a23_reclassify_auto_import.py` to honor the exclusion path (delete instead of flag-and-null).
- Unit tests covering: classifier returns `excluded_asset_class` for muni strategy labels; service skips insert; migration deletes only auto-import rows.

**Out of scope:**
- Do NOT add other asset-class exclusions (leveraged ETFs, crypto ETFs, thematic single-country). Muni only. Future exclusions are separate PRs with separate product justification.
- Do NOT touch allocation_blocks, strategic_allocation, block_mapping, optimizer, or any quant code.
- Do NOT delete rows from `instruments_universe` — the global catalog keeps everything; exclusion is only at the org-scoped level.
- Do NOT re-run any A23 scripts as part of this PR. Operator triggers them separately per the runbook.

---

## Execution Spec

### Section A — Exclusion reference

**File:** extend `backend/scripts/_pr_a23_canonical_reference.py` (re-export from service layer if needed).

Add:
```python
# US muni bonds are categorically excluded from the Netz wealth engine.
# Muni tax-exempt premium applies only to US taxpayers; Netz clients are
# international (Brazilian offshore structures) that do not benefit from
# it. Exclusion is mandate-level, not a classification fallback.
EXCLUDED_STRATEGY_LABELS: frozenset[str] = frozenset({
    "Muni National Interm",
    "Muni National Short",
    "Muni National Long",
    "Muni Single State Interm",
    "Muni Single State Short",
    "Muni Single State Long",
    "High Yield Muni",
    "Muni California Intermediate",
    "Muni California Long",
    "Muni New York Intermediate",
    "Muni New York Long",
    "Muni Target Maturity",
})
```

List is exhaustive enough to cover Morningstar/Lipper muni categories seen in the catalog; verify against `SELECT DISTINCT attributes->>'strategy_label' FROM instruments_universe WHERE attributes->>'strategy_label' ILIKE '%muni%'` during implementation and extend if labels surface that aren't listed.

Remove VTEB and MUB from `CANONICAL_REFERENCE` (they no longer have a canonical target block). Add a top-of-file comment noting the exclusion.

**Acceptance:** module imports clean, frozenset ensures immutability.

### Section B — Classifier exclusion branch

**File:** `backend/app/domains/wealth/services/universe_auto_import_classifier.py`

Add an early exclusion check (before any rule/cosine/LLM layer):

```python
if strategy_label and strategy_label in EXCLUDED_STRATEGY_LABELS:
    return None, "excluded_asset_class"
```

**Acceptance:** unit test `test_universe_auto_import_classifier.py`: seed a muni-labeled input → classifier returns `(None, "excluded_asset_class")`, NOT `needs_human_review` and NOT a block_id.

### Section C — Service-layer skip

**File:** `backend/app/domains/wealth/services/universe_auto_import_service.py`

When classifier returns `excluded_asset_class`:
- Do NOT insert a row into `instruments_org`.
- Set `instruments_universe.attributes.strategic_excluded_reason = <label>` (JSONB merge, not replace, to preserve other attributes). This is an audit breadcrumb — future imports won't reconsider.
- Emit log `{"event": "auto_import_excluded", "ticker": ..., "strategy_label": ..., "reason": "excluded_asset_class"}`.

**Acceptance:** integration test: auto-import a batch with one muni ticker → `instruments_org` row count unchanged by that ticker; `instruments_universe.attributes.strategic_excluded_reason` populated; log emitted.

### Section D — Migration 0152

**File:** `backend/app/core/db/migrations/versions/0152_exclude_muni_auto_import.py`

Down_revision: `0151_fix_known_strategy_labels`.

Steps (transactional):
1. Create backup table `pr_a24_muni_exclusion_backup` with same columns as `instruments_org` plus `deleted_at TIMESTAMPTZ` column.
2. `INSERT INTO pr_a24_muni_exclusion_backup SELECT *, now() FROM instruments_org WHERE instrument_id IN (SELECT instrument_id FROM instruments_universe WHERE attributes->>'strategy_label' IN (<excluded labels>)) AND source = 'universe_auto_import'`.
3. `DELETE FROM instruments_org WHERE instrument_id IN (...) AND source = 'universe_auto_import'`. Log row count.
4. `UPDATE instruments_universe SET attributes = jsonb_set(attributes, '{strategic_excluded_reason}', to_jsonb(attributes->>'strategy_label')) WHERE attributes->>'strategy_label' IN (<excluded labels>) AND (attributes ? 'strategic_excluded_reason') IS NOT TRUE`. Log row count.

Down-migration: restore rows from `pr_a24_muni_exclusion_backup` into `instruments_org`, drop the backup table, clear `strategic_excluded_reason` keys added by the up-migration (track via a sentinel column in the backup table — include a boolean `universe_flag_set_by_this_migration` to know which universe rows were newly flagged).

**Acceptance:**
- `make migrate` clean.
- Dev DB post-migration: `SELECT COUNT(*) FROM instruments_org io JOIN instruments_universe iu USING (instrument_id) WHERE iu.attributes->>'strategy_label' IN (<muni labels>) AND io.source = 'universe_auto_import'` returns 0.
- `make migrate downgrade -1` restores the rows.

### Section E — Audit + reclassify script updates

**File:** `backend/scripts/pr_a23_classifier_audit.py`

Add new report section:
```json
"excluded_asset_class_contamination": {
  "instruments_org_rows_remaining": 0,  // should be 0 post-migration
  "instruments_universe_without_exclusion_flag": 0  // should be 0
}
```

**File:** `backend/scripts/pr_a23_reclassify_auto_import.py`

If classifier returns `excluded_asset_class` during reclassification, DELETE the `instruments_org` row (same path as the migration) instead of nulling `block_id`. Honor `block_overridden=true` guard (do not delete operator-curated rows). Increment a separate counter: `rows_deleted_as_excluded`.

**Acceptance:** reclassify dry-run on dev DB (post-migration) shows zero pending changes. Live run shows zero. Audit report shows zero contamination.

---

## Ordering inside this PR

A → B → C → D → E. Each as its own commit.

## Global guardrails

- `CLAUDE.md` rules. Async-first, RLS via `SET LOCAL`, `expire_on_commit=False`, `lazy="raise"`.
- No new dependencies.
- `make check` green.
- One commit per Section.
- Do not touch: optimizer, candidate_screener, block_mapping, allocation_blocks, strategic_allocation, construction_run_executor, block_coverage_service.

## Final report format

1. Dev DB pre-migration count of VTEB/MUB/other muni rows in `instruments_org` (via audit script).
2. Migration execution log (counts per step).
3. Dev DB post-migration count (expect 0).
4. Test output (pytest -v for classifier + service + migration).
5. Audit script re-run post-migration showing zero contamination.
6. Reclassify dry-run post-migration showing zero pending changes.
