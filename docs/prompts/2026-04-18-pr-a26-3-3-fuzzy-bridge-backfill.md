# PR-A26.3.3 — Fuzzy Fund-Name Bridge Backfill for Authoritative Labels

**Date**: 2026-04-18
**Status**: P0 COMPLETES A26.3.2 — extends the authoritative-first refresh to resolve the ~90% of ETFs/MMFs that lack a direct CIK/ticker bridge, and populates `sec_etfs.strategy_label` for rows where it's NULL.
**Branch**: `feat/pr-a26-3-3-fuzzy-bridge-backfill`
**Predecessors merged**: A21–A26.2, #218 label patch revert, #220 authoritative-first refresh (A26.3.2).

---

## Context — why A26.3.2 alone wasn't enough

Empirical finding 2026-04-18 after A26.3.2 apply against dev DB:

| Block | Total approved in org | Rows with matching `sec_etfs.strategy_label` NOT NULL | Resolved by A26.3.2 | Still contaminated |
|---|---|---|---|---|
| alt_real_estate | 394 | 12 (3%) | ≤12 | 382 (97%) |
| alt_gold | 26 | 3 (12%) | ≤3 | 23 (88%) |
| alt_commodities | 50 | unknown (small) | small | most |
| cash | 36 | — (MMF source) | 1 MMF bridged | 32 orphaned |

**Two gaps behind 382+23+32 = 437 unresolved contaminated rows:**

1. **Bridge gap.** 439 of 985 `sec_etfs` rows have `strategy_label IS NULL`. Even if `iu.ticker → sec_etfs.ticker` matches, the SEC row has no authority to offer. Root cause: sec_bulk_ingestion populated `sec_etfs.ticker` + basic metadata but left `strategy_label` unpopulated (no N-CEN `classification_fund_type` mapped, no Morningstar category).
2. **Join gap.** For MMFs, `iu.attributes.sec_cik → sec_money_market_funds.cik` bridges only 44/373 rows (12%). 328 real MMFs in SEC data exist but are invisible to the catalog.

Post-A26.3.2 smoke proved the proposition is unchanged: propose mode still allocates 51-61% to "cash" via contaminated "Cash Equivalent" labels (32 equity/bond funds kept the bad label; A26.3.2 only resolved 4 of 36).

**A26.3.3 closes both gaps via two bridges:**

1. **Fuzzy fund-name match** for MMFs: `instruments_universe.name` ↔ `sec_money_market_funds.fund_name` (tokenized Jaccard / trigram similarity). High-confidence matches (≥0.85) get `attributes.sec_cik` + `attributes.sec_series_id` written. Enables MMF bridge to jump from 44 to ~300+.
2. **Populate sec_etfs.strategy_label** via Tiingo description cascade on the NULL-labeled 439 rows. Uses the same cascade classifier that A26.3.2 falls back to, but writes result into `sec_etfs.strategy_label` directly (not `instruments_universe.attributes`) so future `refresh_authoritative_labels` runs promote authoritatively.

---

## Scope

**In scope:**
- Migration 0157: `sec_etfs_strategy_label_source` audit column (tracks whether strategy_label came from SEC N-CEN or Tiingo cascade backfill). `sec_mmf_bridge_candidates` table for fuzzy match audit.
- Helper service `backend/app/domains/wealth/services/fuzzy_bridge.py` — deterministic token Jaccard + string-similarity scorer with explicit thresholds (NO LLM, NO NLP library beyond stdlib).
- Script `backend/scripts/bridge_mmf_catalog.py` — one-shot fuzzy matcher. Uses `difflib.SequenceMatcher` + token-set Jaccard. Thresholds 0.85 auto-match, 0.70-0.85 operator review (writes to `sec_mmf_bridge_candidates`). Writes `sec_cik` + `sec_series_id` to `instruments_universe.attributes` on auto-match. Dry-run default.
- Script `backend/scripts/backfill_sec_etfs_strategy_label.py` — runs Tiingo cascade classifier against `sec_etfs` rows with NULL `strategy_label`. Writes `strategy_label` + `strategy_label_source='tiingo_cascade'`. Dry-run default.
- Post-backfill, run `refresh_authoritative_labels.py --apply` a second time to propagate new bridges and new sec_etfs labels into `instruments_universe`.
- Tests for fuzzy bridge thresholds, edge cases, idempotency.
- Runbook extension: full `A26.3.2 + A26.3.3` combined execution sequence.

