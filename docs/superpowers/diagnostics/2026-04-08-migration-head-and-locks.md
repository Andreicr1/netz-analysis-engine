# Migration Head & Worker Lock Inventory — 2026-04-08

> **Source:** Phase 0 Tasks 0.2 + 0.4 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.
> **Purpose:** Confirm the real Alembic head before Phase 1 starts numbering portfolio migrations, verify the 3 reserved worker lock IDs are unused, and resolve the uncommitted-`regime_fit.py` ambiguity that the plan flagged in Task 0.4.

## Summary

| # | Item | Plan assumption | Reality at HEAD | Action taken |
|---|---|---|---|---|
| 1 | Alembic head | `0096_discovery_fcl_keyset_indexes` | **`0097_curated_institutions_seed`** | CLAUDE.md updated; portfolio range shifted +1 (DL20) |
| 2 | Portfolio reserved range | 0097-0104 (8 migrations) | Same count, **shifted to 0098-0105** | Plan patched in DL20, all phase headers, task headings, filenames, commit messages, gate checklists |
| 3 | Lock 900_100 (`live_price_poll`) | Reserved unused | **Unused — confirmed** | No-op; Phase 9 Task 9.1 will register it |
| 4 | Lock 900_101 (`construction_run_executor`) | Reserved unused | **Unused — confirmed** | No-op; Phase 3 Task 3.4 will register it |
| 5 | Lock 900_102 (`alert_sweeper`) | Reserved unused | **Unused — confirmed** | No-op; Phase 7 Task 7.4 will register it |
| 6 | `regime_fit.py` lock | "TBD — quant draft says 900_026, file uncommitted" | **NO LOCK AT ALL** (quant draft was speculative) | DL19 patched; Phase 7 Task 7.3 must ADD lock 900_026 |
| 7 | Task 0.4 — uncommitted `regime_fit.py` | Three options (commit / stash / fold-into-Phase-7) | **RESOLVED** — committed in `9c29a140` already | Phase 7 Task 7.3 only needs to add the lock, no integration debt |

---

## 1. Alembic head — DRIFTED

### Step 1: List recent migrations

```bash
$ ls backend/app/core/db/migrations/versions/ | grep -E "^009[0-9]_" | sort
0090_instruments_universe_slug.py
0091_wealth_library_pins.py
0092_wealth_library_triggers.py
0093_fund_risk_metrics_composite_pk.py
0094_mv_unified_funds_aum_native_fx.py
0095_mv_unified_funds_share_class.py
0096_discovery_fcl_keyset_indexes.py
0097_curated_institutions_seed.py
```

The plan was anchored against `0096_discovery_fcl_keyset_indexes`. A new migration `0097_curated_institutions_seed.py` exists.

### Step 2: Confirm `0097_curated_institutions_seed` is the real head

```python
# backend/app/core/db/migrations/versions/0097_curated_institutions_seed.py:10-11
revision = "0097_curated_institutions_seed"
down_revision = "0096_discovery_fcl_keyset_indexes"
```

Yes — `0097_curated_institutions_seed` is a linear successor of `0096_discovery_fcl_keyset_indexes`. It is the real head.

### Step 3: Verify it does not conflict with portfolio scope

```python
# backend/app/core/db/migrations/versions/0097_curated_institutions_seed.py:16-31
def upgrade() -> None:
    op.create_table(
        "curated_institutions",
        sa.Column("institution_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cik", sa.String(20), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "idx_curated_institutions_category",
        "curated_institutions",
        ["category", "display_order"],
    )
    seed = [
        # Endowments
        ("yale_endowment", "Yale University Endowment", "endowment", "USA"),
        ...
    ]
```

`curated_institutions` is a Discovery seed table for endowments, family offices, and sovereigns. It seeds the institutional filer browser. **Zero collision** with portfolio scope (no shared columns, no shared FKs, no shared indexes, no shared workers, no shared lock IDs).

### Step 4: Find when 0097 landed

```bash
$ git log --oneline -1 backend/app/core/db/migrations/versions/0097_curated_institutions_seed.py
365cd470 feat(db): curated_institutions table + seed (Ivy endowments, family offices, sovereign)
```

Commit `365cd470` landed between draft authoring and Phase 0 execution. Confirms drift is real, not a draft error.

### Step 5: Sync CLAUDE.md

`CLAUDE.md` line 98 was:

> Migrations via Alembic. App uses async asyncpg. Current migration head: `0095_mv_unified_funds_share_class`.

**Updated to:**

> Migrations via Alembic. App uses async asyncpg. Current migration head: `0097_curated_institutions_seed`.

The original `0095` reference was already 2 migrations stale even before the portfolio sprint started. This is now fully synchronized.

### Step 6: Update the plan's reserved range

DL20 changed from "Migration range 0097-0104 reserved for this plan" to "Migration range 0098-0105 reserved for this plan", with a forensic note explaining the cause. All Phase 1 / Phase 2 task headings, filenames, test filenames, commit messages, and gate checklists shifted accordingly. Total +1 shift across 8 migrations and ~30 references in the plan.

---

## 2. Worker lock IDs 900_100 / 900_101 / 900_102 — CONFIRMED UNUSED

### Step 1: Grep all wealth + credit workers

