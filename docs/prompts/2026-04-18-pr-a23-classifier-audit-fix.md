# PR-A23 — Classifier Audit + Fallback Fix + Strategy Label Sanitization

**Date**: 2026-04-18
**Status**: P1 — depends on PR-A21 (sanitized `instruments_org`). Can run in parallel with or after PR-A22.
**Branch**: `feat/pr-a23-classifier-audit-fix`
**Predecessors merged**: PR-A21. Ideally also PR-A22, but not strictly required.

---

## Context — what this PR fixes

Diagnostic (dev DB, 2026-04-18) surfaced three distinct classifier-layer defects that cause structurally miscategorized instruments in `instruments_org`:

### Defect D1 — `fallback_fi_aggregate` at `universe_auto_import_classifier.py:136`

Concrete example: VTEB (Vanguard Tax-Exempt Bond ETF — municipal bonds) is classified into `fi_us_aggregate`. Taxable aggregate bond funds (AGG, BND) and muni bonds have fundamentally different risk/return/tax profiles. The current fallback code path silently buckets anything unclassified-but-bond-like into `fi_us_aggregate`, producing false candidates for the cascade.

### Defect D2 — equity classifier dumps foreign-developed into `na_equity_large`

Concrete example: EFA (iShares MSCI EAFE, 100% developed markets ex-US) is classified into `na_equity_large`. This is an equity-side analog of D1 — the classifier has insufficient geography signal and defaults to the most common US-equity block.

### Defect D3 — upstream `strategy_label` corruption

Concrete examples: AGG and EFA both have `attributes->>'strategy_label' = 'Government Bond'` in `instruments_universe`. AGG is an aggregate bond fund, not government-only. EFA is an equity fund. These are errors in the upstream data ingestion (likely SEC/ESMA parsing in `data_providers/sec/` or the ESMA ingestion worker) OR in the `backfill_strategy_label.py` script. The classifier downstream cannot be correct if its input is wrong.

---

## Scope

**In scope:**
- Audit-only script `backend/scripts/pr_a23_classifier_audit.py` that produces a report of suspected misclassifications with (current, inferred, confidence) per instrument, WITHOUT mutating any data.
- Fix the `fallback_fi_aggregate` branch at `backend/app/domains/wealth/services/universe_auto_import_classifier.py:136` and any sibling equity fallback: replace silent mis-bucketing with `block_id = NULL` + `attributes.needs_human_review = true`.
- Batch re-classification script `backend/scripts/pr_a23_reclassify_auto_import.py` that re-runs the corrected classifier over existing `source='universe_auto_import'` rows and updates `block_id` where the new classifier result differs from the stored value. Writes an audit log row per change.
- Strategy-label patch migration: for a narrow, verified set of universally-wrong labels (AGG, BND, EFA, EEM, VEA, VWO, VTEB, MUB, and any others surfaced by the audit script with high confidence), correct `instruments_universe.attributes->'strategy_label'` via a data migration.
- Unit tests for the classifier changes.

**Out of scope:**
- Do NOT rewrite the classifier algorithm. Keep the existing three-layer structure (rules → cosine similarity → LLM fallback). Only replace the *silent fallback bucket* with an explicit NULL+flag.
- Do NOT add ML or LLM passes to identify misclassifications. The audit uses deterministic ticker/ISIN → canonical strategy_label mappings hardcoded from public fund fact sheets for the ~30 most-liquid ETFs. This is a narrow, high-confidence patch, not a full re-labeling.
- Do NOT change `block_mapping.py` (strategy_label → block_id) except additions; do not remove entries.
- Do NOT touch SEC ingestion workers or ESMA ingestion worker. The upstream `strategy_label` corruption will persist for long-tail tickers; this PR fixes the top-30 by liquidity only. A future PR can address upstream.
- Do NOT run the re-classification against prod. This PR ships the script; operator runs it manually after review.

---

## Execution Spec

### Section A — Audit script

**File:** `backend/scripts/pr_a23_classifier_audit.py`

Reads (never writes). Identifies suspected misclassifications via a **canonical reference table** hardcoded in the script — the ~30 most-liquid ETFs with their known-correct `strategy_label` and `block_id`:

```python
CANONICAL_REFERENCE = {
    # Equity - US
    "SPY": ("Large Blend", "na_equity_large"),
    "IVV": ("Large Blend", "na_equity_large"),
    "VOO": ("Large Blend", "na_equity_large"),
    "VTI": ("Large Blend", "na_equity_large"),
    "QQQ": ("Large Growth", "na_equity_growth"),
    "VUG": ("Large Growth", "na_equity_growth"),
    "IWF": ("Large Growth", "na_equity_growth"),
    "VTV": ("Large Value", "na_equity_value"),
    "IWD": ("Large Value", "na_equity_value"),
    "IWM": ("Small Blend", "na_equity_small"),
    "VB": ("Small Blend", "na_equity_small"),
    # Equity - International
    "EFA": ("Foreign Large Blend", "dm_europe_equity"),
    "VEA": ("Foreign Large Blend", "dm_europe_equity"),
    "IEFA": ("Foreign Large Blend", "dm_europe_equity"),
    "EEM": ("Diversified Emerging Mkts", "em_equity"),
    "VWO": ("Diversified Emerging Mkts", "em_equity"),
    "IEMG": ("Diversified Emerging Mkts", "em_equity"),
    # Fixed Income - Treasury / Aggregate
    "AGG": ("Intermediate Core Bond", "fi_us_aggregate"),
    "BND": ("Intermediate Core Bond", "fi_us_aggregate"),
    "IEF": ("Intermediate Government", "fi_us_treasury"),
    "TLT": ("Long Government", "fi_us_treasury"),
    "SHY": ("Short Government", "fi_us_treasury"),
    "GOVT": ("Intermediate Government", "fi_us_treasury"),
    # Fixed Income - Muni (NOT fi_us_aggregate)
    "VTEB": ("Muni National Interm", "fi_us_aggregate_muni"),  # see note
    "MUB": ("Muni National Interm", "fi_us_aggregate_muni"),
    # Fixed Income - TIPS / HY / IG
    "TIP": ("Inflation-Protected Bond", "fi_us_tips"),
    "SCHP": ("Inflation-Protected Bond", "fi_us_tips"),
    "HYG": ("High Yield Bond", "fi_us_high_yield"),
    "JNK": ("High Yield Bond", "fi_us_high_yield"),
    "LQD": ("Corporate Bond", "fi_ig_corporate"),
    # Alts
    "GLD": ("Precious Metals", "alt_gold"),
    "IAU": ("Precious Metals", "alt_gold"),
    "DBC": ("Commodities Broad Basket", "alt_commodities"),
    "GSG": ("Commodities Broad Basket", "alt_commodities"),
    "VNQ": ("Real Estate", "alt_real_estate"),
}
```

**Note on `fi_us_aggregate_muni`:** if `allocation_blocks` does not have this block, report it as a gap for operator decision; do not create it in this PR. For now VTEB/MUB should classify to `None` with `needs_human_review=true` until the operator decides whether to split muni from aggregate.

Audit output (JSON + human summary):
```json
{
  "strategy_label_mismatches": [
    {"ticker": "AGG", "current_label": "Government Bond",
     "canonical_label": "Intermediate Core Bond",
     "n_rows_in_universe": 1}
  ],
  "block_id_mismatches_in_instruments_org": [
    {"ticker": "EFA", "organization_id": "...",
     "current_block_id": "na_equity_large",
     "canonical_block_id": "dm_europe_equity"}
  ],
  "fallback_bucket_contamination": {
    "fi_us_aggregate_contaminated_by": [
      {"ticker": "VTEB", "canonical_block": "muni (unresolved)"}
    ]
  }
}
```

**Acceptance:** script runs against dev DB, produces JSON that matches the defects observed (AGG/EFA strategy_label mismatches, VTEB in `fi_us_aggregate`, EFA in `na_equity_large`).

### Section B — Classifier fallback fix

**File:** `backend/app/domains/wealth/services/universe_auto_import_classifier.py` (around line 136 and any sibling fallback).

Current behavior (roughly):
```python
# line ~136
return "fi_us_aggregate", "fallback_fi_aggregate"
```

New behavior:
```python
return None, "needs_human_review"
```