**Out of scope:**
- Do NOT implement LLM-based matching — deterministic only.
- Do NOT fuzzy-bridge BDCs or ESMA funds — just MMFs this PR (highest-impact).
- Do NOT touch the cascade classifier internals or add new Tiingo round 2 patches — we're populating `sec_etfs.strategy_label` with whatever the current cascade produces, not rewriting the cascade.
- Do NOT modify `instruments_universe.name` — bridge uses existing names as-is.
- Do NOT delete rows that fail to bridge — they remain with current labels + `needs_human_review` where applicable.
- Do NOT frontend-expose the bridge-candidates review table — CLI-only in v1.

---

## Execution Spec

### Section A — Migration 0157

**File:** `backend/app/core/db/migrations/versions/0157_fuzzy_bridge_audit.py`

Down_revision: `0156_authoritative_label_refresh`.

```sql
ALTER TABLE sec_etfs
  ADD COLUMN strategy_label_source TEXT;  -- NULL before backfill, 'sec_bulk' or 'tiingo_cascade' after

CREATE TABLE sec_mmf_bridge_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instrument_id UUID NOT NULL,
  instrument_name TEXT NOT NULL,
  matched_cik TEXT NOT NULL,
  matched_series_id TEXT NOT NULL,
  matched_fund_name TEXT NOT NULL,
  score NUMERIC(5,4) NOT NULL,
  match_tier TEXT NOT NULL,  -- 'auto_applied' (>=0.85) | 'needs_review' (0.70-0.85)
  applied_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_mmf_bridge_instrument ON sec_mmf_bridge_candidates(instrument_id);
CREATE INDEX ix_mmf_bridge_tier ON sec_mmf_bridge_candidates(match_tier) WHERE applied_at IS NULL;
```

Global tables, no RLS. Reversible.

### Section B — Fuzzy bridge service

**File:** `backend/app/domains/wealth/services/fuzzy_bridge.py`

Pure Python (stdlib only — no rapidfuzz, no scikit-learn). Combines two signals:

```python
def _token_set(name: str) -> frozenset[str]:
    """Lowercase, strip punctuation, drop common fund-jargon tokens
    ('fund', 'trust', 'inc', 'llc', 'money', 'market' — but keep
    'government', 'prime', 'tax', 'exempt'), return frozenset of
    remaining tokens."""
    ...

def _jaccard(a: frozenset, b: frozenset) -> float:
    """Token-set Jaccard coefficient."""
    ...

def _seqmatch(a: str, b: str) -> float:
    """difflib.SequenceMatcher ratio on lowercased strings."""
    ...

def score(iu_name: str, sec_name: str) -> float:
    """Combined 0.0-1.0 score. Weighted 0.6 * jaccard + 0.4 * seqmatch.
    Returns 0.0 on empty inputs."""
    ...
```

**Stopword discipline:** the stopword list is critical for muni/govt MMF matching. `"government"` MUST NOT be stopworded because "Vanguard Federal Money Market" vs "Fidelity Government Money Market" differ by that token. `"money market"` IS stopworded as it's universal.

**Hard filter before scoring:** if `sec_name` mmf_category differs from implied category (e.g. iu_name mentions "tax exempt" but candidate is Government), return 0.0. Use a small keyword-to-category map.

**Acceptance:** unit tests cover: exact match, token permutation, typo tolerance, stopword isolation (ensure "Vanguard Federal Money Market" and "Schwab Government Money Market" score < 0.85 despite sharing many tokens), empty inputs, None inputs.

### Section C — MMF bridge script

**File:** `backend/scripts/bridge_mmf_catalog.py`

```
Usage:
  python backend/scripts/bridge_mmf_catalog.py [--dry-run | --apply]
                                                [--min-auto-score 0.85]
                                                [--min-review-score 0.70]
```

Algorithm:
1. Load all `instruments_universe` rows where:
   - `is_active = TRUE`
   - `attributes->>'sec_cik'` does NOT appear in `sec_money_market_funds.cik` (i.e., not already bridged)
   - `name ILIKE '%money market%' OR name ILIKE '%cash management%' OR name ILIKE '%liquidity%'` (pre-filter to plausible MMF candidates; avoids O(n*m) full product)
2. Load all `sec_money_market_funds` rows.
3. For each iu candidate × each SEC MMF, compute `score`. Keep best match per iu.
4. Classify:
   - `score >= 0.85` → **auto-apply**: update `iu.attributes` with `sec_cik`, `sec_series_id`. Insert audit row with `match_tier='auto_applied'`, `applied_at=now()`.
   - `0.70 ≤ score < 0.85` → **needs_review**: insert audit row with `match_tier='needs_review'`, `applied_at=NULL`. No iu update.
   - `score < 0.70` → discard.
5. Report JSON: counts per tier, top 10 auto-matched, top 10 needs_review with their candidate fund names.
6. Dry-run prints decisions without writes.

**Idempotency:** re-running is a no-op. The pre-filter excludes already-bridged instruments.