```bash
$ rg -n "900_100|900_101|900_102|pg_try_advisory_lock\(900" backend
backend/scripts/run_wealth_embedding_backfill.py:118:
    lock = await db.execute(sql_text("SELECT pg_try_advisory_lock(900041)"))
```

Only one match: `900041` (wealth_embedding worker) at line 118 of a script. Zero matches for `900_100`, `900_101`, `900_102`. The 3 reserved IDs are clean.

### Step 2: Reserved IDs and their consumers

| Lock ID | Worker | Phase / Task that registers it |
|---|---|---|
| `900_100` | `live_price_poll` | Phase 9 Task 9.1 |
| `900_101` | `construction_run_executor` | Phase 3 Task 3.4 |
| `900_102` | `alert_sweeper` | Phase 7 Task 7.4 |

### Step 3: Existing portfolio-adjacent locks (untouched)

Confirmed via grep against the existing inventory in CLAUDE.md §Data Ingestion Workers:

| Lock ID | Worker | Status |
|---|---|---|
| `900_008` | `portfolio_eval` | Untouched — Phase 7 Task 7.1 will extend to write `portfolio_alerts` |
| `42` | `drift_check` | Untouched — Phase 7 Task 7.2 will extend |
| `900_026` | `regime_fit` (PROPOSED — does not exist yet) | **Phase 7 Task 7.3 must add this lock** (see §3 below) |
| `900_030` | `portfolio_nav_synthesizer` | Untouched — Phase 9 Task 9.7 reads from it |
| `900_007` | `risk_calc` | Untouched |
| `900_071` | `global_risk_metrics` | Untouched |

---

## 3. `regime_fit.py` lock ID — NO LOCK EXISTS (quant draft was speculative)

### Step 1: Grep `regime_fit.py` for any advisory lock construct

```bash
$ rg -n "pg_try_advisory_lock|advisory_xact_lock|advisory_lock" \
    backend/app/domains/wealth/workers/regime_fit.py
```

**Zero matches.** The file at HEAD has no advisory lock at all.

### Step 2: Confirm against quant draft §F.2 claim

The quant draft cited "regime_fit lock 900_026" as if it existed. It does not. The draft was prospectively proposing a lock ID without verifying the file. This is exactly the "verify the surface before consuming it" failure that Phase 0 exists to catch.

### Step 3: Action

`DL19` patched: `regime_fit (TBD — confirm in Phase 0)` → `regime_fit (no lock currently — Phase 7 Task 7.3 must add 900_026)`. Phase 7 Task 7.3 acquires a NEW responsibility: in addition to extending the worker to write `portfolio_alerts` rows, it must wrap the worker body in `pg_try_advisory_lock(900_026)` and unlock in `finally`. The proposed `900_026` is still free (zero conflicts in the lock inventory).

---

## 4. Task 0.4 — uncommitted `regime_fit.py` — RESOLVED

### Step 1: Check git history

```bash
$ git log --oneline -1 backend/app/domains/wealth/workers/regime_fit.py
9c29a140 fix(regime_fit): add strict=False to zip() calls (B905)
```

```bash
$ git status --short backend/app/domains/wealth/workers/regime_fit.py
(no output — file is clean)
```

The file is committed and clean. The `RESUME-PORTFOLIO-ENTERPRISE-PLAN.md` resume doc and the plan's Phase 0 Task 0.4 both assumed `regime_fit.py` was uncommitted at plan-write time. Between draft authoring and Phase 0 execution, Andrei (or a prior session) committed it as `9c29a140 fix(regime_fit): add strict=False to zip() calls (B905)`.

### Step 2: Read the actual content of the file (sanity)

```bash
$ rg -n "regime_fit" backend/app/domains/wealth/workers/regime_fit.py | head -5
11:    fred_ingestion → risk_calc → portfolio_eval → regime_fit
14:    python -m app.workers.regime_fit
261:async def run_regime_fit() -> dict[str, Any]:
315:    asyncio.run(run_regime_fit())
```

The worker is alive and functional, just unlocked. Bug fix `9c29a140` was a `zip(strict=False)` addition for B905 — a minor lint fix, not a structural change.

### Step 3: Disposition

Task 0.4 in the plan listed three options (commit, stash, fold-into-Phase-7-Task-7.4). **Selected: Option 4 (not in plan) — RESOLVED, no integration needed.** The committed version is the one Phase 7 will extend. Phase 7 Task 7.3 only needs to (a) add the advisory lock at 900_026 and (b) extend the worker body to write a `portfolio_alerts` row on regime transitions. No diff to reconcile, no merge conflict to manage.

---

## Verification commands (re-runnable)

```bash
# Real head
ls backend/app/core/db/migrations/versions/ | grep -E "^009[0-9]_|^010[0-9]_" | sort | tail -5

# Lock inventory
rg -n "900_100|900_101|900_102|pg_try_advisory_lock\(900_10" backend

# regime_fit lock state
rg -n "pg_try_advisory_lock|advisory_xact_lock" backend/app/domains/wealth/workers/regime_fit.py

# regime_fit commit history
git log --oneline -1 backend/app/domains/wealth/workers/regime_fit.py
```

## Disposition

Task 0.2 + Task 0.4 complete. Phase 0 gate items 1-3 cleared. The plan has been forensically updated to match the real branch state. Phase 1 starts at migration `0098_model_portfolio_lifecycle_state.py` (NOT `0097_*`) and the entire 8-migration range now occupies `0098-0105`.