And the caller (wherever `universe_auto_import_service.py` consumes this) must handle `None` by:
- Setting `instruments_org.block_id = NULL`
- Setting `attributes.needs_human_review = True` (via JSONB merge, not replace)
- Logging a structured event `{"event": "classifier_needs_review", "ticker": ..., "reason": "fallback_..."}`

Do the same for any equity-side fallback bucket (audit the file — there may be a `fallback_equity_large` or similar). If uncertain, add a comment and flag in the audit report rather than guessing.

**Acceptance:**
- Unit test: mock a "muni-like" input (bond with muni in name, no other signals) — classifier returns `(None, "needs_human_review")`, not `("fi_us_aggregate", "fallback_fi_aggregate")`.
- Unit test: mock a well-known equity input (SPY metadata) — classifier still returns `("na_equity_large", ...)` correctly. No regression on happy path.

### Section C — Batch re-classification script

**File:** `backend/scripts/pr_a23_reclassify_auto_import.py`

For every row in `instruments_org` with `source = 'universe_auto_import'`:
1. Re-run the classifier using current metadata from `instruments_universe`.
2. If new `block_id` differs from stored `block_id`, update the row. Record a before/after audit entry.
3. If classifier returns `None`, set `block_id = NULL` and `attributes.needs_human_review = True` on the corresponding `instruments_universe` row (NOT on `instruments_org` — universe is the canonical place for human-review flags).

Script MUST:
- Be idempotent (re-running produces zero changes on second run).
- Run in a single transaction per organization_id for safety.
- Emit a summary at the end: `{"orgs_processed": N, "rows_updated": M, "rows_flagged_for_review": K}`.
- Support a `--dry-run` flag that only prints intended changes.

**Acceptance:**
- Dry-run against dev DB: output plausible change counts (at minimum, VTEB → NULL+flag, EFA → dm_europe_equity if strategy_label is corrected first via Section D).
- Live run against dev DB: changes applied, re-run dry-run shows zero pending changes.
- Unit test: seed a minimal fixture with a VTEB-like row, run script (not dry), assert block_id = NULL and needs_human_review flag set.

### Section D — Strategy label data migration

**File:** `backend/app/core/db/migrations/versions/0151_fix_known_strategy_labels.py`

Pure data migration — no schema changes. Uses the `CANONICAL_REFERENCE` list from Section A (import it, don't duplicate). For each ticker in that dict, update `instruments_universe.attributes->'strategy_label'` to the canonical value IF the current value differs.

Use JSONB update semantics:
```sql
UPDATE instruments_universe
SET attributes = jsonb_set(attributes, '{strategy_label}', '"Intermediate Core Bond"'::jsonb)
WHERE ticker = 'AGG'
  AND attributes->>'strategy_label' IS DISTINCT FROM 'Intermediate Core Bond';
```

Down-migration: write the inverse update (restore the prior value). Since we can't recover the *exact* prior strings without a snapshot table, capture pre-migration state into a one-off `pr_a23_strategy_label_backup` table within the migration, so down can restore.

**Acceptance:**
- `make migrate` clean.
- Post-migration: AGG has `strategy_label = 'Intermediate Core Bond'`, EFA has `'Foreign Large Blend'`, VTEB has `'Muni National Interm'`, and so on for the canonical reference list.
- `make migrate downgrade -1`: values restored to pre-migration state.

---

## Ordering + dependencies

- Section A (audit) ships first and can run before B/C/D — it is read-only.
- Section D (strategy label fix) must run BEFORE Section C (re-classification), because the classifier reads strategy_label as a primary signal.
- Section B (classifier fallback fix) must ship before Section C (otherwise re-classification would re-bucket VTEB to fi_us_aggregate again).
- Order inside this PR: A → B → D → C.

---

## Global guardrails

- `CLAUDE.md` rules.
- No new dependencies.
- `make check` green.
- One commit per Section.
- Do not touch `optimizer_service.py`, `construction_run_executor.py`, `candidate_screener.py`, `block_coverage_service.py`.

## Final report format

1. Audit script output (JSON) against dev DB pre-migration.
2. Migration execution log.
3. Classifier unit test output.
4. Re-classification dry-run output + live run summary.
5. Audit script re-run post-everything — expect ~zero `strategy_label_mismatches` for tickers in the canonical reference, and VTEB/MUB flagged for review.
6. List of tickers that landed in `needs_human_review` state for operator triage.