**Per-match validation:** before auto-applying, verify the claimed match via:
- Token-set jaccard ≥ 0.70
- SequenceMatcher ≥ 0.80
- At least one "family" keyword in common (e.g., both have "Government" or both have "Tax-Exempt") OR both are categorized Prime.

If any verifier fails, downgrade to `needs_review`.

**Acceptance tests:**
- Seed 5 iu rows ("Vanguard Federal Money Market Fund", "Schwab Value Advantage Money Fund", etc.) and 10 sec_mmf rows (including exact matches and decoys). Run apply mode. Assert correct matches were written and decoys didn't cross-bridge.
- Dry-run produces no writes.
- Re-run auto produces zero new changes.

### Section D — sec_etfs strategy_label backfill

**File:** `backend/scripts/backfill_sec_etfs_strategy_label.py`

```
Usage:
  python backend/scripts/backfill_sec_etfs_strategy_label.py [--dry-run | --apply]
```

Algorithm:
1. SELECT rows from `sec_etfs` where `strategy_label IS NULL` (439 rows).
2. For each, load the matching row in `instruments_universe` via `ticker` OR `series_id`. Extract `attributes->>'tiingo_description'` if present.
3. Run the existing Tiingo cascade classifier against the description.
4. Write `sec_etfs.strategy_label = <classifier_output>` + `sec_etfs.strategy_label_source = 'tiingo_cascade'`.
5. Rows with no Tiingo description OR classifier returns NULL → leave `strategy_label IS NULL` with `strategy_label_source = 'unclassified'`.
6. Report: count populated, count unclassified, top 20 new strategy_label values, sample 10 (ticker, fund_name, new_label).

**Acceptance:**
- Dry-run output shows plausible distribution (no single label dominates; some NULLs for ETFs without Tiingo data).
- Apply mode increments `sec_etfs.strategy_label` non-NULL count.
- Re-run is no-op (only touches NULL rows).

### Section E — Final refresh

Document in runbook: after Sections C + D apply, re-run `refresh_authoritative_labels.py --apply`. Expected outcome:
- MMF resolutions: ~300 more rows (up from 1 to ~300+).
- sec_etf resolutions: ~440 more rows (up from 507 to ~950).
- `needs_human_review` count drops proportionally.
- Post-smoke: cash allocation drops from 60% to 5-15% range (real MMFs compete realistically).

### Section F — Integration tests

**File:** `backend/tests/scripts/test_bridge_mmf_catalog.py` + `backend/tests/scripts/test_backfill_sec_etfs_strategy_label.py`.

Each file: 4-5 tests covering dry-run, apply, idempotency, threshold boundary cases, bad-input tolerance.

### Section G — Runbook update

**File:** `docs/reference/authoritative-label-refresh-runbook.md` — extend with section "A26.3.3 extension".

Commands in order:
```bash
# 1. A26.3.3 migrations
make migrate

# 2. Fuzzy bridge MMFs (dry-run first)
python backend/scripts/bridge_mmf_catalog.py
python backend/scripts/bridge_mmf_catalog.py --apply

# 3. Backfill sec_etfs.strategy_label (dry-run first)
python backend/scripts/backfill_sec_etfs_strategy_label.py
python backend/scripts/backfill_sec_etfs_strategy_label.py --apply

# 4. Re-run authoritative labels refresh to propagate new bridges
python backend/scripts/refresh_authoritative_labels.py --apply

# 5. Verify via smoke
python backend/scripts/pr_a26_2_smoke.py
```

Document expected outcomes at each step with concrete numbers (post-dev-DB validation).

---

## Ordering inside this PR

A (migration) → B (fuzzy_bridge service + tests) → C (bridge script + tests) → D (sec_etfs backfill script + tests) → G (runbook) → E (documented in runbook; not a code section). One commit per Section A-D + one for runbook.

## Global guardrails

- `CLAUDE.md` rules. Async-first where applicable; sync scripts OK for one-shot tooling.
- No new Python dependencies.
- `make check` green.
- Do NOT touch: optimizer, composition, propose/approve, frontend, cascade classifier internals.

## Final report format

1. Migration up/down round-trip.
2. Unit + integration test output.
3. MMF bridge dry-run output → apply output: count before/after of `sec_mmf.cik` bridged to `instruments_universe`.
4. sec_etfs backfill dry-run → apply: count of `strategy_label IS NOT NULL` before/after.
5. Second-pass `refresh_authoritative_labels.py --apply` output showing increased counts in `applied_by_source.sec_mmf` + `applied_by_source.sec_etf`.
6. `pr_a26_2_smoke.py` final run — **paste complete allocation distribution by family** (equity / FI / alt / cash). Expected: cash 5-15%, alt 10-20%, FI 30-50%, equity 20-50%. Sharpe 1.5-2.5.
7. List deviations from spec.
